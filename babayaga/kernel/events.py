"""Core message types exchanged over the kernel event bus.

These are intentionally plain dataclasses so they can be serialised to the
memory store, logged, or shipped over a network transport later without pulling
in a schema framework.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Topic(str, Enum):
    """Well-known channels on the event bus."""

    TICK = "tick"            # new market candle from a data feed
    SIGNAL = "signal"        # a specialist agent's opinion
    DECISION = "decision"    # the coordinator's fused decision
    ORDER = "order"          # an order submitted to the broker
    FILL = "fill"            # a broker fill / execution report
    ACCOUNT = "account"      # account/equity snapshot
    LOG = "log"              # human-readable telemetry


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"
    FLAT = "flat"

    @property
    def sign(self) -> int:
        return {Side.BUY: 1, Side.SELL: -1, Side.FLAT: 0}[self]


@dataclass(frozen=True)
class Candle:
    """A single OHLCV bar for one instrument."""

    symbol: str
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def mid(self) -> float:
        return self.close


@dataclass(frozen=True)
class Signal:
    """A specialist agent's directional view on an instrument."""

    agent: str
    symbol: str
    side: Side
    confidence: float          # 0.0 .. 1.0
    rationale: str = ""
    timestamp: float = field(default_factory=time.time)
    features: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "confidence", max(0.0, min(1.0, self.confidence)))


@dataclass(frozen=True)
class Decision:
    """The coordinator's fused, risk-adjusted trading decision."""

    symbol: str
    side: Side
    size: float                # units; 0 means "no trade / stay flat"
    confidence: float
    rationale: str
    contributing: tuple[Signal, ...] = ()
    stop_loss: float | None = None
    take_profit: float | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class Order:
    symbol: str
    side: Side
    size: float
    kind: str = "market"       # market | limit
    limit_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    reason: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class Fill:
    symbol: str
    side: Side
    size: float
    price: float
    order_reason: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class AccountSnapshot:
    balance: float
    equity: float
    unrealized_pnl: float
    realized_pnl: float
    open_positions: int
    # True when trading is frozen (drawdown breaker or hard stop) — surfaces
    # the halt on dashboards instead of the bot silently going quiet.
    halted: bool = False
    timestamp: float = field(default_factory=time.time)
