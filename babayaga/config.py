"""Configuration for the trading OS."""

from __future__ import annotations

from dataclasses import dataclass, field

from babayaga.agents.risk import RiskLimits


@dataclass
class Config:
    # Instruments the OS trades.
    symbols: tuple[str, ...] = ("EUR/USD",)

    # Account / broker.
    starting_cash: float = 100_000.0
    # Spread in price units. None -> pick a realistic value for the first symbol.
    spread: float | None = None
    commission_per_unit: float = 0.0

    # Data window each agent sees.
    history_window: int = 250

    # Risk configuration.
    risk: RiskLimits = field(default_factory=RiskLimits)

    # Persistence. ":memory:" keeps everything in RAM (nothing written to disk).
    memory_path: str = ":memory:"

    # Simulation defaults (used by the demo/backtest feed).
    sim_steps: int = 500
    sim_seed: int | None = 7
    # Starting price for the simulated feed. None -> a realistic price per symbol.
    sim_start_price: float | None = None
    sim_interval: float = 0.0        # seconds between simulated bars (>0 for live UIs)

    # Safety switch. The OS is paper-only; this must stay False unless you have
    # implemented and vetted a real broker adapter yourself.
    allow_live_trading: bool = False
