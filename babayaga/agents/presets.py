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
from babayaga.agents.regime_switch import RegimeSwitchAgent
from babayaga.agents.risk import RiskLimits
from babayaga.agents.sentiment import SentimentAgent
from babayaga.agents.technical import TechnicalAgent


def strategy_preset(kind: str) -> tuple[RiskLimits, list[SpecialistAgent]]:
    """Return (risk limits, specialist committee) for a named strategy family."""
    kind = kind.strip().lower()
    # Exit policy for the reversion-based families (meanrev, regime, ensemble):
    # these were validated in deep_search with SIGNAL-driven exits and NO fixed
    # stop/target. A tight ATR stop stops them out on the extra stretch right
    # before the reversion, and a fixed take-profit caps the reversion — both
    # convert winners into losers. So: no take-profit (atr_target_mult=0 -> let
    # winners run to the signal exit) and only a WIDE catastrophic stop
    # (atr_stop_mult=6) as a gap backstop. A wider stop also shrinks position
    # size for the same fixed $ risk, so this is not more leverage — it is less.
    SIGNAL_EXIT_STOP = 6.0
    if kind in ("ensemble", "portfolio", "combo", "all"):
        # ALL strategies working together as one committee. The coordinator
        # votes their signals: when regime-switch and mean-reversion AGREE the
        # signal is strong; when they conflict they cancel toward FLAT — so the
        # ensemble only trades high-conviction setups and sits out the rest.
        # This is the diversification the owner asked for: two edges + many
        # instruments smooth each other's rough patches.
        return (
            RiskLimits(
                min_trend_strength=0.0,
                atr_stop_mult=SIGNAL_EXIT_STOP,
                atr_target_mult=0.0,  # signal-driven exit; let winners run
                min_confidence=0.15,
            ),
            [RegimeSwitchAgent(), MeanReversionAgent()],
        )
    if kind in ("regime", "regime-switch", "regimeswitch"):
        # Best out-of-sample family in scripts/deep_search.py on real data
        # (+0.42% OOS median, walk-forward). The agent decides trend-vs-range
        # itself via the Efficiency Ratio, so the risk layer must NOT also
        # impose a trend filter (min_trend_strength=0).
        return (
            RiskLimits(
                min_trend_strength=0.0,
                atr_stop_mult=SIGNAL_EXIT_STOP,
                atr_target_mult=0.0,  # signal-driven exit; let winners run
                min_confidence=0.1,
            ),
            [RegimeSwitchAgent()],
        )
    if kind == "meanrev":
        # Fade Bollinger extremes, no trend filter (it trades AGAINST stretches).
        # Exit on signal (price returning to the mean), not a fixed target that
        # would cap the reversion; wide catastrophic stop only.
        return (
            RiskLimits(
                min_trend_strength=0.0,
                atr_stop_mult=SIGNAL_EXIT_STOP,
                atr_target_mult=0.0,  # signal-driven exit; let winners run
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
    raise ValueError(
        f"unknown strategy {kind!r} — use 'regime', 'meanrev' or 'trend'"
    )
