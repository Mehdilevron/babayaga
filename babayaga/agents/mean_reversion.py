"""Mean-reversion agent — fades extremes instead of chasing trends.

The opposite philosophy to :class:`~babayaga.agents.technical.TechnicalAgent`:
when price stretches far from its moving average (a high Bollinger z-score) it
bets on a snap back — buy when oversold, sell when overbought. Trend-following
and mean-reversion are the two classic edges; currencies tend to mean-revert
more than trending equities, so this is worth testing on FX.

Like every specialist it is pure and stateless: ``evaluate`` reads the window
and returns a :class:`Signal`. It shares no parameters with the trend agent, so
the two can be A/B compared cleanly.
"""

from __future__ import annotations

from collections.abc import Sequence

from babayaga.agents.base import SpecialistAgent
from babayaga.analytics import indicators as ind
from babayaga.kernel.events import Candle, Side, Signal


class MeanReversionAgent(SpecialistAgent):
    name = "mean_reversion"

    def __init__(self, period: int = 20, entry_z: float = 1.5, weight: float = 1.0) -> None:
        self.period = period
        self.entry_z = entry_z
        self.weight = weight

    def evaluate(self, symbol: str, history: Sequence[Candle]) -> Signal | None:
        closes = self.closes(history)
        if len(closes) < self.period + 1:
            return None
        bands = ind.bollinger(closes, self.period)
        if bands is None:
            return None
        lower, mid, upper = bands
        std = (upper - mid) / 2.0  # bollinger uses 2 std by default
        if std <= 0:
            return None
        price = closes[-1]
        z = (price - mid) / std  # standard deviations from the mean

        # Fade the move: above the mean -> sell, below -> buy. Scaled so a z of
        # entry_z gives ~full conviction.
        score = max(-1.0, min(1.0, -z / self.entry_z))
        side = Side.BUY if score > 0.1 else Side.SELL if score < -0.1 else Side.FLAT
        return Signal(
            agent=self.name,
            symbol=symbol,
            side=side,
            confidence=min(1.0, abs(score)),
            rationale=f"z-score {z:+.2f} vs {self.period}-SMA ({'oversold' if z < 0 else 'overbought'})",
            features={"zscore": round(z, 3)},
        )
