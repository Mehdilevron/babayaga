"""MetaTrader 5 price feed for the cross-market hedge leg (e.g. XAUUSD).

Requires the optional `MetaTrader5` dependency (`pip install babayaga[mt5]`)
AND a running, logged-in MT5 terminal on the SAME machine - the package
talks to your local terminal process over IPC, it does not connect to a
broker over the network by itself. This cannot run inside a plain Linux
container with no terminal installed; run this part on Windows (or under
Wine) where your MT5 terminal lives.

XAUUSD (unlike the 24/7 on-chain leg it's paired against) follows the forex
market calendar - closed weekends, and with a daily rollover gap most
brokers observe even on weekdays. MT5's API has no clean "is the market
open" boolean, so get_quote uses two practical proxies instead: the
symbol's trade_mode (most brokers flip this to disabled outside trading
hours for that instrument) and tick staleness (if neither the broker nor
MT5 itself say the market's shut, a tick that hasn't moved in a while is
itself a sign trading on it right now would be against a stale price).
Either one raises, and the engine treats that exactly like any other failed
quote: skip this pair for the tick, don't trade.
"""

from __future__ import annotations

import time
from typing import Optional

from babayaga.core.models import Quote

DEFAULT_STALE_AFTER_S = 120.0


class Mt5Session:
    """Thin wrapper around the MetaTrader5 module's global connection state.

    The MetaTrader5 package is not object-oriented - `initialize()` opens
    one connection for the whole process. This wrapper just centralizes
    connect/shutdown so the feed and executor share a single session.
    """

    def __init__(self, login: int, password: str, server: str, terminal_path: Optional[str] = None):
        self.login = login
        self.password = password
        self.server = server
        self.terminal_path = terminal_path
        self._connected = False

    def connect(self) -> None:
        import MetaTrader5 as mt5  # lazy import: optional, Windows-only dependency

        kwargs = {"login": self.login, "password": self.password, "server": self.server}
        if self.terminal_path:
            kwargs["path"] = self.terminal_path
        if not mt5.initialize(**kwargs):
            code, desc = mt5.last_error()
            raise RuntimeError(f"MT5 initialize() failed: [{code}] {desc}")
        self._connected = True

    def ensure_connected(self) -> None:
        if not self._connected:
            self.connect()

    def shutdown(self) -> None:
        if self._connected:
            import MetaTrader5 as mt5

            mt5.shutdown()
            self._connected = False


class Mt5Feed:
    def __init__(
        self,
        venue: str,
        fee_bps: float,
        session: Mt5Session,
        stale_after_s: float = DEFAULT_STALE_AFTER_S,
    ):
        self.venue = venue
        self.fee_bps = fee_bps
        self.session = session
        self.stale_after_s = stale_after_s

    async def get_quote(self, base: str, quote: str, size_base: float, symbol: str) -> Quote:
        import MetaTrader5 as mt5

        self.session.ensure_connected()
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"MT5 symbol_select({symbol}) failed: {mt5.last_error()}")

        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            raise RuntimeError(f"MT5 symbol_info({symbol}) returned None: {mt5.last_error()}")
        if symbol_info.trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
            raise RuntimeError(f"MT5 {symbol}: trading disabled for this symbol (market likely closed)")

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"MT5 symbol_info_tick({symbol}) returned None: {mt5.last_error()}")

        age_s = time.time() - tick.time
        if age_s > self.stale_after_s:
            raise RuntimeError(
                f"MT5 {symbol}: last tick is {age_s:.0f}s old (> {self.stale_after_s:.0f}s) - "
                "market likely closed, refusing to quote against a stale price"
            )

        return Quote(venue=self.venue, base=base, quote=quote, bid=tick.bid, ask=tick.ask, fee_bps=self.fee_bps)
