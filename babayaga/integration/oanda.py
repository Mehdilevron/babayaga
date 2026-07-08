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
import math
import os
import queue
import threading
import urllib.error
import urllib.request
from collections.abc import AsyncIterator, Iterator
from typing import Any

from babayaga.integration.broker import Broker, Position
from babayaga.integration.market_data import MarketDataFeed
from babayaga.kernel.events import Candle, Fill, Order, Side

PRACTICE_HOST = "https://api-fxpractice.oanda.com"
LIVE_HOST = "https://api-fxtrade.oanda.com"
PRACTICE_STREAM_HOST = "https://stream-fxpractice.oanda.com"
LIVE_STREAM_HOST = "https://stream-fxtrade.oanda.com"


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
        self.stream_base = PRACTICE_STREAM_HOST if practice else LIVE_STREAM_HOST

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

    def stream_prices(self, instruments: str) -> Iterator[dict]:
        """Yield newline-delimited JSON objects from OANDA's pricing stream.

        This is a *blocking* generator (one HTTP connection held open). The
        async :class:`OandaStreamFeed` runs it on a background thread. Yields
        both ``PRICE`` and ``HEARTBEAT`` messages so callers can keep-alive.
        """
        path = f"/v3/accounts/{self.account_id}/pricing/stream?instruments={instruments}"
        url = f"{self.stream_base}{path}"
        req = urllib.request.Request(url, method="GET")
        req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req) as resp:  # noqa: S310  # pragma: no cover - network
                for raw in resp:
                    line = raw.decode(errors="replace").strip()
                    if line:
                        yield json.loads(line)
        except urllib.error.HTTPError as e:  # pragma: no cover - network path
            detail = e.read().decode(errors="replace")
            raise OandaError(f"OANDA stream -> HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:  # pragma: no cover - network path
            raise OandaError(f"OANDA stream failed: {e.reason}") from e


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


class _BarAggregator:
    """Aggregates streamed price ticks into fixed-duration OHLC candles."""

    def __init__(self, symbol: str, bar_seconds: int) -> None:
        self.symbol = symbol
        self.bar_seconds = bar_seconds
        self.bar_start: float | None = None
        self._o = self._h = self._l = self._c = 0.0
        self._ticks = 0

    def _boundary(self, ts: float) -> float:
        return math.floor(ts / self.bar_seconds) * self.bar_seconds

    def add(self, ts: float, price: float) -> Candle | None:
        """Add a tick; return a completed :class:`Candle` when the bar rolls over."""
        b = self._boundary(ts)
        completed: Candle | None = None
        if self.bar_start is None:
            self.bar_start = b
        elif b > self.bar_start:
            completed = self.snapshot()
            self.bar_start = b
            self._ticks = 0
        if self._ticks == 0:
            self._o = self._h = self._l = self._c = price
        else:
            self._h = max(self._h, price)
            self._l = min(self._l, price)
            self._c = price
        self._ticks += 1
        return completed

    def snapshot(self) -> Candle | None:
        if self._ticks == 0 or self.bar_start is None:
            return None
        return Candle(
            symbol=self.symbol,
            timestamp=self.bar_start,
            open=self._o,
            high=self._h,
            low=self._l,
            close=self._c,
            volume=float(self._ticks),
        )


class OandaStreamFeed(MarketDataFeed):
    """Real-time feed off OANDA's pricing *stream* (not polling).

    Holds a streaming HTTP connection open on a background thread and
    aggregates incoming bid/ask ticks into ``bar_seconds`` OHLC candles. A
    completed candle is emitted as soon as the first tick of the next bar
    arrives; the final partial bar is flushed when the stream ends.
    """

    def __init__(
        self,
        client: OandaClient,
        symbol: str,
        bar_seconds: int = 60,
        max_bars: int | None = None,
    ) -> None:
        self.client = client
        self.symbol = symbol
        self.instrument = to_oanda_symbol(symbol)
        self.bar_seconds = bar_seconds
        self.max_bars = max_bars

    @staticmethod
    def _mid(msg: dict) -> float | None:
        bids = msg.get("bids") or []
        asks = msg.get("asks") or []
        if bids and asks:
            return (float(bids[0]["price"]) + float(asks[0]["price"])) / 2.0
        if bids:
            return float(bids[0]["price"])
        if asks:
            return float(asks[0]["price"])
        return None

    async def stream(self) -> AsyncIterator[Candle]:
        loop = asyncio.get_event_loop()
        q: queue.Queue = queue.Queue()
        sentinel = object()

        def producer() -> None:
            try:
                for msg in self.client.stream_prices(self.instrument):
                    q.put(msg)
            except Exception as exc:  # noqa: BLE001 - surface to the consumer
                q.put(exc)
            finally:
                q.put(sentinel)

        threading.Thread(target=producer, daemon=True).start()
        agg = _BarAggregator(self.symbol, self.bar_seconds)
        emitted = 0
        while True:
            msg = await loop.run_in_executor(None, q.get)
            if msg is sentinel:
                final = agg.snapshot()
                if final is not None:
                    yield final
                return
            if isinstance(msg, Exception):
                raise msg
            if msg.get("type") != "PRICE":
                continue  # skip heartbeats
            price = self._mid(msg)
            if price is None:
                continue
            ts = _rfc3339_to_epoch(msg.get("time", "0"))
            candle = agg.add(ts, price)
            if candle is not None:
                yield candle
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
