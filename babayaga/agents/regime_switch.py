"""Regime-switch agent — trend-follow when the market trends, fade when it chops.

This is the strategy that, for the first time in the project, came out
**positive out-of-sample** on 17 years of real prices across 10 instruments,
net of spread, walk-forward (see ``scripts/deep_search.py`` and ``MISSION.md``).
On pure random walks the same logic loses, so its edge is a real property of
the data, not curve-fitting.

The idea the owner kept pushing for, made concrete:

* Measure the **regime** with Kaufman's Efficiency Ratio (ER) over a lookback.
  ER near 1 = a clean trend; ER near 0 = choppy/ranging.
* **Trending regime** (ER >= ``er_thr``): follow the trend — long above the
  SMA, short below it.
* **Ranging regime** (ER < ``er_thr``): fade the extreme — buy a low z-score,
  sell a high one.

Defaults are the parameters the research *locked on the in-sample years before*
scoring out-of-sample (``er_win=30, er_thr=0.35, sma_win=20``), so they were
never fit to the data they were judged on. Pure and stateless like every
specialist: ``evaluate`` reads the window and returns a :class:`Signal`.
"""

from __future__ import annotations

from collections.abc import Sequence

from babayaga.agents.base import SpecialistAgent
from babayaga.analytics import indicators as ind
from babayaga.kernel.events import Candle, Side, Signal


class RegimeSwitchAgent(SpecialistAgent):
    name = "regime_switch"

    def __init__(
        self,
        er_win: int = 30,
        er_thr: float = 0.35,
        sma_win: int = 20,
        z_win: int = 20,
        entry_z: float = 1.0,
        weight: float = 1.0,
    ) -> None:
        self.er_win = er_win
        self.er_thr = er_thr
        self.sma_win = sma_win
        self.z_win = z_win
        self.entry_z = entry_z
        self.weight = weight

    def evaluate(self, symbol: str, history: Sequence[Candle]) -> Signal | None:
        closes = self.closes(history)
        # Need enough history for both the ER window and the SMA/z window.
        need = max(self.er_win + 1, self.sma_win, self.z_win) + 1
        if len(closes) < need:
            return None

        er = ind.efficiency_ratio(closes, self.er_win)
        if er is None:
            return None

        if er >= self.er_thr:
            return self._trend_signal(symbol, closes, er)
        return self._revert_signal(symbol, closes, er)

    # -- trending regime: go with the move -----------------------------------
    def _trend_signal(self, symbol: str, closes: list[float], er: float) -> Signal | None:
        mid = ind.sma(closes, self.sma_win)
        if mid is None or mid == 0:
            return None
        price = closes[-1]
        gap = (price - mid) / mid  # fractional distance from the SMA
        # Conviction scales with how far above/below the SMA we are, capped.
        score = max(-1.0, min(1.0, gap / 0.01))  # ~1% gap -> full conviction
        side = Side.BUY if score > 0.1 else Side.SELL if score < -0.1 else Side.FLAT
        return Signal(
            agent=self.name,
            symbol=symbol,
            side=side,
            confidence=min(1.0, abs(score)),
            rationale=(f"TREND regime (ER {er:.2f}>= {self.er_thr}) — "
                       f"price {'above' if gap >= 0 else 'below'} {self.sma_win}-SMA"),
            features={"regime": "trend", "er": round(er, 3), "gap": round(gap, 5)},
        )

    # -- ranging regime: fade the extreme ------------------------------------
    def _revert_signal(self, symbol: str, closes: list[float], er: float) -> Signal | None:
        bands = ind.bollinger(closes, self.z_win)
        if bands is None:
            return None
        _lower, mid, upper = bands
        std = (upper - mid) / 2.0
        if std <= 0:
            return None
        z = (closes[-1] - mid) / std
        # Fade: above the mean -> sell, below -> buy. Full conviction at entry_z.
        score = max(-1.0, min(1.0, -z / self.entry_z))
        side = Side.BUY if score > 0.1 else Side.SELL if score < -0.1 else Side.FLAT
        return Signal(
            agent=self.name,
            symbol=symbol,
            side=side,
            confidence=min(1.0, abs(score)),
            rationale=(f"RANGE regime (ER {er:.2f}< {self.er_thr}) — z-score "
                       f"{z:+.2f} ({'oversold' if z < 0 else 'overbought'})"),
            features={"regime": "range", "er": round(er, 3), "zscore": round(z, 3)},
        )
