"""The scan -> detect -> risk-check -> execute loop.

Each tick polls every configured pair's venues concurrently, hands any
detected opportunity to the RiskManager, and - if approved - fires the buy
leg then the sell/hedge leg in sequence (never concurrently) so a failed
second leg is always caught before it could go unnoticed.

If the buy leg fails, nothing was opened and the tick just moves on. If the
buy leg fills but the sell/hedge leg then fails, the bot is left holding an
unhedged position it cannot safely unwind on its own - that immediately
trips the kill switch instead of continuing to trade.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

from babayaga.config import PairConfig, Settings
from babayaga.core.models import ArbOpportunity, Fill, Order, OrderStatus, Quote, Side, TradeRecord
from babayaga.core.opportunity import find_best_opportunity
from babayaga.core.risk import RiskManager
from babayaga.factory import VenueRuntime, build_runtimes

logger = logging.getLogger(__name__)


def _json_default(obj):
    if isinstance(obj, (Side, OrderStatus)):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"not JSON serializable: {type(obj)!r}")


class Engine:
    def __init__(
        self,
        settings: Settings,
        runtimes: Dict[str, VenueRuntime],
        risk_manager: RiskManager,
        trades_log_path: Union[str, Path] = "trades.jsonl",
    ):
        self.settings = settings
        self.runtimes = runtimes
        self.risk = risk_manager
        self.trades_log_path = Path(trades_log_path)

    @classmethod
    def from_settings(cls, settings: Settings) -> "Engine":
        runtimes = build_runtimes(settings)
        risk_manager = RiskManager(settings.risk, kill_switch_path=settings.engine.kill_switch_file)
        return cls(settings, runtimes, risk_manager)

    async def run(self, *, iterations: Optional[int] = None) -> None:
        mode = "DRY RUN" if self.settings.dry_run else "LIVE"
        logger.info("babayaga engine starting in %s mode, %d pair(s) configured", mode, len(self.settings.pairs))
        count = 0
        while iterations is None or count < iterations:
            if self.risk.is_halted():
                logger.warning("halted (%s) - skipping this tick", self.risk.state.trip_reason)
            else:
                await self.run_once()
            count += 1
            if iterations is None or count < iterations:
                await asyncio.sleep(self.settings.engine.poll_interval_ms / 1000)

    async def run_once(self) -> None:
        for pair in self.settings.pairs:
            try:
                await self.process_pair(pair)
            except Exception:
                logger.exception("pair %s: unhandled error this tick", pair.name)

    async def process_pair(self, pair: PairConfig) -> None:
        quotes = await self._gather_quotes(pair)
        if quotes is None:
            return

        gas_cost_usd = sum(self.settings.venues[leg.venue].gas_cost_usd_estimate for leg in pair.legs)
        opportunity = find_best_opportunity(
            pair.name,
            quotes,
            pair.size_base,
            gas_cost_usd=gas_cost_usd,
            slippage_bps=self.settings.risk.slippage_bps,
            is_hedge=pair.hedge,
        )
        if opportunity is None:
            return

        ok, reason = self.risk.evaluate(opportunity)
        if not ok:
            logger.debug("pair %s: skipped (%s)", pair.name, reason)
            return

        size = self.risk.max_size_within_limits(opportunity)
        if size <= 0:
            return
        if size != opportunity.size_base:
            # Re-derive economics at the clamped size. The buy/sell prices
            # themselves aren't requoted at the smaller size - on an AMM a
            # smaller fill never gets a worse price than the original quote,
            # so this stays conservative.
            opportunity = ArbOpportunity(
                pair_name=opportunity.pair_name,
                buy_quote=opportunity.buy_quote,
                sell_quote=opportunity.sell_quote,
                size_base=size,
                gross_spread_bps=opportunity.gross_spread_bps,
                est_cost_bps=opportunity.est_cost_bps,
                net_profit_bps=opportunity.net_profit_bps,
                est_net_profit_usd=opportunity.net_profit_bps / 10_000.0 * size * opportunity.buy_quote.ask,
                is_hedge=opportunity.is_hedge,
            )

        logger.info(
            "pair %s: opportunity buy@%s(%.6f) sell@%s(%.6f) net=%.1fbps size=%.6f est=$%.2f",
            pair.name,
            opportunity.buy_quote.venue,
            opportunity.buy_quote.ask,
            opportunity.sell_quote.venue,
            opportunity.sell_quote.bid,
            opportunity.net_profit_bps,
            opportunity.size_base,
            opportunity.est_net_profit_usd,
        )

        await self._execute(pair, opportunity)

    async def _gather_quotes(self, pair: PairConfig) -> Optional[List[Quote]]:
        async def _quote_for(leg):
            runtime = self.runtimes[leg.venue]
            return await runtime.get_quote(pair.base, pair.quote, pair.size_base, leg.symbol)

        results = await asyncio.gather(*(_quote_for(leg) for leg in pair.legs), return_exceptions=True)
        quotes: List[Quote] = []
        for leg, result in zip(pair.legs, results):
            if isinstance(result, Exception):
                logger.warning("pair %s: quote failed on venue %s: %s", pair.name, leg.venue, result)
                return None
            quotes.append(result)
        return quotes

    async def _execute(self, pair: PairConfig, opportunity: ArbOpportunity) -> None:
        leg_symbol = {leg.venue: leg.symbol for leg in pair.legs}

        buy_order = Order(
            venue=opportunity.buy_quote.venue,
            side=Side.BUY,
            base=pair.base,
            quote=pair.quote,
            size_base=opportunity.size_base,
            limit_price=opportunity.buy_quote.ask,
        )
        sell_order = Order(
            venue=opportunity.sell_quote.venue,
            side=Side.SELL,
            base=pair.base,
            quote=pair.quote,
            size_base=opportunity.size_base,
            limit_price=opportunity.sell_quote.bid,
        )
        if pair.hedge:
            # The MT5 leg doesn't sell `base` - it opens an offsetting position
            # that mirrors the *other* leg's side, and Mt5Executor flips that
            # internally to the real hedge direction. Detect which side of the
            # permutation landed on MT5 by venue kind, not by venue name.
            if self.runtimes[opportunity.sell_quote.venue].kind == "mt5":
                sell_order.side = buy_order.side
            elif self.runtimes[opportunity.buy_quote.venue].kind == "mt5":
                buy_order.side = sell_order.side

        try:
            buy_fill = await self._fill(buy_order, leg_symbol.get(buy_order.venue))
        except Exception as exc:
            logger.error("pair %s: buy leg failed, no position opened: %s", pair.name, exc)
            return

        self.risk.on_position_opened()
        try:
            sell_fill = await self._fill(sell_order, leg_symbol.get(sell_order.venue))
        except Exception as exc:
            self.risk.trip("unhedged_leg_failure")
            logger.critical(
                "pair %s: buy leg filled but sell/hedge leg failed - UNHEDGED POSITION, "
                "halting until a human investigates: %s",
                pair.name,
                exc,
            )
            return

        self.risk.on_position_closed()
        realized_pnl_usd = (
            (sell_fill.avg_price - buy_fill.avg_price) * min(buy_fill.filled_size_base, sell_fill.filled_size_base)
            - buy_fill.fee_paid_usd
            - sell_fill.fee_paid_usd
        )
        trade = TradeRecord(
            opportunity=opportunity,
            buy_fill=buy_fill,
            sell_fill=sell_fill,
            realized_pnl_usd=realized_pnl_usd,
            dry_run=self.settings.dry_run,
        )
        self.risk.record_trade(trade)
        self._log_trade(trade)
        logger.info("pair %s: round-trip complete, realized pnl $%.2f", pair.name, realized_pnl_usd)

    async def _fill(self, order: Order, symbol: Optional[str]) -> Fill:
        if self.settings.dry_run:
            order.status = OrderStatus.FILLED
            return Fill(order=order, filled_size_base=order.size_base, avg_price=order.limit_price, fee_paid_usd=0.0)
        runtime = self.runtimes[order.venue]
        return await runtime.place_order(order, symbol)

    def _log_trade(self, trade: TradeRecord) -> None:
        try:
            with self.trades_log_path.open("a") as f:
                f.write(json.dumps(asdict(trade), default=_json_default))
                f.write("\n")
        except OSError:
            logger.exception("failed to write trade log entry")
