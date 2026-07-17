"""Exness adapter via MetaTrader 5 — market data + broker.

Exness has no REST trading API; it is driven through the **MetaTrader 5**
terminal. This module talks to MT5 through the official ``MetaTrader5`` Python
package, which **only runs on Windows** (a Windows PC or VPS with the MT5
terminal installed and logged into your Exness account). It will import fine
anywhere, but ``connect()`` requires that package + terminal.

Safety model (deliberate, and consistent with the OANDA adapter):

* ``ExnessMT5Broker`` reads the connected account's *trade mode*. If it detects a
  **REAL / live** account it **refuses to place any order** unless you construct
  it with ``confirm_live=True``. Demo accounts trade freely.
* The live switch is yours to throw. Run demo first, then decide.

The feed and broker take an injected ``mt5`` handle (the module, or a fake in
tests), so all the parsing / sizing / gating logic is unit-tested offline
without the Windows-only package.
"""

from __future__ import annotations

import math
import time
from collections.abc import AsyncIterator
from typing import Any

from babayaga.integration.broker import Broker, Position
from babayaga.integration.market_data import MarketDataFeed
from babayaga.kernel.events import Candle, Fill, Order, Side


class Mt5Error(RuntimeError):
    pass


def to_mt5_symbol(symbol: str, suffix: str = "") -> str:
    """``XAU/USD`` -> ``XAUUSD`` (+ optional broker suffix, e.g. ``XAUUSDm``)."""
    return symbol.replace("/", "").upper() + suffix


def from_mt5_symbol(mt5_symbol: str, suffix: str = "") -> str:
    """``EURUSDm`` (suffix ``m``) -> ``EUR/USD``. Inverse of :func:`to_mt5_symbol`."""
    base = mt5_symbol
    if suffix and base.endswith(suffix):
        base = base[: -len(suffix)]
    if len(base) >= 6:
        return f"{base[:-3]}/{base[-3:]}".upper()
    return base.upper()


def load_mt5():  # pragma: no cover - environment dependent
    """Import the Windows-only MetaTrader5 package, with a helpful error."""
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError as e:
        raise Mt5Error(
            "The 'MetaTrader5' package is required for Exness and only runs on "
            "Windows. Install it on a Windows PC/VPS with:  pip install MetaTrader5"
        ) from e
    return mt5


def connect(
    mt5,
    login: int,
    password: str,
    server: str,
    terminal_path: str | None = None,
    timeout_ms: int = 60_000,
):  # pragma: no cover - requires a live terminal
    """Initialise the MT5 terminal and log in to the Exness account."""
    kwargs: dict[str, Any] = {"login": int(login), "password": password, "server": server}
    if terminal_path:
        kwargs["path"] = terminal_path
    if not mt5.initialize(**kwargs):
        raise Mt5Error(f"MT5 initialize/login failed: {mt5.last_error()}")
    return mt5


# Timeframe name -> attribute on the mt5 module.
_TIMEFRAMES = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}


class ExnessMT5Feed(MarketDataFeed):
    """Streams completed MT5 candles for one symbol by polling ``copy_rates``."""

    def __init__(
        self,
        mt5,
        symbol: str,
        timeframe: str = "M1",
        suffix: str = "",
        poll_interval: float = 1.0,   # how often to check for a new closed bar
        warmup_bars: int = 200,
        max_bars: int | None = None,
    ) -> None:
        self.mt5 = mt5
        self.symbol = symbol
        self.mt5_symbol = to_mt5_symbol(symbol, suffix)
        self.timeframe = timeframe
        self.poll_interval = poll_interval
        self.warmup_bars = warmup_bars
        self.max_bars = max_bars

    def _tf_const(self) -> Any:
        attr = _TIMEFRAMES.get(self.timeframe.upper(), "TIMEFRAME_M1")
        return getattr(self.mt5, attr, 1)

    def _rates(self, count: int) -> list:
        # Ensure the symbol is in Market Watch, then pull the latest bars.
        select = getattr(self.mt5, "symbol_select", None)
        if select:
            select(self.mt5_symbol, True)
        rates = self.mt5.copy_rates_from_pos(self.mt5_symbol, self._tf_const(), 0, count)
        return list(rates) if rates is not None else []

    @staticmethod
    def _to_candle(symbol: str, row: Any) -> Candle:
        return Candle(
            symbol=symbol,
            timestamp=float(row["time"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["tick_volume"]) if "tick_volume" in _keys(row) else 0.0,
        )

    async def stream(self) -> AsyncIterator[Candle]:
        import asyncio

        emitted = 0
        # Warm up with recent history (all but the still-forming last bar).
        history = self._rates(self.warmup_bars)
        last_time = None
        for row in history[:-1]:
            yield self._to_candle(self.symbol, row)
            last_time = float(row["time"])
            emitted += 1
            if self.max_bars and emitted >= self.max_bars:
                return
        while True:
            await asyncio.sleep(self.poll_interval)
            rows = self._rates(3)
            # The last row is the in-progress bar; the one before it is complete.
            for row in rows[:-1]:
                t = float(row["time"])
                if last_time is not None and t <= last_time:
                    continue
                yield self._to_candle(self.symbol, row)
                last_time = t
                emitted += 1
                if self.max_bars and emitted >= self.max_bars:
                    return


class ExnessMT5Broker(Broker):
    """Places orders on an Exness (MT5) account. Live accounts are gated."""

    def __init__(
        self,
        mt5,
        symbol_suffix: str = "",
        units_per_lot: float = 100.0,   # XAUUSD: 1 lot = 100 oz
        deviation: int = 20,
        magic: int = 990099,
        confirm_live: bool = False,
        max_lot: float | None = None,        # hard cap on lots per order
        daily_max_loss: float | None = None,  # stop opening trades after this loss
        max_total_loss: float | None = None,  # LATCHING: hard stop for the account
        equity_floor: float | None = None,    # LATCHING: hard stop at this equity
        loss_anchor_equity: float | None = None,  # measure max_total_loss from here
        reconcile_interval: float = 10.0,     # seconds between position syncs
        on_halt=None,                          # callback(reason:str) when hard-stopped
    ) -> None:
        self.mt5 = mt5
        self.symbol_suffix = symbol_suffix
        self.units_per_lot = units_per_lot
        self.deviation = deviation
        self.magic = magic
        self.confirm_live = confirm_live
        self.max_lot = max_lot
        self.daily_max_loss = daily_max_loss
        self.max_total_loss = max_total_loss
        self.equity_floor = equity_floor
        self.reconcile_interval = reconcile_interval
        self.on_halt = on_halt

        self.positions: dict[str, Position] = {}
        self.realized_pnl = 0.0
        self.closed_trade_pnls: list[float] = []
        self._cash = 0.0
        self._equity = 0.0

        self.is_live = self._detect_live()
        self.blocked = self.is_live and not self.confirm_live
        self.refresh_account()

        # Daily loss kill-switch state (auto-resets at day rollover).
        self.halted_daily = False
        self._warned_daily = False
        self._day = time.strftime("%Y-%m-%d")
        self._day_anchor_equity = self._equity

        # LATCHING total-loss kill-switch. Once tripped it stays halted for the
        # life of the process; the launcher persists it across restarts via a
        # lock file, so it stops "until your command" to resume.
        # ``loss_anchor_equity`` lets the launcher persist the ORIGINAL starting
        # equity across crash-restarts — otherwise each restart would grant a
        # fresh loss budget (lose $150, crash, lose $200 more...).
        self.halted_total = False
        self._warned_total = False
        self._start_equity = (
            loss_anchor_equity if loss_anchor_equity is not None else self._equity
        )
        self._last_reconcile = 0.0

    def force_halt(self, reason: str = "manual") -> None:
        """Latch the hard stop on (e.g. a persisted lock file was found)."""
        self.halted_total = True

    def _check_total_loss(self) -> None:
        if self.halted_total:
            return
        reason = None
        if self.max_total_loss is not None:
            loss = self._start_equity - self._equity
            if loss >= self.max_total_loss:
                reason = f"total loss {loss:.2f} >= limit {self.max_total_loss:.2f}"
        if reason is None and self.equity_floor is not None:
            if self._equity <= self.equity_floor:
                reason = f"equity {self._equity:.2f} <= floor {self.equity_floor:.2f}"
        if reason is None:
            return
        self.halted_total = True
        self._flatten_all()
        if self.on_halt:
            try:
                self.on_halt(reason)
            except Exception:  # noqa: BLE001 - never let a callback break trading halt
                pass

    def _flatten_all(self) -> None:
        """Close every open position (best effort) when the hard stop trips."""
        get = getattr(self.mt5, "positions_get", None)
        if get is None:
            return
        positions = get() or []
        buy_type = getattr(self.mt5, "ORDER_TYPE_BUY", 0)
        sell_type = getattr(self.mt5, "ORDER_TYPE_SELL", 1)
        for p in positions:
            vol = float(getattr(p, "volume", 0.0) or 0.0)
            if vol <= 0:
                continue
            is_long = getattr(p, "type", buy_type) == buy_type
            request = {
                "action": getattr(self.mt5, "TRADE_ACTION_DEAL", 1),
                "symbol": getattr(p, "symbol", ""),
                "volume": vol,
                "type": sell_type if is_long else buy_type,
                "deviation": self.deviation,
                "magic": self.magic,
                "comment": "kill-switch flatten",
                "type_filling": getattr(self.mt5, "ORDER_FILLING_IOC", 1),
            }
            ticket = getattr(p, "ticket", None)
            if ticket is not None:
                request["position"] = ticket  # required to close on hedging accounts
            try:
                self.mt5.order_send(request)
            except Exception:  # noqa: BLE001 - close what we can
                pass

    def _update_daily_guard(self) -> None:
        """Trip the kill-switch if today's loss from the day's opening equity
        exceeds ``daily_max_loss``. Resets automatically at day rollover."""
        today = time.strftime("%Y-%m-%d")
        if today != self._day:
            self._day = today
            self._day_anchor_equity = self._equity
            self.halted_daily = False
            self._warned_daily = False
        if self.daily_max_loss is not None:
            loss = self._day_anchor_equity - self._equity
            if loss >= self.daily_max_loss:
                self.halted_daily = True

    # -- account type gate ------------------------------------------------
    def _detect_live(self) -> bool:
        info = self.mt5.account_info()
        if info is None:
            raise Mt5Error(f"account_info() failed: {self.mt5.last_error()}")
        real = getattr(self.mt5, "ACCOUNT_TRADE_MODE_REAL", 2)
        return getattr(info, "trade_mode", None) == real

    def refresh_account(self) -> None:
        info = self.mt5.account_info()
        if info is not None:
            self._cash = float(getattr(info, "balance", 0.0) or 0.0)
            self._equity = float(getattr(info, "equity", self._cash) or self._cash)

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def unrealized_pnl(self) -> float:
        return self._equity - self._cash

    @property
    def equity(self) -> float:
        return self._equity

    def open_position_count(self) -> int:
        return sum(1 for p in self.positions.values() if p.size != 0)

    def mark_to_market(self, symbol: str, price: float) -> None:
        # Positions/P&L are authoritative on the server. Refresh the account and
        # run the kill-switches on EVERY price update — a halt must trigger while
        # holding a loser, not only when the strategy next submits an order.
        self.refresh_account()
        now = time.time()
        if now - self._last_reconcile >= self.reconcile_interval:
            self._last_reconcile = now
            self.sync_positions()
        self._check_total_loss()
        self._update_daily_guard()

    def sync_positions(self) -> None:
        """Mirror the server's open positions into ``self.positions``.

        The server is the source of truth: positions can be closed out from
        under us (stop-loss/take-profit filled server-side, margin stop-out, a
        manual close in the MT5 app). Without this sync the execution agent
        would keep acting on stale ``current_units``.
        """
        get = getattr(self.mt5, "positions_get", None)
        if get is None:
            return
        server = get()
        if server is None:  # transient terminal error — keep the last mirror
            return
        fresh: dict[str, Position] = {}
        buy_type = getattr(self.mt5, "ORDER_TYPE_BUY", 0)
        for p in server:
            raw = getattr(p, "symbol", "")
            vol = float(getattr(p, "volume", 0.0) or 0.0)
            if not raw or vol <= 0:
                continue
            sym = from_mt5_symbol(raw, self.symbol_suffix)
            info = getattr(self.mt5, "symbol_info", lambda *_: None)(raw)
            contract = self.units_per_lot
            if info is not None:
                contract = float(
                    getattr(info, "trade_contract_size", contract) or contract
                )
            signed = vol * contract * (1 if getattr(p, "type", buy_type) == buy_type else -1)
            open_price = float(getattr(p, "price_open", 0.0) or 0.0)
            pos = fresh.setdefault(sym, Position(sym))
            prev = pos.size
            total = prev + signed
            if total != 0:
                pos.avg_price = (
                    pos.avg_price * abs(prev) + open_price * abs(signed)
                ) / (abs(prev) + abs(signed))
            pos.size = total
        self.positions = fresh

    # -- sizing -----------------------------------------------------------
    def _units_to_lots(self, symbol_mt5: str, units: float) -> float:
        vol_min, vol_max, vol_step, contract = 0.01, 100.0, 0.01, self.units_per_lot
        info = getattr(self.mt5, "symbol_info", lambda *_: None)(symbol_mt5)
        if info is not None:
            vol_min = float(getattr(info, "volume_min", vol_min) or vol_min)
            vol_max = float(getattr(info, "volume_max", vol_max) or vol_max)
            vol_step = float(getattr(info, "volume_step", vol_step) or vol_step)
            contract = float(getattr(info, "trade_contract_size", contract) or contract)
        lots = units / contract if contract else 0.0
        if self.max_lot is not None:
            lots = min(lots, self.max_lot)
        if vol_step > 0:
            lots = math.floor(lots / vol_step) * vol_step
        # VETO instead of rounding up: if the correctly-sized position is below
        # the venue minimum, taking vol_min anyway would multiply the intended
        # risk (e.g. 10x on a small account). Better to skip the trade.
        if lots < vol_min:
            return 0.0
        return round(min(vol_max, lots), 2)

    def _filling_mode(self, symbol_mt5: str) -> int:
        """Pick an order filling mode the venue actually allows.

        MT5 symbols advertise allowed modes as a bitmask (1=FOK, 2=IOC); using a
        disallowed mode gets orders rejected with TRADE_RETCODE_INVALID_FILL.
        Prefer IOC, fall back to FOK, then RETURN.
        """
        ioc = getattr(self.mt5, "ORDER_FILLING_IOC", 1)
        fok = getattr(self.mt5, "ORDER_FILLING_FOK", 0)
        ret = getattr(self.mt5, "ORDER_FILLING_RETURN", 2)
        info = getattr(self.mt5, "symbol_info", lambda *_: None)(symbol_mt5)
        mask = getattr(info, "filling_mode", None) if info is not None else None
        if mask is None:
            return ioc
        if mask & 2:
            return ioc
        if mask & 1:
            return fok
        return ret

    # -- orders -----------------------------------------------------------
    def submit(self, order: Order, mark_price: float) -> Fill | None:
        if order.size <= 0 or order.side is Side.FLAT:
            return None
        if self.blocked:
            raise Mt5Error(
                "REAL Exness account detected and confirm_live is False — refusing "
                "to trade. Set confirm_live=True only after your own review."
            )
        # Kill-switches. Refresh account, then evaluate both guards.
        self.refresh_account()
        self._check_total_loss()
        self._update_daily_guard()
        # LATCHING hard stop: closes positions once, then blocks ALL trades until
        # the process is restarted with the lock cleared (your command to resume).
        if self.halted_total:
            if not self._warned_total:
                print(
                    f"[risk] HARD STOP: account down >= {self.max_total_loss}. "
                    "Positions flattened; trading halted until you restart."
                )
                self._warned_total = True
            return None
        # Daily loss kill-switch: once tripped, stop opening/adjusting positions.
        if self.halted_daily:
            if not self._warned_daily:
                print(
                    f"[risk] DAILY LOSS LIMIT hit "
                    f"(-{self.daily_max_loss}); halting new trades until tomorrow."
                )
                self._warned_daily = True
            return None
        sym = to_mt5_symbol(order.symbol, self.symbol_suffix)
        lots = self._units_to_lots(sym, order.size)
        if lots <= 0:
            # Correctly-sized position is below the venue minimum — skip rather
            # than force a bigger position than the risk model asked for.
            return None

        buy_type = getattr(self.mt5, "ORDER_TYPE_BUY", 0)
        sell_type = getattr(self.mt5, "ORDER_TYPE_SELL", 1)
        request = {
            "action": getattr(self.mt5, "TRADE_ACTION_DEAL", 1),
            "symbol": sym,
            "volume": lots,
            "type": buy_type if order.side is Side.BUY else sell_type,
            "price": mark_price,
            "deviation": self.deviation,
            "magic": self.magic,
            "comment": (order.reason or "babayaga")[:31],
            "type_time": getattr(self.mt5, "ORDER_TIME_GTC", 0),
            "type_filling": self._filling_mode(sym),
        }
        if order.stop_loss is not None:
            request["sl"] = float(order.stop_loss)
        if order.take_profit is not None:
            request["tp"] = float(order.take_profit)

        result = self.mt5.order_send(request)
        done = getattr(self.mt5, "TRADE_RETCODE_DONE", 10009)
        if result is None or getattr(result, "retcode", None) != done:
            # Rejected / requote / not filled — surface nothing, let OS continue.
            return None

        fill_price = float(getattr(result, "price", mark_price) or mark_price)
        filled_lots = float(getattr(result, "volume", lots) or lots)
        # Convert lots back to units with the SYMBOL's contract size (an FX lot
        # is 100,000 units, a gold lot is 100 oz) — not a one-size scalar.
        contract = self.units_per_lot
        info = getattr(self.mt5, "symbol_info", lambda *_: None)(sym)
        if info is not None:
            contract = float(getattr(info, "trade_contract_size", contract) or contract)
        filled_units = filled_lots * contract * order.side.sign
        self._apply_fill(order.symbol, filled_units, fill_price)
        self.refresh_account()
        return Fill(
            symbol=order.symbol,
            side=order.side,
            size=abs(filled_units),
            price=fill_price,
            order_reason=order.reason,
            timestamp=order.timestamp,
        )

    def _apply_fill(self, symbol: str, signed_units: float, price: float) -> None:
        pos = self.positions.setdefault(symbol, Position(symbol))
        prev = pos.size
        new = prev + signed_units
        if prev != 0 and (prev > 0) != (signed_units > 0):
            closing = min(abs(signed_units), abs(prev))
            direction = 1 if prev > 0 else -1
            self.closed_trade_pnls.append((price - pos.avg_price) * closing * direction)
        if new == 0:
            pos.avg_price = 0.0
        elif prev == 0 or (prev > 0) == (signed_units > 0):
            pos.avg_price = (pos.avg_price * abs(prev) + price * abs(signed_units)) / abs(new)
        pos.size = new


def _keys(row: Any) -> Any:
    """Field names for a numpy record row or a dict."""
    if hasattr(row, "dtype") and row.dtype.names:  # numpy void
        return row.dtype.names
    if isinstance(row, dict):
        return row.keys()
    return ()
