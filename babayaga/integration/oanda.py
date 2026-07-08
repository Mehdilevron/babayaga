"""Real OANDA v3 adapter — market data + broker — over the standard library.

This is a *working* integration (not a stub) against OANDA's REST v3 API, built
on ``urllib`` so it needs no third-party packages. It defaults to OANDA's
**practice** environment (``api-fxpractice.oanda.com``): a free demo account with
virtual money. Nothing here can touch real funds unless you deliberately
construct it with ``practice=False`` *and* ``confirm_live=True``.

Usage (with a free OANDA practice account):

    export OANDA_API_TOKEN=...        # from your practice account
    export OANDA_ACCOUNT_ID=101-...

    from babayaga import Config, TradingOS
    from babayaga.integration.oanda import OandaClient, OandaFeed, OandaBroker

    client = OandaClient.from_env()
    os_ = TradingOS(Config(symbols=("EUR/USD",), sim_steps=0))
    os_.broker = OandaBroker(client, account_id=client.account_id)   # demo broker
    os_.execution.broker = os_.broker
    os_.attach_feed("EUR/USD", OandaFeed(client, "EUR/USD", granularity="M1"))
    import asyncio; asyncio.run(os_.run())

The classes accept an injected transport (any object with ``request(...)``), so
the parsing logic is fully unit-tested offline without hitting the network.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from collections.abc import AsyncIterator
from typing import Any

from babayaga.integration.broker import Broker, Position
from babayaga.integration.market_data import MarketDataFeed
from babayaga.kernel.events import Candle, Fill, Order, Side

PRACTICE_HOST = "https://api-fxpractice.oanda.com"
LIVE_HOST = "https://api-fxtrade.oanda.com"


class OandaError(RuntimeError):
    pass


def to_oanda_symbol(symbol: str) -> str:
    """``EUR/USD`` -> ``EUR_USD`` (OANDA's instrument format)."""
    return symbol.replace("/", "_").upper()


def from_oanda_symbol(instrument: str) -> str:
    return instrument.replace("_", "/").upper()


class OandaClient:
    """Thin authenticated HTTP client for the OANDA v3 REST API."""

    def __init__(
        self,
        token: str,
        account_id: str,
        practice: bool = True,
        timeout: float = 10.0,
    ) -> None:
        if not token or not account_id:
            raise OandaError("OANDA token and account_id are required")
        self.token = token
        self.account_id = account_id
        self.practice = practice
        self.timeout = timeout
        self.base = PRACTICE_HOST if practice else LIVE_HOST

    @classmethod
    def from_env(cls, practice: bool = True) -> "OandaClient":
        return cls(
            token=os.environ.get("OANDA_API_TOKEN", ""),
            account_id=os.environ.get("OANDA_ACCOUNT_ID", ""),
            practice=practice,
        )

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{self.base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                return json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as e:  # pragma: no cover - network path
            detail = e.read().decode(errors="replace")
            raise OandaError(f"OANDA {method} {path} -> HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:  # pragma: no cover - network path
            raise OandaError(f"OANDA request failed: {e.reason}") from e


class OandaFeed(MarketDataFeed):
    """Streams completed candles by polling OANDA's candles endpoint."""

    def __init__(
        self,
        client: OandaClient,
        symbol: str,
        granularity: str = "M1",
        poll_interval: float = 5.0,
        max_bars: int | None = None,
        price: str = "M",  # M=mid, B=bid, A=ask
    ) -> None:
        self.client = client
        self.symbol = symbol
        self.instrument = to_oanda_symbol(symbol)
        self.granularity = granularity
        self.poll_interval = poll_interval
        self.max_bars = max_bars
        self.price = price

    def _fetch(self, count: int = 2, from_time: str | None = None) -> list[dict]:
        path = (
            f"/v3/instruments/{self.instrument}/candles"
            f"?granularity={self.granularity}&price={self.price}&count={count}"
        )
        if from_time:
            path = (
                f"/v3/instruments/{self.instrument}/candles"
                f"?granularity={self.granularity}&price={self.price}&from={from_time}"
            )
        return self.client.request("GET", path).get("candles", [])

    def _to_candle(self, raw: dict) -> Candle:
        ohlc = raw.get("mid") or raw.get("bid") or raw.get("ask") or {}
        # OANDA timestamps are RFC3339; keep the epoch seconds for ordering.
        ts = _rfc3339_to_epoch(raw.get("time", "0"))
        return Candle(
            symbol=self.symbol,
            timestamp=ts,
            open=float(ohlc.get("o", 0.0)),
            high=float(ohlc.get("h", 0.0)),
            low=float(ohlc.get("l", 0.0)),
            close=float(ohlc.get("c", 0.0)),
            volume=float(raw.get("volume", 0.0)),
        )

    async def stream(self) -> AsyncIterator[Candle]:
        emitted = 0
        last_time: str | None = None
        # Seed with recent history so agents warm up quickly.
        for raw in self._fetch(count=200):
            if raw.get("complete"):
                yield self._to_candle(raw)
                last_time = raw.get("time")
                emitted += 1
                if self.max_bars and emitted >= self.max_bars:
                    return
        while True:
            await asyncio.sleep(self.poll_interval)
            for raw in self._fetch(from_time=last_time):
                if not raw.get("complete") or raw.get("time") == last_time:
                    continue
                yield self._to_candle(raw)
                last_time = raw.get("time")
                emitted += 1
                if self.max_bars and emitted >= self.max_bars:
                    return


class OandaBroker(Broker):
    """Places orders on an OANDA account (practice by default).

    Maintains a local mirror of positions/P&L updated from fill transactions,
    and refreshes cash/equity from the account summary. It matches the same
    interface the OS uses for :class:`~babayaga.integration.broker.PaperBroker`.
    """

    def __init__(
        self,
        client: OandaClient,
        account_id: str | None = None,
        confirm_live: bool = False,
    ) -> None:
        if not client.practice and not confirm_live:
            raise OandaError(
                "Refusing to build a LIVE OANDA broker. This trades real money. "
                "Pass confirm_live=True only after your own risk/compliance review."
            )
        self.client = client
        self.account_id = account_id or client.account_id
        self.positions: dict[str, Position] = {}
        self.realized_pnl = 0.0
        self.closed_trade_pnls: list[float] = []
        self._cash = 0.0
        self._unrealized = 0.0
        self.refresh_account()

    # -- account ----------------------------------------------------------
    def refresh_account(self) -> None:
        summary = self.client.request(
            "GET", f"/v3/accounts/{self.account_id}/summary"
        ).get("account", {})
        if "balance" in summary:
            self._cash = float(summary["balance"])
        self._unrealized = float(summary.get("unrealizedPL", 0.0) or 0.0)

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def unrealized_pnl(self) -> float:
        return self._unrealized

    @property
    def equity(self) -> float:
        return self._cash + self._unrealized

    def open_position_count(self) -> int:
        return sum(1 for p in self.positions.values() if p.size != 0)

    def mark_to_market(self, symbol: str, price: float) -> None:
        # Positions and P&L are authoritative on OANDA's side; nothing local to do.
        # Callers may periodically call refresh_account() to update equity.
        pass

    # -- orders -----------------------------------------------------------
    def submit(self, order: Order, mark_price: float) -> Fill | None:
        if order.size <= 0 or order.side is Side.FLAT:
            return None
        units = int(round(order.size)) * order.side.sign
        payload: dict[str, Any] = {
            "order": {
                "type": "MARKET",
                "instrument": to_oanda_symbol(order.symbol),
                "units": str(units),
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
            }
        }
        # Attach protective exits if provided.
        if order.stop_loss is not None:
            payload["order"]["stopLossOnFill"] = {"price": f"{order.stop_loss:.5f}"}
        if order.take_profit is not None:
            payload["order"]["takeProfitOnFill"] = {"price": f"{order.take_profit:.5f}"}

        resp = self.client.request(
            "POST", f"/v3/accounts/{self.account_id}/orders", payload
        )
        txn = resp.get("orderFillTransaction")
        if not txn:
            # Order was cancelled/rejected (e.g. FOK unfilled); surface nothing.
            return None
        fill_price = float(txn.get("price", mark_price))
        filled_units = float(txn.get("units", units))
        self._apply_fill(order.symbol, filled_units, fill_price, txn)
        return Fill(
            symbol=order.symbol,
            side=order.side,
            size=abs(filled_units),
            price=fill_price,
            order_reason=order.reason,
            timestamp=order.timestamp,
        )

    def _apply_fill(self, symbol: str, signed_units: float, price: float, txn: dict) -> None:
        pos = self.positions.setdefault(symbol, Position(symbol))
        prev = pos.size
        new = prev + signed_units
        if prev != 0 and (prev > 0) != (signed_units > 0):
            closing = min(abs(signed_units), abs(prev))
            direction = 1 if prev > 0 else -1
            pnl = (price - pos.avg_price) * closing * direction
            self.realized_pnl += pnl
            self.closed_trade_pnls.append(pnl)
        if new == 0:
            pos.avg_price = 0.0
        elif prev == 0 or (prev > 0) == (signed_units > 0):
            total = pos.avg_price * abs(prev) + price * abs(signed_units)
            pos.avg_price = total / abs(new)
        pos.size = new
        # Prefer OANDA's authoritative realised P&L when present.
        if "pl" in txn:
            try:
                self.realized_pnl += float(txn["pl"])
            except (TypeError, ValueError):
                pass


def _rfc3339_to_epoch(ts: str) -> float:
    """Best-effort RFC3339 -> epoch seconds without external deps."""
    if not ts or ts == "0":
        return 0.0
    from datetime import datetime, timezone

    cleaned = ts.replace("Z", "+00:00")
    # OANDA returns nanosecond precision; trim to microseconds for fromisoformat.
    if "." in cleaned:
        head, frac = cleaned.split(".", 1)
        tz = ""
        for marker in ("+", "-"):
            if marker in frac:
                frac, tz = frac.split(marker, 1)
                tz = marker + tz
                break
        frac = frac[:6]
        cleaned = f"{head}.{frac}{tz}"
    try:
        return datetime.fromisoformat(cleaned).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:  # pragma: no cover - defensive
        return 0.0
