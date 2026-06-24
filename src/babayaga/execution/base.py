"""Abstract interface every order executor implements."""

from __future__ import annotations

from abc import ABC, abstractmethod

from babayaga.core.models import Fill, Order


class Executor(ABC):
    venue: str

    @abstractmethod
    async def execute(self, order: Order) -> Fill:
        """Submit `order` to this venue and return the resulting fill.

        Implementations must raise on failure rather than returning a
        partially-populated Fill - the engine treats exceptions as
        OrderStatus.FAILED and stops the round-trip before the other leg fires.
        """
        raise NotImplementedError
