"""The BabaYaga trading OS — boots every layer and runs the coordination loop.

``TradingOS`` is the kernel process: it owns the event bus, the memory store, the
broker and the agent workflow, wires them together as pub/sub subscribers, and
drives market-data feeds through the whole pipeline:

    feed → TICK → coordinator (specialists + risk) → DECISION → execution → FILL

Everything is event-driven over :class:`~babayaga.kernel.bus.EventBus`, so the
memory layer, a console logger, or any future observer simply subscribes to the
topics it cares about.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from collections.abc import Callable

from babayaga.agents.coordinator import Coordinator
from babayaga.agents.execution import ExecutionAgent
from babayaga.agents.risk import RiskAgent
from babayaga.agents.sentiment import SentimentAgent
from babayaga.agents.technical import TechnicalAgent
from babayaga.analytics.metrics import PerformanceSummary, performance_summary
from babayaga.config import Config
from babayaga.integration.broker import PaperBroker
from babayaga.integration.market_data import (
    MarketDataFeed,
    SimulatedFeed,
    typical_price,
)
from babayaga.kernel.bus import EventBus
from babayaga.kernel.events import (
    AccountSnapshot,
    Candle,
    Decision,
    Side,
    Topic,
)
from babayaga.memory.store import MemoryStore

log = logging.getLogger("babayaga.os")


class TradingOS:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config()

        # --- kernel + persistence -------------------------------------
        self.bus = EventBus()
        self.memory = MemoryStore(
            self.config.memory_path,
            max_ticks=self.config.memory_max_ticks,
            max_signals=self.config.memory_max_signals,
            max_decisions=self.config.memory_max_decisions,
        )

        # --- integration layer ----------------------------------------
        # spread=None lets the paper broker charge a realistic spread per
        # symbol (crucial for multi-pair runs).
        self.broker = PaperBroker(
            starting_cash=self.config.starting_cash,
            spread=self.config.spread,
            commission_per_unit=self.config.commission_per_unit,
            slippage=self.config.slippage,
            equity_floor=(
                None
                if self.config.hard_stop_loss is None
                else self.config.starting_cash - self.config.hard_stop_loss
            ),
        )

        # --- agent workflow -------------------------------------------
        self.risk = RiskAgent(self.config.risk)
        specialists = [TechnicalAgent(), SentimentAgent()]
        self.coordinator = Coordinator(specialists, self.risk)
        self.execution = ExecutionAgent(
            self.broker, min_flip_bars=self.config.flip_cooldown_bars
        )

        # --- runtime state --------------------------------------------
        self._windows: dict[str, deque[Candle]] = defaultdict(
            lambda: deque(maxlen=self.config.history_window)
        )
        self._feeds: dict[str, MarketDataFeed] = {}
        self.equity_curve: list[float] = [self.broker.equity]
        self.decisions: list[Decision] = []
        self._running = False

        self._wire_bus()

    # ------------------------------------------------------------------
    # wiring
    # ------------------------------------------------------------------
    def _wire_bus(self) -> None:
        # Memory records the raw event stream, fully decoupled from logic.
        self.bus.subscribe(Topic.TICK, lambda c: self.memory.record_tick(c))
        self.bus.subscribe(Topic.SIGNAL, lambda s: self.memory.record_signal(s))
        self.bus.subscribe(Topic.DECISION, lambda d: self.memory.record_decision(d))
        self.bus.subscribe(Topic.FILL, lambda f: self.memory.record_fill(f))
        # The orchestrator turns each tick into a trading decision.
        self.bus.subscribe(Topic.TICK, self._on_tick)

    def attach_feed(self, symbol: str, feed: MarketDataFeed) -> None:
        self._feeds[symbol] = feed

    def on(self, topic: Topic, handler: Callable) -> None:
        """Public hook so callers (CLI, dashboards) can observe the stream."""
        self.bus.subscribe(topic, handler)

    # ------------------------------------------------------------------
    # core pipeline (runs for every tick)
    # ------------------------------------------------------------------
    async def _on_tick(self, candle: Candle) -> None:
        symbol = candle.symbol
        window = self._windows[symbol]
        window.append(candle)

        # Keep the broker's mark current; this may also trigger stop/target exits.
        self.broker.mark_to_market(symbol, candle.close)
        # Protective exits (stop-loss/take-profit) happen inside the broker —
        # surface them on the bus so memory and the dashboard see every fill.
        for fill in self.broker.pop_protective_fills():
            await self.bus.publish(Topic.FILL, fill)
        self.risk.update_equity(self.broker.equity)

        history = list(window)
        current_units = self._position_units(symbol)
        decision, signals = self.coordinator.decide(
            symbol, history, self.broker.equity, current_units
        )

        for sig in signals:
            await self.bus.publish(Topic.SIGNAL, sig)
        await self.bus.publish(Topic.DECISION, decision)
        self.decisions.append(decision)

        fills = self.execution.execute(decision, current_units, candle.close)
        for fill in fills:
            await self.bus.publish(Topic.FILL, fill)

        # Snapshot the account after any trading.
        self.equity_curve.append(self.broker.equity)
        await self.bus.publish(
            Topic.ACCOUNT,
            AccountSnapshot(
                balance=self.broker.cash,
                equity=self.broker.equity,
                unrealized_pnl=self.broker.unrealized_pnl,
                realized_pnl=self.broker.realized_pnl,
                open_positions=self.broker.open_position_count(),
                halted=self.risk.halted or getattr(self.broker, "halted_hard", False),
            ),
        )

    def _position_units(self, symbol: str) -> float:
        pos = self.broker.positions.get(symbol)
        return pos.size if pos else 0.0

    # ------------------------------------------------------------------
    # running
    # ------------------------------------------------------------------
    async def run(self) -> None:
        """Run every attached feed concurrently until all are exhausted."""
        if self.config.allow_live_trading:  # pragma: no cover - safety guard
            raise RuntimeError(
                "allow_live_trading=True but no vetted live broker is wired. "
                "Refusing to run to avoid any real-money action."
            )
        if not self._feeds:
            # Default: a simulated feed per configured symbol. Offset the seed
            # per symbol so each pair follows its own distinct price path.
            for i, sym in enumerate(self.config.symbols):
                seed = None if self.config.sim_seed is None else self.config.sim_seed + i
                self.attach_feed(
                    sym,
                    SimulatedFeed(
                        symbol=sym,
                        start_price=(
                            self.config.sim_start_price
                            if self.config.sim_start_price is not None
                            else typical_price(sym)
                        ),
                        steps=self.config.sim_steps,
                        seed=seed,
                        interval=self.config.sim_interval,
                        drift_scale=self.config.sim_drift_scale,
                    ),
                )

        self._running = True
        try:
            await asyncio.gather(*(self._drain(f) for f in self._feeds.values()))
        finally:
            self._running = False

    async def _drain(self, feed: MarketDataFeed) -> None:
        async for candle in feed.stream():
            await self.bus.publish(Topic.TICK, candle)
            # Yield to the event loop after every bar. Without this, a feed
            # with no pacing delay (interval=0, i.e. every backtest) runs its
            # ENTIRE history before the next feed gets a turn — multi-pair
            # runs silently became sequential single-pair runs, so early
            # losses on one pair could trip the drawdown breaker and freeze
            # all the others for their whole run. This makes multi-feed runs
            # genuinely concurrent (round-robin per bar).
            await asyncio.sleep(0)

    def run_backtest(self) -> PerformanceSummary:
        """Convenience: run to completion synchronously and return metrics."""
        asyncio.run(self.run())
        return self.performance()

    # ------------------------------------------------------------------
    # reporting
    # ------------------------------------------------------------------
    def performance(self) -> PerformanceSummary:
        return performance_summary(self.equity_curve, self.broker.closed_trade_pnls)

    def shutdown(self) -> None:
        self.memory.close()
