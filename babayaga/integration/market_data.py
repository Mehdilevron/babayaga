"""Market-data adapters.

An adapter is an async generator of :class:`Candle` objects. Ships with a
deterministic simulated feed (a regime-switching geometric random walk) so the
whole OS runs with no network or credentials. A ``ReplayFeed`` lets you drive
the OS from recorded/CSV history, and ``OandaFeed`` is a documented stub showing
exactly where a real streaming feed would plug in.
"""

from __future__ import annotations

import asyncio
import math
import random
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterable, Sequence

from babayaga.kernel.events import Candle


class MarketDataFeed(ABC):
    """Base class for all market-data sources."""

    @abstractmethod
    def stream(self) -> AsyncIterator[Candle]:
        """Yield candles until the feed is exhausted or cancelled."""
        raise NotImplementedError


class SimulatedFeed(MarketDataFeed):
    """A regime-switching random-walk price generator for one instrument.

    The generator alternates between trending and mean-reverting regimes so the
    agents see a realistic mix of conditions. Fully deterministic for a given
    ``seed``, which makes tests and demos reproducible.
    """

    def __init__(
        self,
        symbol: str = "EUR/USD",
        start_price: float = 1.1000,
        steps: int = 500,
        seed: int | None = 7,
        annualized_vol: float = 0.08,
        interval: float = 0.0,
    ) -> None:
        self.symbol = symbol
        self.start_price = start_price
        self.steps = steps
        self.interval = interval
        self._rng = random.Random(seed)
        # Per-bar volatility from an annualised figure (~252*24 hourly bars).
        self._sigma = annualized_vol / math.sqrt(252 * 24)

    async def stream(self) -> AsyncIterator[Candle]:
        price = self.start_price
        drift = 0.0
        regime_len = 0
        ts = time.time()
        for _ in range(self.steps):
            if regime_len <= 0:
                # Switch regime: pick a fresh drift and duration.
                drift = self._rng.uniform(-1.0, 1.0) * self._sigma * 0.5
                regime_len = self._rng.randint(15, 60)
            regime_len -= 1

            shock = self._rng.gauss(0.0, 1.0) * self._sigma
            ret = drift + shock
            open_ = price
            close = price * (1.0 + ret)
            high = max(open_, close) * (1.0 + abs(self._rng.gauss(0, self._sigma / 2)))
            low = min(open_, close) * (1.0 - abs(self._rng.gauss(0, self._sigma / 2)))
            volume = self._rng.uniform(500, 1500)
            price = close
            ts += 3600.0
            yield Candle(self.symbol, ts, open_, high, low, close, volume)
            if self.interval:
                await asyncio.sleep(self.interval)


class ReplayFeed(MarketDataFeed):
    """Replays a fixed sequence of candles (e.g. loaded from CSV history)."""

    def __init__(self, candles: Sequence[Candle], interval: float = 0.0) -> None:
        self._candles = list(candles)
        self.interval = interval

    @classmethod
    def from_rows(
        cls,
        symbol: str,
        rows: Iterable[Sequence[float]],
        interval: float = 0.0,
    ) -> "ReplayFeed":
        """Build from ``(ts, open, high, low, close[, volume])`` rows."""
        candles = []
        for r in rows:
            ts, o, h, l, c = r[0], r[1], r[2], r[3], r[4]
            v = r[5] if len(r) > 5 else 0.0
            candles.append(Candle(symbol, ts, o, h, l, c, v))
        return cls(candles, interval=interval)

    async def stream(self) -> AsyncIterator[Candle]:
        for c in self._candles:
            yield c
            if self.interval:
                await asyncio.sleep(self.interval)


class OandaFeed(MarketDataFeed):
    """Stub for OANDA's streaming pricing endpoint.

    Left intentionally unimplemented so the OS never opens a network connection
    by accident. To go live, implement :meth:`stream` against
    ``/v3/accounts/{id}/pricing/stream`` and yield :class:`Candle` objects. The
    rest of the OS needs no changes — it only depends on ``MarketDataFeed``.
    """

    def __init__(self, symbol: str, account_id: str, token: str, practice: bool = True):
        self.symbol = symbol
        self.account_id = account_id
        self.token = token
        self.practice = practice

    async def stream(self) -> AsyncIterator[Candle]:  # pragma: no cover - stub
        raise NotImplementedError(
            "OandaFeed is a live-trading stub. Implement the streaming request "
            "against the OANDA v3 pricing API and supply valid credentials."
        )
        yield  # pragma: no cover - makes this an async generator
