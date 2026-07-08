"""Broker adapters — the "execution" side of the integration layer.

``PaperBroker`` is a fully functional in-memory broker that maintains positions,
cash, realised and unrealised P&L, applies configurable spread and commission,
and honours stop-loss / take-profit levels. ``OandaBroker`` is a documented stub
that shows where a real venue plugs in — it deliberately refuses to trade.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from babayaga.kernel.events import Fill, Order, Side


@dataclass
class Position:
    symbol: str
    size: float = 0.0            # signed: >0 long, <0 short
    avg_price: float = 0.0
    stop_loss: float | None = None
    take_profit: float | None = None

    @property
    def side(self) -> Side:
        if self.size > 0:
            return Side.BUY
        if self.size < 0:
            return Side.SELL
        return Side.FLAT

    def unrealized(self, mark: float) -> float:
        return (mark - self.avg_price) * self.size


class Broker(ABC):
    @abstractmethod
    def submit(self, order: Order, mark_price: float) -> Fill | None: ...

    @abstractmethod
    def mark_to_market(self, symbol: str, price: float) -> None: ...

    @property
    @abstractmethod
    def equity(self) -> float: ...


class PaperBroker(Broker):
    def __init__(
        self,
        starting_cash: float = 100_000.0,
        spread: float = 0.0001,       # quoted in price units (1 pip on EUR/USD)
        commission_per_unit: float = 0.0,
    ) -> None:
        self.starting_cash = starting_cash
        self.cash = starting_cash
        self.spread = spread
        self.commission_per_unit = commission_per_unit
        self.positions: dict[str, Position] = {}
        self.realized_pnl = 0.0
        self._marks: dict[str, float] = {}
        self.closed_trade_pnls: list[float] = []

    # -- pricing ----------------------------------------------------------
    def _fill_price(self, side: Side, mark: float) -> float:
        """Apply half-spread slippage against the taker."""
        half = self.spread / 2.0
        if side is Side.BUY:
            return mark + half
        if side is Side.SELL:
            return mark - half
        return mark

    def mark_to_market(self, symbol: str, price: float) -> None:
        self._marks[symbol] = price
        self._check_protective_exits(symbol, price)

    # -- protective exits -------------------------------------------------
    def _check_protective_exits(self, symbol: str, price: float) -> None:
        pos = self.positions.get(symbol)
        if not pos or pos.size == 0:
            return
        hit_stop = pos.stop_loss is not None and (
            (pos.size > 0 and price <= pos.stop_loss)
            or (pos.size < 0 and price >= pos.stop_loss)
        )
        hit_tp = pos.take_profit is not None and (
            (pos.size > 0 and price >= pos.take_profit)
            or (pos.size < 0 and price <= pos.take_profit)
        )
        if hit_stop or hit_tp:
            reason = "stop_loss" if hit_stop else "take_profit"
            self.submit(
                Order(symbol, Side.SELL if pos.size > 0 else Side.BUY, abs(pos.size), reason=reason),
                price,
            )

    # -- order handling ---------------------------------------------------
    def submit(self, order: Order, mark_price: float) -> Fill | None:
        if order.size <= 0 or order.side is Side.FLAT:
            return None
        fill_price = self._fill_price(order.side, mark_price)
        signed = order.size * order.side.sign
        pos = self.positions.setdefault(order.symbol, Position(order.symbol))

        prev_size = pos.size
        new_size = prev_size + signed

        # Realise P&L on the portion of the position being reduced/closed.
        if prev_size != 0 and (prev_size > 0) != (signed > 0):
            closing = min(abs(signed), abs(prev_size))
            direction = 1 if prev_size > 0 else -1
            pnl = (fill_price - pos.avg_price) * closing * direction
            self.realized_pnl += pnl
            self.cash += pnl
            self.closed_trade_pnls.append(pnl)

        # Update average price when opening or adding in the same direction.
        if new_size == 0:
            pos.avg_price = 0.0
            pos.stop_loss = None
            pos.take_profit = None
        elif prev_size == 0 or (prev_size > 0) == (signed > 0):
            # Weighted average entry.
            total_cost = pos.avg_price * abs(prev_size) + fill_price * abs(signed)
            pos.avg_price = total_cost / abs(new_size)
        # else: reducing but not flipping — keep avg_price.

        pos.size = new_size
        # Attach protective levels for freshly opened/added positions.
        if order.stop_loss is not None:
            pos.stop_loss = order.stop_loss
        if order.take_profit is not None:
            pos.take_profit = order.take_profit

        commission = self.commission_per_unit * order.size
        self.cash -= commission

        self._marks[order.symbol] = mark_price
        return Fill(
            symbol=order.symbol,
            side=order.side,
            size=order.size,
            price=fill_price,
            order_reason=order.reason,
            timestamp=order.timestamp,
        )

    # -- account ----------------------------------------------------------
    @property
    def unrealized_pnl(self) -> float:
        total = 0.0
        for sym, pos in self.positions.items():
            mark = self._marks.get(sym)
            if mark is not None:
                total += pos.unrealized(mark)
        return total

    @property
    def equity(self) -> float:
        return self.cash + self.unrealized_pnl

    def open_position_count(self) -> int:
        return sum(1 for p in self.positions.values() if p.size != 0)


# A real OANDA broker lives in ``babayaga.integration.oanda`` (imported lazily to
# avoid a circular import, since that module imports from this one).
