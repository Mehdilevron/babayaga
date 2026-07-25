"""Technical-analysis agent.

Combines several classic indicators into a single directional score in
[-1, +1]. Each indicator contributes a sub-vote; the blended score becomes the
signal's side and confidence. The rationale string records what drove the call
so decisions are auditable.
"""

from __future__ import annotations

from collections.abc import Sequence

from babayaga.agents.base import SpecialistAgent
from babayaga.analytics import indicators as ind
from babayaga.kernel.events import Candle, Side, Signal


class TechnicalAgent(SpecialistAgent):
    name = "technical"

    def __init__(
        self,
        fast: int = 12,
        slow: int = 26,
        rsi_period: int = 14,
        weight: float = 1.0,
    ) -> None:
        self.fast = fast
        self.slow = slow
        self.rsi_period = rsi_period
        self.weight = weight

    def evaluate(self, symbol: str, history: Sequence[Candle]) -> Signal | None:
        closes = self.closes(history)
        if len(closes) < self.slow + 5:
            return None

        votes: list[float] = []
        reasons: list[str] = []

        # Trend + MACD in a single pass (fast/slow EMA series computed once and
        # shared) instead of ema()+ema()+macd() recomputing them 5 times total.
        tm = ind.trend_and_macd(closes, self.fast, self.slow)

        # 1) Trend: fast vs slow EMA.
        if tm is not None:
            fast_e, slow_e, _, _, hist = tm
            if slow_e != 0:
                spread = (fast_e - slow_e) / slow_e
                trend_vote = max(-1.0, min(1.0, spread * 400))  # scale bp-ish spread
                votes.append(trend_vote)
                reasons.append(f"EMA{self.fast}/{self.slow} {'bull' if trend_vote > 0 else 'bear'} ({spread*100:+.2f}%)")

        # 2) Momentum: RSI distance from 50.
        rsi_val = ind.rsi(closes, self.rsi_period)
        if rsi_val is not None:
            rsi_vote = max(-1.0, min(1.0, (rsi_val - 50.0) / 30.0))
            votes.append(rsi_vote)
            reasons.append(f"RSI {rsi_val:.0f}")

        # 3) MACD histogram sign & magnitude (from the same single pass above).
        if tm is not None and tm[4] is not None:
            hist = tm[4]
            macd_vote = max(-1.0, min(1.0, hist / (abs(closes[-1]) * 0.002 + 1e-9)))
            votes.append(macd_vote)
            reasons.append(f"MACD hist {hist:+.5f}")

        # 4) Mean-reversion guard: fade extreme Bollinger excursions.
        bands = ind.bollinger(closes, min(20, len(closes)))
        if bands is not None:
            lower, mid, upper = bands
            price = closes[-1]
            if price >= upper:
                votes.append(-0.4)
                reasons.append("above upper Bollinger (stretched)")
            elif price <= lower:
                votes.append(0.4)
                reasons.append("below lower Bollinger (stretched)")

        if not votes:
            return None

        score = sum(votes) / len(votes)
        side = Side.BUY if score > 0.05 else Side.SELL if score < -0.05 else Side.FLAT
        confidence = min(1.0, abs(score))
        return Signal(
            agent=self.name,
            symbol=symbol,
            side=side,
            confidence=confidence,
            rationale="; ".join(reasons),
            features={"score": round(score, 4), "rsi": rsi_val},
        )
