"""Abstract interface every price feed implements."""

from __future__ import annotations

from abc import ABC, abstractmethod

from babayaga.core.models import Quote


class PriceFeed(ABC):
    venue: str

    @abstractmethod
    async def get_quote(self, base: str, quote: str, size_base: float) -> Quote:
        """Fetch a fresh bid/ask for `size_base` units of base/quote from this venue."""
        raise NotImplementedError
