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
    spread: float = 0.0001          # 1 pip on a 4-decimal FX pair
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
    sim_start_price: float = 1.1000

    # Safety switch. The OS is paper-only; this must stay False unless you have
    # implemented and vetted a real broker adapter yourself.
    allow_live_trading: bool = False
