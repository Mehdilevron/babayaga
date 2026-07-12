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

# Typical starting price and spread (in price units) for common instruments, so
# the simulated feed and paper broker produce realistic numbers per instrument
# instead of always looking like EUR/USD. Used only when the caller doesn't set
# an explicit value.
_TYPICAL: dict[str, tuple[float, float]] = {
    "EUR/USD": (1.1000, 0.00008),
    "GBP/USD": (1.2700, 0.00012),
    "USD/JPY": (150.00, 0.010),
    "AUD/USD": (0.6600, 0.00012),
    "USD/CHF": (0.8800, 0.00012),
    "USD/CAD": (1.3600, 0.00012),
    "XAU/USD": (2000.0, 0.30),      # gold
    "XAG/USD": (24.00, 0.020),      # silver
    "BTC/USD": (60000.0, 5.0),
    "ETH/USD": (3000.0, 1.0),
}


def typical_price(symbol: str) -> float:
    return _TYPICAL.get(symbol.upper(), (1.1000, 0.00008))[0]


def typical_spread(symbol: str) -> float:
    return _TYPICAL.get(symbol.upper(), (1.1000, 0.00008))[1]


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


# A real OANDA feed lives in ``babayaga.integration.oanda`` (imported lazily to
# avoid a circular import, since that module imports from this one).
