import datetime as dt

from babayaga.agents.news import (
    EconomicCalendar,
    NewsEvent,
    NewsGuard,
    currencies_of,
)
from babayaga.agents.risk import RiskAgent, RiskLimits
from babayaga.kernel.events import Candle, Side


def _ts(iso: str) -> float:
    return dt.datetime.fromisoformat(iso).replace(tzinfo=dt.timezone.utc).timestamp()


def test_currencies_of_splits_pair_and_gold():
    assert currencies_of("EUR/USD") == {"EUR", "USD"}
    assert currencies_of("XAU/USD") == {"XAU", "USD"}


def test_guard_blocks_window_around_high_impact_usd_event():
    ev = NewsEvent(_ts("2026-02-06T13:30:00"), "high", "USD")
    guard = NewsGuard(EconomicCalendar([ev]), minutes_before=30, minutes_after=15)

    # 20 min before a USD event -> blocked for a USD pair.
    blocked, why = guard.blocked("EUR/USD", _ts("2026-02-06T13:10:00"))
    assert blocked and "blackout" in why
    # 10 min after -> still blocked (spike + wide spread cool-off).
    assert guard.blocked("EUR/USD", _ts("2026-02-06T13:40:00"))[0] is True
    # gold reacts to USD news too.
    assert guard.blocked("XAU/USD", _ts("2026-02-06T13:20:00"))[0] is True
    # far away -> clear.
    assert guard.blocked("EUR/USD", _ts("2026-02-06T10:00:00"))[0] is False


def test_guard_ignores_unrelated_currency_and_low_impact():
    usd = NewsEvent(_ts("2026-02-06T13:30:00"), "high", "USD")
    low = NewsEvent(_ts("2026-02-06T13:30:00"), "low", "EUR")
    guard = NewsGuard(EconomicCalendar([usd, low]), min_impact="high")
    # A pair with neither USD nor a high-impact hit -> not blocked.
    assert guard.blocked("EUR/GBP", _ts("2026-02-06T13:25:00"))[0] is False


def test_empty_calendar_never_blocks():
    guard = NewsGuard(EconomicCalendar([]))
    assert guard.blocked("EUR/USD", _ts("2026-02-06T13:30:00"))[0] is False


def test_risk_agent_vetoes_entry_during_news_blackout():
    ev = NewsEvent(_ts("2026-02-06T13:30:00"), "high", "USD")
    guard = NewsGuard(EconomicCalendar([ev]))
    risk = RiskAgent(RiskLimits(min_confidence=0.0), news_guard=guard)
    # Build history whose last bar sits inside the blackout window.
    base = _ts("2026-02-06T13:20:00")
    hist = [
        Candle("EUR/USD", base - (80 - i) * 60, 1.10, 1.1005, 1.0995, 1.10 + i * 1e-4, 0)
        for i in range(80)
    ]
    d = risk.assess("EUR/USD", Side.BUY, 1.0, "t", hist, 100_000, 0)
    assert d.side is Side.FLAT
    assert "news" in d.rationale.lower()


def test_from_csv_loads_and_skips_bad_rows(tmp_path):
    p = tmp_path / "cal.csv"
    p.write_text(
        "date,impact,currency\n"
        "2026-02-06T13:30:00,high,USD\n"
        "not-a-date,high,EUR\n"          # skipped
        "2026-03-01T09:00:00,medium,EUR\n"
    )
    cal = EconomicCalendar.from_csv(p)
    assert len(cal.events) == 2
    assert cal.events[0].currency == "USD"
