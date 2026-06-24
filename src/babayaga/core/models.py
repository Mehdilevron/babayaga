"""Domain models shared by feeds, the opportunity detector, risk manager, and executors."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    FAILED = "failed"
    REJECTED = "rejected"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Quote:
    """A single venue's price for base/quote at a point in time."""

    venue: str
    base: str
    quote: str
    bid: float  # price received per unit of base when selling into this venue
    ask: float  # price paid per unit of base when buying from this venue
    fee_bps: float
    timestamp: datetime = field(default_factory=_utcnow)
    liquidity_usd: Optional[float] = None  # depth hint, when the feed can supply one

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


@dataclass(frozen=True)
class ArbOpportunity:
    """A detected, sized arbitrage opportunity between a buy leg and a sell/hedge leg."""

    pair_name: str
    buy_quote: Quote  # buy `base` here, at its ask
    sell_quote: Quote  # sell `base` here (or open the offsetting hedge), at its bid
    size_base: float
    gross_spread_bps: float
    est_cost_bps: float  # fees + gas + slippage buffer, in basis points
    net_profit_bps: float
    est_net_profit_usd: float
    is_hedge: bool = False  # True when sell_quote is an MT5 offsetting position, not a sale

    @property
    def is_profitable(self) -> bool:
        return self.net_profit_bps > 0


@dataclass
class Order:
    venue: str
    side: Side
    base: str
    quote: str
    size_base: float
    limit_price: float  # worst acceptable price after slippage tolerance
    status: OrderStatus = OrderStatus.PENDING
    tx_hash: Optional[str] = None
    error: Optional[str] = None


@dataclass
class Fill:
    order: Order
    filled_size_base: float
    avg_price: float
    fee_paid_usd: float
    timestamp: datetime = field(default_factory=_utcnow)


@dataclass
class TradeRecord:
    """One full arbitrage round-trip (both legs), for the audit log and PnL tracking."""

    opportunity: ArbOpportunity
    buy_fill: Optional[Fill]
    sell_fill: Optional[Fill]
    realized_pnl_usd: float
    dry_run: bool
    timestamp: datetime = field(default_factory=_utcnow)
