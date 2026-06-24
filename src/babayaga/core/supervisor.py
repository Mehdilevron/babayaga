"""Per-pair circuit breaker: pauses a pair when its own recent quotes show
abnormal volatility or a blown-out spread, and resumes it automatically once
conditions look normal again for a few consecutive ticks.

This is built only from data the engine already fetches every tick (the
quotes themselves) - it adds no extra network calls and has no dependency on
an external news feed or LLM. It catches "the market just gapped" style
conditions on a pair-by-pair basis; it does not eliminate drawdown and it is
not a substitute for the kill switch in core/risk.py, which still has final
say over every trade.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional

from babayaga.config import SupervisorConfig
from babayaga.core.models import Quote

logger = logging.getLogger(__name__)


@dataclass
class _PairState:
    mids: Deque[float]
    paused: bool = False
    reason: Optional[str] = None
    clean_ticks: int = 0


class PairSupervisor:
    """Tracks rolling volatility/spread per pair and exposes a pause flag the
    engine checks before acting on an opportunity for that pair."""

    def __init__(self, config: SupervisorConfig):
        self.config = config
        self._state: Dict[str, _PairState] = {}

    def is_supervised(self, pair_name: str) -> bool:
        return self.config.enabled and pair_name in self.config.pairs

    def is_paused(self, pair_name: str) -> bool:
        state = self._state.get(pair_name)
        return state is not None and state.paused

    def pause_reason(self, pair_name: str) -> Optional[str]:
        state = self._state.get(pair_name)
        return state.reason if state is not None else None

    def record(self, pair_name: str, quotes: List[Quote]) -> None:
        """Feed this tick's quotes in; updates the pause/resume state for `pair_name`."""
        if not self.is_supervised(pair_name) or not quotes:
            return

        state = self._state.setdefault(
            pair_name, _PairState(mids=deque(maxlen=self.config.window_size))
        )

        max_spread_bps = 0.0
        for q in quotes:
            if q.mid > 0:
                max_spread_bps = max(max_spread_bps, (q.ask - q.bid) / q.mid * 10_000.0)

        avg_mid = sum(q.mid for q in quotes) / len(quotes)
        if avg_mid > 0:
            state.mids.append(avg_mid)

        volatility_bps = self._volatility_bps(state.mids)

        breach: Optional[str] = None
        if max_spread_bps > self.config.max_spread_bps:
            breach = f"spread {max_spread_bps:.1f}bps > max {self.config.max_spread_bps:.1f}bps"
        elif volatility_bps is not None and volatility_bps > self.config.max_volatility_bps:
            breach = f"volatility {volatility_bps:.1f}bps > max {self.config.max_volatility_bps:.1f}bps"

        if breach is not None:
            if not state.paused:
                logger.warning("pair %s: supervisor pausing - %s", pair_name, breach)
            state.paused = True
            state.reason = breach
            state.clean_ticks = 0
            return

        if state.paused:
            state.clean_ticks += 1
            if state.clean_ticks >= self.config.resume_after_clean_ticks:
                logger.warning(
                    "pair %s: supervisor resuming after %d clean ticks", pair_name, state.clean_ticks
                )
                state.paused = False
                state.reason = None
                state.clean_ticks = 0

    @staticmethod
    def _volatility_bps(mids: Deque[float]) -> Optional[float]:
        """Sample stddev of tick-to-tick returns, in bps. None until there's
        enough history (3+ points) to mean anything."""
        if len(mids) < 3:
            return None
        returns = []
        prev = None
        for m in mids:
            if prev is not None and prev > 0:
                returns.append((m - prev) / prev)
            prev = m
        if len(returns) < 2:
            return None
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        return math.sqrt(variance) * 10_000.0
