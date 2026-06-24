"""PairSupervisor tests: spread/volatility pause triggers, hysteresis resume,
and that unsupervised pairs are never touched."""

from __future__ import annotations

from babayaga.config import SupervisorConfig
from babayaga.core.models import Quote
from babayaga.core.supervisor import PairSupervisor


def _quote(venue, bid, ask):
    return Quote(venue=venue, base="PAXG", quote="USDC", bid=bid, ask=ask, fee_bps=0.0)


def _config(**overrides) -> SupervisorConfig:
    defaults = dict(
        enabled=True,
        pairs=["GOLD"],
        window_size=20,
        max_volatility_bps=150.0,
        max_spread_bps=300.0,
        resume_after_clean_ticks=3,
    )
    defaults.update(overrides)
    return SupervisorConfig(**defaults)


def test_unsupervised_pair_is_never_paused():
    sup = PairSupervisor(_config(pairs=["OTHER"]))
    for _ in range(10):
        sup.record("GOLD", [_quote("dex", bid=99, ask=200)])  # absurd spread, but GOLD isn't listed
    assert sup.is_paused("GOLD") is False


def test_disabled_supervisor_never_pauses():
    sup = PairSupervisor(_config(enabled=False))
    for _ in range(10):
        sup.record("GOLD", [_quote("dex", bid=99, ask=200)])
    assert sup.is_paused("GOLD") is False


def test_wide_spread_triggers_pause():
    sup = PairSupervisor(_config(max_spread_bps=300.0))
    assert sup.is_paused("GOLD") is False
    sup.record("GOLD", [_quote("dex", bid=99.0, ask=104.0)])  # ~492bps spread
    assert sup.is_paused("GOLD") is True
    assert "spread" in sup.pause_reason("GOLD")


def test_normal_quotes_never_pause():
    sup = PairSupervisor(_config())
    for i in range(30):
        mid = 100.0 + (i % 2) * 0.01  # tiny, stable wiggle
        sup.record("GOLD", [_quote("dex", bid=mid - 0.05, ask=mid + 0.05)])
    assert sup.is_paused("GOLD") is False


def test_high_volatility_triggers_pause():
    sup = PairSupervisor(_config(max_volatility_bps=50.0, max_spread_bps=1_000_000.0))
    prices = [100.0, 100.0, 130.0, 90.0, 140.0, 80.0]  # wild tick-to-tick swings
    for p in prices:
        sup.record("GOLD", [_quote("dex", bid=p - 0.1, ask=p + 0.1)])
    assert sup.is_paused("GOLD") is True
    assert "volatility" in sup.pause_reason("GOLD")


def test_resumes_after_enough_clean_ticks():
    sup = PairSupervisor(_config(max_spread_bps=300.0, resume_after_clean_ticks=3))
    sup.record("GOLD", [_quote("dex", bid=99.0, ask=104.0)])  # trip the pause
    assert sup.is_paused("GOLD") is True

    sup.record("GOLD", [_quote("dex", bid=99.95, ask=100.05)])
    assert sup.is_paused("GOLD") is True  # 1 clean tick, not enough yet
    sup.record("GOLD", [_quote("dex", bid=99.95, ask=100.05)])
    assert sup.is_paused("GOLD") is True  # 2 clean ticks
    sup.record("GOLD", [_quote("dex", bid=99.95, ask=100.05)])
    assert sup.is_paused("GOLD") is False  # 3rd clean tick resumes it
    assert sup.pause_reason("GOLD") is None


def test_a_fresh_breach_resets_the_clean_tick_counter():
    sup = PairSupervisor(_config(max_spread_bps=300.0, resume_after_clean_ticks=2))
    sup.record("GOLD", [_quote("dex", bid=99.0, ask=104.0)])  # breach
    sup.record("GOLD", [_quote("dex", bid=99.95, ask=100.05)])  # 1 clean tick
    sup.record("GOLD", [_quote("dex", bid=99.0, ask=104.0)])  # breach again, resets counter
    sup.record("GOLD", [_quote("dex", bid=99.95, ask=100.05)])  # 1 clean tick
    assert sup.is_paused("GOLD") is True  # still short of resume_after_clean_ticks=2
