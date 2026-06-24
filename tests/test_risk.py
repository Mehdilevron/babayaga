"""RiskManager tests: limit enforcement, the file-based kill switch, and the
daily-loss trip/rollover semantics."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from babayaga.config import RiskConfig
from babayaga.core.models import ArbOpportunity, Quote
from babayaga.core.risk import RiskManager


def _risk_config(**overrides) -> RiskConfig:
    defaults = dict(
        min_profit_bps=25.0,
        max_position_usd=250.0,
        max_daily_loss_usd=200.0,
        max_open_positions=3,
        slippage_bps=50.0,
    )
    defaults.update(overrides)
    return RiskConfig(**defaults)


def _opportunity(net_profit_bps: float = 50.0, ask: float = 100.0, size_base: float = 1.0) -> ArbOpportunity:
    buy_quote = Quote(venue="cheap", base="WETH", quote="USDC", bid=ask - 1, ask=ask, fee_bps=0.0)
    sell_quote = Quote(venue="rich", base="WETH", quote="USDC", bid=ask * 1.01, ask=ask * 1.02, fee_bps=0.0)
    return ArbOpportunity(
        pair_name="PAIR",
        buy_quote=buy_quote,
        sell_quote=sell_quote,
        size_base=size_base,
        gross_spread_bps=net_profit_bps,
        est_cost_bps=0.0,
        net_profit_bps=net_profit_bps,
        est_net_profit_usd=net_profit_bps / 10_000 * size_base * ask,
    )


def test_evaluate_allows_a_clean_profitable_opportunity():
    rm = RiskManager(_risk_config())
    ok, reason = rm.evaluate(_opportunity(net_profit_bps=50.0))
    assert ok is True
    assert reason == "ok"


def test_evaluate_blocks_below_profit_floor():
    rm = RiskManager(_risk_config(min_profit_bps=25.0))
    ok, reason = rm.evaluate(_opportunity(net_profit_bps=10.0))
    assert ok is False
    assert "below floor" in reason


def test_evaluate_blocks_over_max_position():
    rm = RiskManager(_risk_config(max_position_usd=50.0))
    ok, reason = rm.evaluate(_opportunity(ask=100.0, size_base=1.0))  # $100 notional > $50 cap
    assert ok is False
    assert "exceeds max_position_usd" in reason


def test_evaluate_blocks_when_open_positions_at_max():
    rm = RiskManager(_risk_config(max_open_positions=1))
    rm.on_position_opened()
    ok, reason = rm.evaluate(_opportunity())
    assert ok is False
    assert "open positions" in reason


def test_evaluate_blocks_when_daily_loss_reached():
    rm = RiskManager(_risk_config(max_daily_loss_usd=100.0))
    rm.state.realized_pnl_today_usd = -100.0
    ok, reason = rm.evaluate(_opportunity())
    assert ok is False
    assert "max_daily_loss_usd" in reason


def test_max_size_within_limits_clamps_down(tmp_path):
    rm = RiskManager(_risk_config(max_position_usd=50.0))
    opp = _opportunity(ask=100.0, size_base=1.0)
    clamped = rm.max_size_within_limits(opp)
    assert clamped == pytest.approx(0.5)


def test_max_size_within_limits_never_increases_size():
    rm = RiskManager(_risk_config(max_position_usd=1000.0))
    opp = _opportunity(ask=100.0, size_base=1.0)
    assert rm.max_size_within_limits(opp) == 1.0


def test_kill_switch_file_halts_trading(tmp_path):
    flag = tmp_path / "kill_switch.flag"
    rm = RiskManager(_risk_config(), kill_switch_path=flag)
    assert rm.is_halted() is False

    flag.touch()
    assert rm.is_halted() is True
    ok, reason = rm.evaluate(_opportunity())
    assert ok is False
    assert "halted" in reason


def test_manual_trip_halts_trading(tmp_path):
    rm = RiskManager(_risk_config(), kill_switch_path=tmp_path / "kill_switch.flag")
    rm.trip("unhedged_leg_failure")
    assert rm.is_halted() is True
    ok, reason = rm.evaluate(_opportunity())
    assert ok is False
    assert "unhedged_leg_failure" in reason


def test_daily_loss_trip_clears_on_day_rollover(tmp_path):
    rm = RiskManager(_risk_config(max_daily_loss_usd=100.0), kill_switch_path=tmp_path / "kill_switch.flag")
    rm.state.realized_pnl_today_usd = -150.0
    rm.state.kill_switch_tripped = True
    rm.state.trip_reason = "max_daily_loss"

    # Simulate a day boundary by backdating tracked_day - the same trick
    # _roll_day_if_needed uses date.today() internally to detect rollover.
    rm.state.tracked_day = date.today() - timedelta(days=1)

    assert rm.is_halted() is False
    assert rm.state.realized_pnl_today_usd == 0.0


def test_kill_switch_file_trip_persists_after_file_removed(tmp_path):
    flag = tmp_path / "kill_switch.flag"
    rm = RiskManager(_risk_config(), kill_switch_path=flag)
    flag.touch()
    assert rm.is_halted() is True

    flag.unlink()
    # A file-based trip does not self-clear - only a fresh process (or a day
    # rollover, which doesn't apply to this trip reason) resets it.
    assert rm.is_halted() is True


def test_on_position_opened_and_closed_track_count():
    rm = RiskManager(_risk_config())
    assert rm.state.open_positions == 0
    rm.on_position_opened()
    rm.on_position_opened()
    assert rm.state.open_positions == 2
    rm.on_position_closed()
    assert rm.state.open_positions == 1
    rm.on_position_closed()
    rm.on_position_closed()  # never goes negative
    assert rm.state.open_positions == 0
