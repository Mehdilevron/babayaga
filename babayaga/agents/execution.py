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

    def __init__(self, broker: Broker, min_flip_bars: int = 0) -> None:
        self.broker = broker
        #: Minimum bars between direction changes per symbol (0 = off). Real
        #: accounts pay the spread on every reversal; this stops bar-to-bar
        #: churn when the committee's vote oscillates around zero.
        self.min_flip_bars = min_flip_bars
        self._bar: dict[str, int] = {}
        self._last_dir: dict[str, Side] = {}
        self._last_change_bar: dict[str, int] = {}

    def execute(self, decision: Decision, current_units: float, mark_price: float) -> list[Fill]:
        fills: list[Fill] = []
        symbol = decision.symbol
        bar = self._bar.get(symbol, 0) + 1
        self._bar[symbol] = bar
        current_side = (
            Side.BUY if current_units > 0 else Side.SELL if current_units < 0 else Side.FLAT
        )

        # Flip cooldown: refuse to change direction more often than every
        # ``min_flip_bars`` bars. Closing to flat is never blocked.
        wants_open = decision.side in (Side.BUY, Side.SELL) and decision.size > 0
        prev_dir = self._last_dir.get(symbol)
        if (
            wants_open
            and self.min_flip_bars > 0
            and prev_dir is not None
            and decision.side is not prev_dir
            and bar - self._last_change_bar.get(symbol, -(10**9)) < self.min_flip_bars
        ):
            return fills

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
            if self._last_dir.get(symbol) is not decision.side:
                self._last_change_bar[symbol] = bar
            self._last_dir[symbol] = decision.side
        return fills
