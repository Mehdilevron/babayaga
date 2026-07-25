"""Coordinator (supervisor) agent.

Collects the specialist signals for an instrument and fuses them into a single
raw directional view via a confidence-weighted vote, then defers to the risk
agent for sizing and protective levels. This is the "committee chair": it never
trades on one analyst's opinion alone.
"""

from __future__ import annotations

from collections.abc import Sequence

from babayaga.agents.base import SpecialistAgent
from babayaga.agents.risk import RiskAgent
from babayaga.kernel.events import Candle, Decision, Side, Signal


class Coordinator:
    name = "coordinator"

    def __init__(self, specialists: Sequence[SpecialistAgent], risk: RiskAgent) -> None:
        self.specialists = list(specialists)
        self.risk = risk

    def gather(self, symbol: str, history: Sequence[Candle]) -> list[Signal]:
        signals: list[Signal] = []
        for agent in self.specialists:
            sig = agent.evaluate(symbol, history)
            if sig is not None:
                signals.append(sig)
        return signals

    def decide(
        self,
        symbol: str,
        history: Sequence[Candle],
        equity: float,
        current_units: float,
    ) -> tuple[Decision, list[Signal]]:
        signals = self.gather(symbol, history)
        if not signals:
            return (
                Decision(symbol, Side.FLAT, 0.0, 0.0, "no signals yet"),
                signals,
            )

        weight_by_name = {a.name: a.weight for a in self.specialists}
        total_weight = 0.0
        net = 0.0
        for s in signals:
            w = weight_by_name.get(s.agent, 1.0)
            total_weight += w
            net += s.side.sign * s.confidence * w
        score = net / total_weight if total_weight else 0.0

        raw_side = Side.BUY if score > 0.05 else Side.SELL if score < -0.05 else Side.FLAT
        confidence = min(1.0, abs(score))
        agreement = ", ".join(f"{s.agent}:{s.side.value}({s.confidence:.2f})" for s in signals)
        rationale = f"vote={score:+.2f} [{agreement}]"

        decision = self.risk.assess(
            symbol=symbol,
            raw_side=raw_side,
            confidence=confidence,
            rationale=rationale,
            history=history,
            equity=equity,
            current_units=current_units,
            contributing=tuple(signals),
        )
        return decision, signals
