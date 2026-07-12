"""Integration layer: pluggable market-data feeds and broker adapters.

The OANDA adapter (``OandaClient``, ``OandaFeed``, ``OandaBroker``) lives in
``babayaga.integration.oanda`` and is imported lazily via ``__getattr__`` so the
core has zero import-time coupling to it.
"""

from typing import TYPE_CHECKING

from babayaga.integration.broker import Broker, PaperBroker, Position
from babayaga.integration.market_data import (
    MarketDataFeed,
    ReplayFeed,
    SimulatedFeed,
)

if TYPE_CHECKING:  # for type checkers / IDEs only
    from babayaga.integration.exness import ExnessMT5Broker, ExnessMT5Feed
    from babayaga.integration.oanda import (
        OandaBroker,
        OandaClient,
        OandaFeed,
        OandaStreamFeed,
    )

__all__ = [
    "MarketDataFeed",
    "SimulatedFeed",
    "ReplayFeed",
    "Broker",
    "PaperBroker",
    "Position",
    "OandaClient",
    "OandaFeed",
    "OandaStreamFeed",
    "OandaBroker",
    "ExnessMT5Feed",
    "ExnessMT5Broker",
]

_OANDA = {"OandaClient", "OandaFeed", "OandaStreamFeed", "OandaBroker"}
_EXNESS = {"ExnessMT5Feed", "ExnessMT5Broker"}


def __getattr__(name: str):
    if name in _OANDA:
        from babayaga.integration import oanda

        return getattr(oanda, name)
    if name in _EXNESS:
        from babayaga.integration import exness

        return getattr(exness, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
