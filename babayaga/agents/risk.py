"""Risk-management agent.

Sits between the coordinator's raw directional view and the execution agent. Its
job is capital preservation:

* size positions by **fractional risk** — never risk more than ``risk_per_trade``
  of equity on a single idea, with the stop distance derived from ATR;
* attach ATR-based stop-loss and take-profit levels;
* enforce a portfolio **drawdown circuit-breaker** and a gross-exposure cap;
* **veto** trades whose confidence is too low or which would breach a limit.

It is deliberately conservative — the whole system is paper-only, but the risk
agent is written as if real money were at stake.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from babayaga.analytics import indicators as ind
from babayaga.kernel.events import Candle, Decision, Side, Signal


@dataclass
class RiskLimits:
    risk_per_trade: float = 0.01        # fraction of equity risked per trade
    atr_period: int = 14
    atr_stop_mult: float = 2.0          # stop = entry -/+ mult * ATR
    atr_target_mult: float = 3.0        # target = entry +/- mult * ATR
    max_gross_exposure: float = 3.0     # max notional / equity (leverage cap)
    max_drawdown_pct: float = 20.0      # halt new risk beyond this DD from peak
    min_confidence: float = 0.15
    max_units: float = 1_000_000.0
    # Regime filter: require a real trend before trading. Measured as the EMA
    # fast/slow separation in units of ATR. 0.0 = off (trade everything). A
    # value like 0.5 means "only trade when the trend is at least half an ATR
    # of separation" — i.e. sit out the chop where trend-followers bleed.
    min_trend_strength: float = 0.0
    trend_fast: int = 12
    trend_slow: int = 26
    # Volatility floor: skip dead markets where ATR is a tiny fraction of price.
    # There's nothing to capture and the spread dominates. 0.0 = off.
    min_atr_pct: float = 0.0


class RiskAgent:
    name = "risk"

    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()
        self._peak_equity: float | None = None
        self.halted = False

    def update_equity(self, equity: float) -> None:
        """Track peak equity and trip the drawdown breaker if needed."""
        if self._peak_equity is None:
            self._peak_equity = equity
        self._peak_equity = max(self._peak_equity, equity)
        if self._peak_equity > 0:
            dd = (self._peak_equity - equity) / self._peak_equity * 100.0
            self.halted = dd >= self.limits.max_drawdown_pct

    def assess(
        self,
        symbol: str,
        raw_side: Side,
        confidence: float,
        rationale: str,
        history: Sequence[Candle],
        equity: float,
        current_units: float,
        contributing: tuple[Signal, ...] = (),
    ) -> Decision:
        """Produce a sized, protected decision (size may be 0 = stay flat)."""

        def flat(reason: str) -> Decision:
            return Decision(symbol, Side.FLAT, 0.0, confidence, reason, contributing)

        if self.halted:
            return flat(f"RISK HALT: drawdown breaker tripped ({rationale})")
        if raw_side is Side.FLAT:
            return flat(f"no directional edge ({rationale})")
        if confidence < self.limits.min_confidence:
            return flat(
                f"confidence {confidence:.2f} < min {self.limits.min_confidence:.2f}"
            )

        price = history[-1].close
        highs = [c.high for c in history]
        lows = [c.low for c in history]
        closes = [c.close for c in history]
        atr = ind.atr(highs, lows, closes, self.limits.atr_period)
        if atr is None or atr <= 0:
            return flat("ATR unavailable — cannot size stop")

        # Volatility floor: don't trade a market that isn't moving.
        if self.limits.min_atr_pct > 0 and price > 0:
            if atr / price < self.limits.min_atr_pct:
                return flat(
                    f"low volatility (ATR {atr / price * 100:.3f}% < "
                    f"{self.limits.min_atr_pct * 100:.3f}%)"
                )

        # Regime filter: only trade when a genuine trend exists. Trend-followers
        # lose money getting whipsawed in chop while paying the spread; this
        # keeps them flat unless the EMAs have separated by a real margin.
        if self.limits.min_trend_strength > 0:
            fast = ind.ema(closes, self.limits.trend_fast)
            slow = ind.ema(closes, self.limits.trend_slow)
            if fast is None or slow is None:
                return flat("trend filter: not enough data")
            strength = abs(fast - slow) / atr
            if strength < self.limits.min_trend_strength:
                return flat(
                    f"regime filter: chop (trend {strength:.2f} < "
                    f"{self.limits.min_trend_strength:.2f} ATR)"
                )
            # Only trade WITH the higher-level trend, never against it.
            trend_side = Side.BUY if fast > slow else Side.SELL
            if raw_side is not trend_side:
                return flat("regime filter: signal against the prevailing trend")

        stop_dist = self.limits.atr_stop_mult * atr
        target_dist = self.limits.atr_target_mult * atr

        # Fractional-risk position sizing.
        risk_budget = equity * self.limits.risk_per_trade
        units = risk_budget / stop_dist
        # Scale by conviction so weak signals take smaller size.
        units *= confidence

        # Exposure cap.
        max_units_by_exposure = (equity * self.limits.max_gross_exposure) / price
        units = min(units, max_units_by_exposure, self.limits.max_units)
        units = max(0.0, units)
        if units < 1:
            return flat("sized position below 1 unit")

        sign = raw_side.sign
        stop = price - sign * stop_dist
        target = price + sign * target_dist

        return Decision(
            symbol=symbol,
            side=raw_side,
            size=round(units, 2),
            confidence=confidence,
            rationale=(
                f"{rationale} | size {units:,.0f}u risk {self.limits.risk_per_trade:.0%} "
                f"stop {stop:.5f} target {target:.5f} (ATR {atr:.5f})"
            ),
            contributing=contributing,
            stop_loss=round(stop, 6),
            take_profit=round(target, 6),
        )
