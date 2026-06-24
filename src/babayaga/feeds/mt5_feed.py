"""MetaTrader 5 price feed for the cross-market hedge leg (e.g. XAUUSD).

Requires the optional `MetaTrader5` dependency (`pip install babayaga[mt5]`)
AND a running, logged-in MT5 terminal on the SAME machine - the package
talks to your local terminal process over IPC, it does not connect to a
broker over the network by itself. This cannot run inside a plain Linux
container with no terminal installed; run this part on Windows (or under
Wine) where your MT5 terminal lives.
"""

from __future__ import annotations

from typing import Optional

from babayaga.core.models import Quote


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
    def __init__(self, venue: str, fee_bps: float, session: Mt5Session):
        self.venue = venue
        self.fee_bps = fee_bps
        self.session = session

    async def get_quote(self, base: str, quote: str, size_base: float, symbol: str) -> Quote:
        import MetaTrader5 as mt5

        self.session.ensure_connected()
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"MT5 symbol_select({symbol}) failed: {mt5.last_error()}")

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"MT5 symbol_info_tick({symbol}) returned None: {mt5.last_error()}")

        return Quote(venue=self.venue, base=base, quote=quote, bid=tick.bid, ask=tick.ask, fee_bps=self.fee_bps)
