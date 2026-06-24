"""build_runtimes wiring tests: which venues get built, which secrets are
required when, and the fail-fast validation paths - all without touching a
real RPC, wallet, or MT5 terminal."""

from __future__ import annotations

import sys
import time
import types

import pytest

from babayaga.config import ChainConfig, PairConfig, PairLeg, RiskConfig, Settings, VenueConfig
from babayaga.core.models import Order, Side
from babayaga.factory import build_runtimes


def _risk() -> RiskConfig:
    return RiskConfig(
        min_profit_bps=0,
        max_position_usd=1_000_000.0,
        max_daily_loss_usd=1_000_000.0,
        max_open_positions=10,
        slippage_bps=0,
    )


def _settings(*, venues, pairs, dry_run=True, chains=None, rpc_urls=None, **secrets) -> Settings:
    return Settings(
        dry_run=dry_run,
        risk=_risk(),
        chains=chains or {},
        venues=venues,
        pairs=pairs,
        rpc_urls=rpc_urls or {},
        **secrets,
    )


def _order(venue: str) -> Order:
    return Order(venue=venue, side=Side.BUY, base="WETH", quote="USDC", size_base=1.0, limit_price=100.0)


ROUTER_ADDRESS = "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"
QUOTER_ADDRESS = "0x61fFE014bA17989E743c5F6cB21bF9697530B21e"


def test_only_venues_referenced_by_pairs_are_built():
    venues = {
        "used": VenueConfig(kind="evm_v2_router", chain="eth", router_address=ROUTER_ADDRESS),
        "unused": VenueConfig(kind="evm_v2_router", chain="eth", router_address=ROUTER_ADDRESS),
    }
    chains = {"eth": ChainConfig(rpc_env="ETH_RPC")}
    pairs = [PairConfig(name="P", base="WETH", quote="USDC", legs=[PairLeg(venue="used")])]
    settings = _settings(venues=venues, pairs=pairs, chains=chains, rpc_urls={"ETH_RPC": "http://localhost:1"})

    runtimes = build_runtimes(settings)

    assert set(runtimes.keys()) == {"used"}


@pytest.mark.asyncio
async def test_dry_run_builds_without_private_key_but_place_order_then_fails():
    venues = {"v": VenueConfig(kind="evm_v2_router", chain="eth", router_address=ROUTER_ADDRESS)}
    chains = {"eth": ChainConfig(rpc_env="ETH_RPC")}
    pairs = [PairConfig(name="P", base="WETH", quote="USDC", legs=[PairLeg(venue="v")])]
    settings = _settings(
        venues=venues, pairs=pairs, chains=chains, dry_run=True, rpc_urls={"ETH_RPC": "http://localhost:1"}
    )

    runtimes = build_runtimes(settings)  # no EVM_PRIVATE_KEY set anywhere - must not raise in dry-run

    with pytest.raises(RuntimeError, match="no executor was constructed"):
        await runtimes["v"].place_order(_order("v"))


def test_evm_v2_router_missing_router_address_raises_even_in_dry_run():
    venues = {"v": VenueConfig(kind="evm_v2_router", chain="eth")}
    chains = {"eth": ChainConfig(rpc_env="ETH_RPC")}
    pairs = [PairConfig(name="P", base="WETH", quote="USDC", legs=[PairLeg(venue="v")])]
    settings = _settings(
        venues=venues, pairs=pairs, chains=chains, dry_run=True, rpc_urls={"ETH_RPC": "http://localhost:1"}
    )

    with pytest.raises(ValueError, match="router_address"):
        build_runtimes(settings)


def test_evm_v3_quoter_live_mode_requires_router_address_but_dry_run_does_not():
    venues = {"v": VenueConfig(kind="evm_v3_quoter", chain="eth", quoter_address=QUOTER_ADDRESS)}
    chains = {"eth": ChainConfig(rpc_env="ETH_RPC")}
    pairs = [PairConfig(name="P", base="WETH", quote="USDC", legs=[PairLeg(venue="v")])]
    rpc_urls = {"ETH_RPC": "http://localhost:1"}

    dry_settings = _settings(venues=venues, pairs=pairs, chains=chains, dry_run=True, rpc_urls=rpc_urls)
    build_runtimes(dry_settings)  # quoting needs no router_address - must not raise

    live_settings = _settings(
        venues=venues, pairs=pairs, chains=chains, dry_run=False, rpc_urls=rpc_urls, evm_private_key="0xabc"
    )
    with pytest.raises(ValueError, match="router_address"):
        build_runtimes(live_settings)


def test_missing_rpc_url_raises():
    venues = {"v": VenueConfig(kind="evm_v2_router", chain="eth", router_address="0xabc")}
    chains = {"eth": ChainConfig(rpc_env="ETH_RPC")}
    pairs = [PairConfig(name="P", base="WETH", quote="USDC", legs=[PairLeg(venue="v")])]
    settings = _settings(venues=venues, pairs=pairs, chains=chains, rpc_urls={})

    with pytest.raises(ValueError, match="ETH_RPC"):
        build_runtimes(settings)


def test_unknown_venue_kind_raises():
    venues = {"v": VenueConfig(kind="bogus")}
    pairs = [PairConfig(name="P", base="WETH", quote="USDC", legs=[PairLeg(venue="v")])]
    settings = _settings(venues=venues, pairs=pairs)

    with pytest.raises(ValueError, match="unknown kind"):
        build_runtimes(settings)


def test_mt5_venue_requires_credentials_even_in_dry_run():
    venues = {"v": VenueConfig(kind="mt5")}
    pairs = [PairConfig(name="P", base="PAXG", quote="USDC", legs=[PairLeg(venue="v", symbol="XAUUSD")])]
    settings = _settings(venues=venues, pairs=pairs, dry_run=True)

    with pytest.raises(ValueError, match="MT5_LOGIN"):
        build_runtimes(settings)


@pytest.mark.asyncio
async def test_mt5_runtime_requires_symbol_for_quote():
    # The feed is built unconditionally (even in dry-run), and the symbol
    # check happens before ever touching the MetaTrader5 module, so this
    # exercises the real wrapper without needing the optional dependency.
    venues = {"v": VenueConfig(kind="mt5")}
    pairs = [PairConfig(name="P", base="PAXG", quote="USDC", legs=[PairLeg(venue="v", symbol="XAUUSD")])]
    settings = _settings(
        venues=venues, pairs=pairs, dry_run=True, mt5_login=1, mt5_password="pw", mt5_server="srv"
    )

    runtimes = build_runtimes(settings)

    with pytest.raises(ValueError, match="symbol"):
        await runtimes["v"].get_quote("PAXG", "USDC", 1.0, None)


@pytest.mark.asyncio
async def test_mt5_runtime_requires_symbol_for_order():
    # Mt5Executor.__init__ never touches the MetaTrader5 module (only
    # execute() does), so building it live-mode is still safe here, and lets
    # us reach the symbol check past the "no executor" guard.
    venues = {"v": VenueConfig(kind="mt5")}
    pairs = [PairConfig(name="P", base="PAXG", quote="USDC", legs=[PairLeg(venue="v", symbol="XAUUSD")])]
    settings = _settings(
        venues=venues, pairs=pairs, dry_run=False, mt5_login=1, mt5_password="pw", mt5_server="srv"
    )

    runtimes = build_runtimes(settings)

    with pytest.raises(ValueError, match="symbol"):
        await runtimes["v"].place_order(_order("v"), None)


def test_no_live_gas_pricing_without_chain_native_token_config():
    venues = {"v": VenueConfig(kind="evm_v2_router", chain="eth", router_address=ROUTER_ADDRESS)}
    chains = {"eth": ChainConfig(rpc_env="ETH_RPC")}  # native_token/native_price_venue unset
    pairs = [PairConfig(name="P", base="WETH", quote="USDC", legs=[PairLeg(venue="v")])]
    settings = _settings(venues=venues, pairs=pairs, chains=chains, rpc_urls={"ETH_RPC": "http://localhost:1"})

    runtimes = build_runtimes(settings)

    assert runtimes["v"].estimate_gas_cost_usd is None


def test_live_gas_pricer_attached_when_chain_configures_native_token_and_price_venue():
    venues = {
        "v": VenueConfig(kind="evm_v2_router", chain="eth", router_address=ROUTER_ADDRESS),
        "pricer": VenueConfig(kind="evm_v2_router", chain="eth", router_address=ROUTER_ADDRESS),
    }
    chains = {"eth": ChainConfig(rpc_env="ETH_RPC", native_token="WETH", native_price_venue="pricer")}
    pairs = [PairConfig(name="P", base="WETH", quote="USDC", legs=[PairLeg(venue="v")])]
    settings = _settings(venues=venues, pairs=pairs, chains=chains, rpc_urls={"ETH_RPC": "http://localhost:1"})

    runtimes = build_runtimes(settings)

    assert callable(runtimes["v"].estimate_gas_cost_usd)
    # "pricer" itself isn't referenced by any pair leg, so it must not be built
    assert "pricer" not in runtimes


def test_native_price_venue_must_be_an_evm_quoting_venue():
    venues = {
        "v": VenueConfig(kind="evm_v2_router", chain="eth", router_address=ROUTER_ADDRESS),
        "pricer": VenueConfig(kind="jupiter_aggregator"),
    }
    chains = {"eth": ChainConfig(rpc_env="ETH_RPC", native_token="WETH", native_price_venue="pricer")}
    pairs = [PairConfig(name="P", base="WETH", quote="USDC", legs=[PairLeg(venue="v")])]
    settings = _settings(venues=venues, pairs=pairs, chains=chains, rpc_urls={"ETH_RPC": "http://localhost:1"})

    with pytest.raises(ValueError, match="evm_v2_router or evm_v3_quoter"):
        build_runtimes(settings)


@pytest.mark.asyncio
async def test_mt5_venue_honors_configured_stale_quote_after_s(monkeypatch):
    module = types.ModuleType("MetaTrader5")
    module.SYMBOL_TRADE_MODE_DISABLED = 0
    module.initialize = lambda **kwargs: True
    module.symbol_select = lambda symbol, enable: True
    module.symbol_info = lambda symbol: types.SimpleNamespace(trade_mode=1)
    module.symbol_info_tick = lambda symbol: types.SimpleNamespace(bid=100.0, ask=100.5, time=time.time() - 10)
    module.last_error = lambda: (0, "no error")
    monkeypatch.setitem(sys.modules, "MetaTrader5", module)

    venues = {"v": VenueConfig(kind="mt5", stale_quote_after_s=5.0)}  # tighter than the 10s-old tick above
    pairs = [PairConfig(name="P", base="PAXG", quote="USDC", legs=[PairLeg(venue="v", symbol="XAUUSD")])]
    settings = _settings(venues=venues, pairs=pairs, dry_run=True, mt5_login=1, mt5_password="pw", mt5_server="srv")

    runtimes = build_runtimes(settings)

    with pytest.raises(RuntimeError, match="stale"):
        await runtimes["v"].get_quote("PAXG", "USDC", 1.0, "XAUUSD")
