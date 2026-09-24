"""Tests for the walk-forward real-data backtest harness."""

import datetime as dt

from babayaga.backtest import load_csv, run_segment, symbol_from_filename, walk_forward


def _write_csv(tmp_path, name, start_year=2020, days=400, start=1.10, drift=0.0002):
    """Two calendar years of plausible daily OHLC rows."""
    path = tmp_path / name
    lines = ["Date,Open,High,Low,Close,Volume"]
    price = start
    d = dt.date(start_year, 1, 2)
    for i in range(days):
        o = price
        c = price * (1 + drift + (0.001 if i % 7 == 3 else -0.0008 if i % 5 == 2 else 0))
        h, low = max(o, c) * 1.001, min(o, c) * 0.999
        lines.append(f"{d.isoformat()},{o:.5f},{h:.5f},{low:.5f},{c:.5f},0")
        price = c
        d += dt.timedelta(days=1 if d.weekday() < 4 else 3)  # skip weekends
    path.write_text("\n".join(lines))
    return path


def test_symbol_from_filename():
    assert symbol_from_filename("data/eurusd_d.csv") == "EUR/USD"
    assert symbol_from_filename("XAUUSD.csv") == "XAU/USD"


def test_load_csv_parses_and_sorts(tmp_path):
    path = _write_csv(tmp_path, "eurusd_d.csv", days=50)
    sym, candles = load_csv(path)
    assert sym == "EUR/USD"
    assert len(candles) == 50
    assert candles[0].timestamp < candles[-1].timestamp
    assert candles[0].open == 1.10


def test_load_csv_skips_malformed_rows(tmp_path):
    path = tmp_path / "gbpusd_d.csv"
    path.write_text(
        "Date,Open,High,Low,Close\n"
        "2020-01-02,1.30,1.31,1.29,1.305\n"
        "not-a-date,x,y,z,w\n"
        "2020-01-03,1.305,1.32,1.30,1.31\n"
    )
    _, candles = load_csv(path)
    assert len(candles) == 2


def test_run_segment_produces_summary(tmp_path):
    _, candles = load_csv(_write_csv(tmp_path, "eurusd_d.csv", days=120))
    perf = run_segment({"EUR/USD": candles}, cash=10_000.0, cooldown=3)
    assert perf.start_equity == 10_000.0
    assert perf.end_equity > 0


def test_walk_forward_segments_by_year(tmp_path):
    _, candles = load_csv(_write_csv(tmp_path, "eurusd_d.csv", start_year=2020, days=400))
    results = walk_forward({"EUR/USD": candles}, cash=10_000.0, cooldown=3)
    years = [y for y, _, _ in results]
    assert years == sorted(years)
    assert len(years) >= 2  # 400 weekday-ish bars span at least two years
    for _, perf, bh in results:
        assert perf.start_equity == 10_000.0
        assert isinstance(bh, float)
