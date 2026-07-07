"""Agent base classes for the multi-agent trading workflow.

The workflow has three kinds of participant:

* **Specialist agents** each look at the market through one lens (technical
  structure, sentiment/flow, …) and emit a :class:`Signal` — a direction plus a
  confidence and a human-readable rationale.
* The **coordinator** fuses those signals into a single raw view.
* The **risk agent** and **execution agent** turn that view into a properly
  sized, protected order.

Specialists share a tiny, uniform interface so new ones can be dropped in
without touching the coordinator.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from babayaga.kernel.events import Candle, Signal


class SpecialistAgent(ABC):
    """A single-lens analyst that turns price history into a directional view."""

    #: Weight applied to this agent's confidence when the coordinator votes.
    weight: float = 1.0
    name: str = "specialist"

    @abstractmethod
    def evaluate(self, symbol: str, history: Sequence[Candle]) -> Signal | None:
        """Return a :class:`Signal`, or ``None`` if there isn't enough data."""
        raise NotImplementedError

    @staticmethod
    def closes(history: Sequence[Candle]) -> list[float]:
        return [c.close for c in history]
