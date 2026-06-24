"""Loads config/config.yaml (strategy/risk parameters) and .env (secrets), and
validates that live trading isn't enabled without the credentials it needs.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Union

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict


class EngineConfig(BaseModel):
    poll_interval_ms: int = 750
    kill_switch_file: str = "kill_switch.flag"


class RiskConfig(BaseModel):
    min_profit_bps: float
    max_position_usd: float
    max_daily_loss_usd: float
    max_open_positions: int
    slippage_bps: float


class SupervisorConfig(BaseModel):
    """Optional per-pair circuit breaker built from the engine's own recent
    quotes (no external news/LLM dependency) - see core/supervisor.py."""

    enabled: bool = False
    pairs: List[str] = []  # pair names to supervise; pairs not listed here are never paused
    window_size: int = 20  # rolling number of ticks used to estimate volatility
    max_volatility_bps: float = 150.0  # pause if stddev of tick-to-tick returns exceeds this
    max_spread_bps: float = 300.0  # pause if any leg's own bid/ask spread exceeds this
    resume_after_clean_ticks: int = 5  # consecutive in-bounds ticks required before auto-resuming


class ChainConfig(BaseModel):
    rpc_env: str
    chain_id: Optional[int] = None
    gas_limit_estimate: Optional[int] = None
    # Both optional, and only used to price gas live instead of off the venue's
    # static gas_cost_usd_estimate - see factory.py's gas pricer wiring. Leave
    # unset to keep the static estimate (the previous, still-default, behavior).
    native_token: Optional[str] = None  # wrapped native token symbol, e.g. "WETH"
    native_price_venue: Optional[str] = None  # a venue (from `venues`) quoting native_token against a stablecoin


class VenueConfig(BaseModel):
    kind: str  # evm_v2_router | evm_v3_quoter | jupiter_aggregator | mt5
    chain: Optional[str] = None
    router_address: Optional[str] = None
    quoter_address: Optional[str] = None
    fee_bps: float = 0.0
    gas_cost_usd_estimate: float = 0.0  # static estimate; used as-is unless the chain has live gas pricing configured
    dexes: Optional[str] = None  # jupiter_aggregator only: restrict routing to this comma-separated DEX label list
    stale_quote_after_s: Optional[float] = None  # mt5 only: treat an older tick as a closed/stale market (default 120s)


class PairLeg(BaseModel):
    venue: str
    symbol: Optional[str] = None  # used by mt5 venues, e.g. "XAUUSD"


class PairConfig(BaseModel):
    name: str
    description: str = ""
    base: str
    quote: str
    hedge: bool = False
    size_base: float = 1.0  # quoting/trade size in units of `base`, before risk clamping
    legs: List[PairLeg]


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = True
    engine: EngineConfig = EngineConfig()
    risk: RiskConfig
    supervisor: SupervisorConfig = SupervisorConfig()
    chains: Dict[str, ChainConfig] = {}
    venues: Dict[str, VenueConfig] = {}
    pairs: List[PairConfig]
    tokens: Dict[str, Dict[str, str]] = {}

    # Secrets - populated from the environment in load_settings(), never read
    # from config.yaml itself so this file is always safe to commit.
    evm_private_key: Optional[str] = None
    solana_private_key: Optional[str] = None
    mt5_login: Optional[int] = None
    mt5_password: Optional[str] = None
    mt5_server: Optional[str] = None
    mt5_terminal_path: Optional[str] = None
    rpc_urls: Dict[str, str] = {}

    def require_live_secrets(self) -> None:
        """Raise if going live would touch a venue we don't have credentials for."""
        missing: List[str] = []
        used_kinds = {v.kind for v in self.venues.values()}

        if used_kinds & {"evm_v2_router", "evm_v3_quoter"} and not self.evm_private_key:
            missing.append("EVM_PRIVATE_KEY")
        if "jupiter_aggregator" in used_kinds and not self.solana_private_key:
            missing.append("SOLANA_PRIVATE_KEY")
        if "mt5" in used_kinds and not (self.mt5_login and self.mt5_password and self.mt5_server):
            missing.append("MT5_LOGIN/MT5_PASSWORD/MT5_SERVER")

        for chain in self.chains.values():
            if not self.rpc_urls.get(chain.rpc_env):
                missing.append(chain.rpc_env)

        if missing:
            raise RuntimeError(
                "Refusing to start in live mode - missing required secrets/config: "
                + ", ".join(sorted(set(missing)))
            )


def load_settings(
    config_path: Union[str, Path] = "config/config.yaml",
    env_path: Optional[Union[str, Path]] = None,
    *,
    force_dry_run: Optional[bool] = None,
) -> Settings:
    load_dotenv(env_path or ".env")

    raw = yaml.safe_load(Path(config_path).read_text())
    settings = Settings(**raw)

    settings.evm_private_key = os.getenv("EVM_PRIVATE_KEY") or None
    settings.solana_private_key = os.getenv("SOLANA_PRIVATE_KEY") or None
    mt5_login = os.getenv("MT5_LOGIN")
    settings.mt5_login = int(mt5_login) if mt5_login else None
    settings.mt5_password = os.getenv("MT5_PASSWORD") or None
    settings.mt5_server = os.getenv("MT5_SERVER") or None
    settings.mt5_terminal_path = os.getenv("MT5_TERMINAL_PATH") or None

    for chain in settings.chains.values():
        url = os.getenv(chain.rpc_env)
        if url:
            settings.rpc_urls[chain.rpc_env] = url

    if force_dry_run is not None:
        settings.dry_run = force_dry_run
    else:
        env_dry_run = os.getenv("DRY_RUN")
        if env_dry_run is not None:
            settings.dry_run = env_dry_run.strip().lower() not in {"false", "0", "no"}

    if not settings.dry_run:
        settings.require_live_secrets()

    return settings
