"""Execution agent.

Translates a risk-approved :class:`Decision` into concrete broker orders and
manages the transition from the current position to the target one. Its policy
is designed to avoid over-trading:

* **Flat decision** → close any open position.
* **Same direction as current position** → hold (don't churn size every bar).
* **Opposite direction, or currently flat** → close what's open (if anything)
  and open the newly sized position with its stop/target attached.
"""

from __future__ import annotations

from babayaga.integration.broker import Broker
from babayaga.kernel.events import Decision, Fill, Order, Side


class ExecutionAgent:
    name = "execution"

    def __init__(self, broker: Broker) -> None:
        self.broker = broker

    def execute(self, decision: Decision, current_units: float, mark_price: float) -> list[Fill]:
        fills: list[Fill] = []
        current_side = (
            Side.BUY if current_units > 0 else Side.SELL if current_units < 0 else Side.FLAT
        )

        # 1) Flat decision: close everything.
        if decision.side is Side.FLAT or decision.size <= 0:
            if current_units != 0:
                closing = Order(
                    decision.symbol,
                    Side.SELL if current_units > 0 else Side.BUY,
                    abs(current_units),
                    reason="close (flat decision)",
                )
                fill = self.broker.submit(closing, mark_price)
                if fill:
                    fills.append(fill)
            return fills

        # 2) Already positioned the same way: hold.
        if current_side is decision.side and current_units != 0:
            return fills

        # 3) Reverse or open: first close an opposing position.
        if current_units != 0 and current_side is not decision.side:
            closing = Order(
                decision.symbol,
                Side.SELL if current_units > 0 else Side.BUY,
                abs(current_units),
                reason="close (reverse)",
            )
            fill = self.broker.submit(closing, mark_price)
            if fill:
                fills.append(fill)

        # 4) Open the new, sized position with protective levels.
        opening = Order(
            symbol=decision.symbol,
            side=decision.side,
            size=decision.size,
            stop_loss=decision.stop_loss,
            take_profit=decision.take_profit,
            reason=decision.rationale[:120],
        )
        fill = self.broker.submit(opening, mark_price)
        if fill:
            fills.append(fill)
        return fills
