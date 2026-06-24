"""Engine tests using fake VenueRuntime objects - no real RPC/wallet/MT5
connections, just the scan -> detect -> risk-check -> execute wiring."""

from __future__ import annotations

import json

import pytest

from babayaga.config import EngineConfig, PairConfig, PairLeg, RiskConfig, Settings, VenueConfig
from babayaga.core.models import Fill, Quote
from babayaga.core.risk import RiskManager
from babayaga.engine import Engine
from babayaga.factory import VenueRuntime


def _quote(venue, bid, ask, base="WETH", quote="USDC", fee_bps=0.0):
    return Quote(venue=venue, base=base, quote=quote, bid=bid, ask=ask, fee_bps=fee_bps)


def _runtime(name, kind, quote, *, order_error=None, calls=None):
    async def get_quote(base, q, size_base, symbol=None):
        return quote

    async def place_order(order, symbol=None):
        if calls is not None:
            calls.append(order)
        if order_error is not None:
            raise order_error
        return Fill(order=order, filled_size_base=order.size_base, avg_price=order.limit_price, fee_paid_usd=0.0)

    return VenueRuntime(name=name, kind=kind, get_quote=get_quote, place_order=place_order)


def _settings(pairs, venues, *, dry_run, risk=None):
    return Settings(
        dry_run=dry_run,
        engine=EngineConfig(poll_interval_ms=10),
        risk=risk
        or RiskConfig(
            min_profit_bps=0,
            max_position_usd=1_000_000.0,
            max_daily_loss_usd=1_000_000.0,
            max_open_positions=10,
            slippage_bps=0,
        ),
        venues=venues,
        pairs=pairs,
    )


def _two_leg_pair(name="TEST", hedge=False, base="WETH", quote="USDC", symbol_b=None):
    legs = [PairLeg(venue="cheap"), PairLeg(venue="rich", symbol=symbol_b)]
    return PairConfig(name=name, base=base, quote=quote, hedge=hedge, size_base=1.0, legs=legs)


@pytest.mark.asyncio
async def test_dry_run_round_trip_records_a_profitable_trade(tmp_path):
    cheap = _quote("cheap", bid=99, ask=100)
    rich = _quote("rich", bid=110, ask=111)
    runtimes = {
        "cheap": _runtime("cheap", "evm_v2_router", cheap),
        "rich": _runtime("rich", "evm_v2_router", rich),
    }
    venues = {
        "cheap": VenueConfig(kind="evm_v2_router"),
        "rich": VenueConfig(kind="evm_v2_router"),
    }
    settings = _settings([_two_leg_pair()], venues, dry_run=True)
    risk = RiskManager(settings.risk, kill_switch_path=tmp_path / "kill_switch.flag")
    engine = Engine(settings, runtimes, risk, trades_log_path=tmp_path / "trades.jsonl")

    await engine.run_once()

    assert risk.state.open_positions == 0
    assert risk.state.realized_pnl_today_usd > 0
    lines = (tmp_path / "trades.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["dry_run"] is True
    assert record["realized_pnl_usd"] > 0


@pytest.mark.asyncio
async def test_unprofitable_opportunity_is_skipped_and_never_executed(tmp_path):
    cheap = _quote("cheap", bid=99, ask=100)
    rich = _quote("rich", bid=100.05, ask=100.1)  # spread too thin
    runtimes = {
        "cheap": _runtime("cheap", "evm_v2_router", cheap),
        "rich": _runtime("rich", "evm_v2_router", rich),
    }
    venues = {"cheap": VenueConfig(kind="evm_v2_router"), "rich": VenueConfig(kind="evm_v2_router")}
    risk_cfg = RiskConfig(
        min_profit_bps=1000.0,
        max_position_usd=1_000_000.0,
        max_daily_loss_usd=1_000_000.0,
        max_open_positions=10,
        slippage_bps=0,
    )
    settings = _settings([_two_leg_pair()], venues, dry_run=True, risk=risk_cfg)
    risk = RiskManager(settings.risk, kill_switch_path=tmp_path / "kill_switch.flag")
    engine = Engine(settings, runtimes, risk, trades_log_path=tmp_path / "trades.jsonl")

    await engine.run_once()

    assert risk.state.open_positions == 0
    assert risk.state.realized_pnl_today_usd == 0.0
    assert not (tmp_path / "trades.jsonl").exists()


@pytest.mark.asyncio
async def test_buy_leg_failure_opens_no_position(tmp_path):
    cheap = _quote("cheap", bid=99, ask=100)
    rich = _quote("rich", bid=110, ask=111)
    calls = []
    runtimes = {
        "cheap": _runtime("cheap", "evm_v2_router", cheap, order_error=RuntimeError("buy boom"), calls=calls),
        "rich": _runtime("rich", "evm_v2_router", rich, calls=calls),
    }
    venues = {"cheap": VenueConfig(kind="evm_v2_router"), "rich": VenueConfig(kind="evm_v2_router")}
    settings = _settings([_two_leg_pair()], venues, dry_run=False)
    risk = RiskManager(settings.risk, kill_switch_path=tmp_path / "kill_switch.flag")
    engine = Engine(settings, runtimes, risk, trades_log_path=tmp_path / "trades.jsonl")

    await engine.run_once()

    assert len(calls) == 1  # only the buy leg was ever attempted
    assert risk.state.open_positions == 0
    assert risk.is_halted() is False
    assert not (tmp_path / "trades.jsonl").exists()


@pytest.mark.asyncio
async def test_sell_leg_failure_after_buy_fills_trips_kill_switch(tmp_path):
    cheap = _quote("cheap", bid=99, ask=100)
    rich = _quote("rich", bid=110, ask=111)
    calls = []
    runtimes = {
        "cheap": _runtime("cheap", "evm_v2_router", cheap, calls=calls),
        "rich": _runtime("rich", "evm_v2_router", rich, order_error=RuntimeError("sell boom"), calls=calls),
    }
    venues = {"cheap": VenueConfig(kind="evm_v2_router"), "rich": VenueConfig(kind="evm_v2_router")}
    settings = _settings([_two_leg_pair()], venues, dry_run=False)
    risk = RiskManager(settings.risk, kill_switch_path=tmp_path / "kill_switch.flag")
    engine = Engine(settings, runtimes, risk, trades_log_path=tmp_path / "trades.jsonl")

    await engine.run_once()

    assert len(calls) == 2  # buy succeeded, sell was attempted and failed
    assert risk.state.open_positions == 1  # left open - unhedged, must not be silently closed
    assert risk.is_halted() is True
    assert risk.state.trip_reason == "unhedged_leg_failure"
    assert not (tmp_path / "trades.jsonl").exists()


@pytest.mark.asyncio
async def test_halted_engine_skips_processing_pairs(tmp_path):
    calls = []
    cheap = _quote("cheap", bid=99, ask=100)
    rich = _quote("rich", bid=110, ask=111)
    runtimes = {
        "cheap": _runtime("cheap", "evm_v2_router", cheap, calls=calls),
        "rich": _runtime("rich", "evm_v2_router", rich, calls=calls),
    }
    venues = {"cheap": VenueConfig(kind="evm_v2_router"), "rich": VenueConfig(kind="evm_v2_router")}
    settings = _settings([_two_leg_pair()], venues, dry_run=False)
    kill_switch_path = tmp_path / "kill_switch.flag"
    kill_switch_path.touch()
    risk = RiskManager(settings.risk, kill_switch_path=kill_switch_path)
    engine = Engine(settings, runtimes, risk, trades_log_path=tmp_path / "trades.jsonl")

    await engine.run(iterations=1)

    assert calls == []  # never even quoted, let alone executed


@pytest.mark.asyncio
async def test_hedge_leg_mirrors_dex_side_when_mt5_is_the_sell_leg(tmp_path):
    dex_quote = _quote("dex", bid=99, ask=100, base="PAXG", quote="USDC")
    mt5_quote = _quote("mt5_hedge", bid=110, ask=111, base="PAXG", quote="USDC")
    calls = []
    runtimes = {
        "dex": _runtime("dex", "evm_v3_quoter", dex_quote, calls=calls),
        "mt5_hedge": _runtime("mt5_hedge", "mt5", mt5_quote, calls=calls),
    }
    venues = {"dex": VenueConfig(kind="evm_v3_quoter"), "mt5_hedge": VenueConfig(kind="mt5")}
    pair = PairConfig(
        name="HEDGE",
        base="PAXG",
        quote="USDC",
        hedge=True,
        size_base=1.0,
        legs=[PairLeg(venue="dex"), PairLeg(venue="mt5_hedge", symbol="XAUUSD")],
    )
    settings = _settings([pair], venues, dry_run=False)
    risk = RiskManager(settings.risk, kill_switch_path=tmp_path / "kill_switch.flag")
    engine = Engine(settings, runtimes, risk, trades_log_path=tmp_path / "trades.jsonl")

    await engine.run_once()

    assert len(calls) == 2
    by_venue = {order.venue: order for order in calls}
    # dex is the cheap/buy leg here, so it keeps its natural BUY side - and the
    # mt5 leg (the sell side of the permutation) is overridden to mirror it
    # rather than keeping its own natural SELL, since Mt5Executor flips
    # whatever side it's given to produce the real offsetting direction.
    assert by_venue["dex"].side.value == "buy"
    assert by_venue["mt5_hedge"].side.value == "buy"


@pytest.mark.asyncio
async def test_hedge_leg_mirrors_dex_side_when_mt5_is_the_buy_leg(tmp_path):
    dex_quote = _quote("dex", bid=110, ask=111, base="PAXG", quote="USDC")
    mt5_quote = _quote("mt5_hedge", bid=99, ask=100, base="PAXG", quote="USDC")
    calls = []
    runtimes = {
        "dex": _runtime("dex", "evm_v3_quoter", dex_quote, calls=calls),
        "mt5_hedge": _runtime("mt5_hedge", "mt5", mt5_quote, calls=calls),
    }
    venues = {"dex": VenueConfig(kind="evm_v3_quoter"), "mt5_hedge": VenueConfig(kind="mt5")}
    pair = PairConfig(
        name="HEDGE",
        base="PAXG",
        quote="USDC",
        hedge=True,
        size_base=1.0,
        legs=[PairLeg(venue="dex"), PairLeg(venue="mt5_hedge", symbol="XAUUSD")],
    )
    settings = _settings([pair], venues, dry_run=False)
    risk = RiskManager(settings.risk, kill_switch_path=tmp_path / "kill_switch.flag")
    engine = Engine(settings, runtimes, risk, trades_log_path=tmp_path / "trades.jsonl")

    await engine.run_once()

    assert len(calls) == 2
    by_venue = {order.venue: order for order in calls}
    # Now mt5 is the cheap/buy leg of the permutation and dex is the sell leg -
    # dex keeps its natural SELL side, and mt5 mirrors it instead of its own
    # natural BUY.
    assert by_venue["dex"].side.value == "sell"
    assert by_venue["mt5_hedge"].side.value == "sell"
