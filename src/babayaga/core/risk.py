"""Risk management: per-trade limits, a daily-loss kill switch, and a
file-based emergency stop that takes effect on the engine's next tick.

This is the one module every execution path must go through before an order
is ever signed - feeds and executors don't enforce limits themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional, Tuple, Union

from babayaga.config import RiskConfig
from babayaga.core.models import ArbOpportunity, TradeRecord


@dataclass
class RiskState:
    open_positions: int = 0
    realized_pnl_today_usd: float = 0.0
    tracked_day: date = field(default_factory=date.today)
    kill_switch_tripped: bool = False
    trip_reason: Optional[str] = None


class RiskManager:
    def __init__(self, config: RiskConfig, kill_switch_path: Union[str, Path] = "kill_switch.flag"):
        self.config = config
        self.kill_switch_path = Path(kill_switch_path)
        self.state = RiskState()

    def _roll_day_if_needed(self) -> None:
        today = date.today()
        if today != self.state.tracked_day:
            self.state.tracked_day = today
            self.state.realized_pnl_today_usd = 0.0
            # A new day clears a daily-loss trip, but never a manual file-based stop.
            if self.state.trip_reason == "max_daily_loss":
                self.state.kill_switch_tripped = False
                self.state.trip_reason = None

    def is_halted(self) -> bool:
        self._roll_day_if_needed()
        if self.kill_switch_path.exists():
            self.state.kill_switch_tripped = True
            self.state.trip_reason = self.state.trip_reason or "kill_switch_file"
        return self.state.kill_switch_tripped

    def evaluate(self, opportunity: ArbOpportunity) -> Tuple[bool, str]:
        """Decide whether `opportunity` is allowed to execute right now."""
        if self.is_halted():
            return False, f"halted: {self.state.trip_reason}"

        if opportunity.net_profit_bps < self.config.min_profit_bps:
            return False, (
                f"net profit {opportunity.net_profit_bps:.1f}bps below floor "
                f"{self.config.min_profit_bps:.1f}bps"
            )

        notional_usd = opportunity.size_base * opportunity.buy_quote.ask
        if notional_usd > self.config.max_position_usd:
            return False, (
                f"notional ${notional_usd:.2f} exceeds max_position_usd "
                f"${self.config.max_position_usd:.2f}"
            )

        if self.state.open_positions >= self.config.max_open_positions:
            return False, (
                f"open positions {self.state.open_positions} at max "
                f"{self.config.max_open_positions}"
            )

        if -self.state.realized_pnl_today_usd >= self.config.max_daily_loss_usd:
            return False, "max_daily_loss_usd already reached for today"

        return True, "ok"

    def max_size_within_limits(self, opportunity: ArbOpportunity) -> float:
        """Clamp size_base down to respect max_position_usd, in case the
        opportunity was sized off the full available on-chain/MT5 liquidity."""
        price = opportunity.buy_quote.ask
        if price <= 0:
            return 0.0
        max_size = self.config.max_position_usd / price
        return min(opportunity.size_base, max_size)

    def trip(self, reason: str) -> None:
        """Manually halt trading, e.g. when the engine's first leg fills but
        the second leg fails, leaving an unhedged position that needs human
        attention before the bot should be trusted to resume on its own."""
        self.state.kill_switch_tripped = True
        self.state.trip_reason = reason

    def on_position_opened(self) -> None:
        self.state.open_positions += 1

    def on_position_closed(self) -> None:
        self.state.open_positions = max(0, self.state.open_positions - 1)

    def record_trade(self, trade: TradeRecord) -> None:
        self._roll_day_if_needed()
        self.state.realized_pnl_today_usd += trade.realized_pnl_usd
        if -self.state.realized_pnl_today_usd >= self.config.max_daily_loss_usd:
            self.state.kill_switch_tripped = True
            self.state.trip_reason = "max_daily_loss"
