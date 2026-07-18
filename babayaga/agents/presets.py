"""Named strategy presets, chosen by the real-data research.

``scripts/research.py`` on 17 years of real daily FX (7 pairs, ECB rates,
in-sample < 2019 vs out-of-sample >= 2019) found:

    trend    out-of-sample median +0.09%   -> no edge
    meanrev  out-of-sample median +1.31%, mean +9.63%  -> the only survivor

So ``meanrev`` is the recommended trading preset. Both are kept so the
comparison stays reproducible. IMPORTANT: that validation is on DAILY bars —
running either preset on M1 is untested territory.
"""

from __future__ import annotations

from babayaga.agents.base import SpecialistAgent
from babayaga.agents.mean_reversion import MeanReversionAgent
from babayaga.agents.risk import RiskLimits
from babayaga.agents.sentiment import SentimentAgent
from babayaga.agents.technical import TechnicalAgent


def strategy_preset(kind: str) -> tuple[RiskLimits, list[SpecialistAgent]]:
    """Return (risk limits, specialist committee) for a named strategy family."""
    kind = kind.strip().lower()
    if kind == "meanrev":
        # Fade Bollinger extremes; symmetric R:R (reversion targets the mean,
        # not a runaway trend), no trend filter (it trades AGAINST stretches).
        return (
            RiskLimits(
                min_trend_strength=0.0,
                atr_stop_mult=2.0,
                atr_target_mult=2.0,
                min_confidence=0.1,
            ),
            [MeanReversionAgent()],
        )
    if kind == "trend":
        # The original trend-follower with its A/B-tested guards.
        return (
            RiskLimits(min_trend_strength=1.0, atr_stop_mult=1.5, atr_target_mult=6.0),
            [TechnicalAgent(), SentimentAgent()],
        )
    raise ValueError(f"unknown strategy {kind!r} — use 'meanrev' or 'trend'")
