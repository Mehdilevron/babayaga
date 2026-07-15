"""Walk-forward backtest on REAL historical data — the honest edge test.

    python -m babayaga.backtest data/*.csv [--cash 10000] [--cooldown 3]

Feeds real daily OHLC history (CSV: Date,Open,High,Low,Close[,Volume]) through
the exact same agents, risk manager and cost-charging paper broker used
everywhere else, one calendar year at a time. Each year runs in a fresh OS
instance, so no state leaks between segments and every year is effectively
out-of-sample (the strategy has no fitted parameters).

How to read the output, honestly:

* A real edge shows up as **most years positive** with a livable worst year —
  across many years and pairs, not one lucky stretch.
* Median yearly return ~0 or negative means **no demonstrated edge**: do not
  fund this strategy; change it and re-test.
* One great year proves nothing. Costs are charged (per-pair spread), but real
  trading still adds swap, news slippage and spread widening on top.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import statistics
from collections import defaultdict
from pathlib import Path

from babayaga.analytics.metrics import PerformanceSummary
from babayaga.config import Config
from babayaga.integration.market_data import ReplayFeed
from babayaga.kernel.events import Candle
from babayaga.os import TradingOS


def symbol_from_filename(path: str | Path) -> str:
    """``data/eurusd_d.csv`` -> ``EUR/USD``; ``xauusd.csv`` -> ``XAU/USD``."""
    stem = Path(path).stem.split("_")[0].upper()
    if len(stem) >= 6:
        return f"{stem[:-3]}/{stem[-3:]}"
    return stem


def load_csv(path: str | Path, symbol: str | None = None) -> tuple[str, list[Candle]]:
    """Load Date,Open,High,Low,Close[,Volume] rows into Candles (sorted)."""
    sym = symbol or symbol_from_filename(path)
    candles: list[Candle] = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            r = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            try:
                ts = dt.datetime.fromisoformat(r["date"]).replace(
                    tzinfo=dt.timezone.utc
                ).timestamp()
                o, h = float(r["open"]), float(r["high"])
                low, c = float(r["low"]), float(r["close"])
            except (KeyError, ValueError):
                continue  # header variants / blank / malformed rows
            vol = 0.0
            try:
                vol = float(r.get("volume") or 0.0)
            except ValueError:
                pass
            candles.append(Candle(sym, ts, o, h, low, c, vol))
    candles.sort(key=lambda cd: cd.timestamp)
    return sym, candles


def _year(c: Candle) -> int:
    return dt.datetime.fromtimestamp(c.timestamp, tz=dt.timezone.utc).year


def run_segment(
    data: dict[str, list[Candle]],
    cash: float,
    cooldown: int,
) -> PerformanceSummary:
    """Run one independent backtest over the given candles per symbol."""
    cfg = Config(
        symbols=tuple(data),
        starting_cash=cash,
        sim_steps=0,
        flip_cooldown_bars=cooldown,
    )
    os_ = TradingOS(cfg)
    for sym, candles in data.items():
        os_.attach_feed(sym, ReplayFeed(candles))
    perf = os_.run_backtest()
    os_.shutdown()
    return perf


def buy_and_hold_pct(data: dict[str, list[Candle]]) -> float:
    """Average per-pair buy-and-hold return over the segment, for reference."""
    rets = [
        (c[-1].close - c[0].close) / c[0].close * 100.0
        for c in data.values()
        if len(c) >= 2 and c[0].close
    ]
    return sum(rets) / len(rets) if rets else 0.0


def walk_forward(
    series: dict[str, list[Candle]],
    cash: float = 10_000.0,
    cooldown: int = 3,
    min_bars: int = 60,
) -> list[tuple[int, PerformanceSummary, float]]:
    """Run one independent segment per calendar year. Returns (year, perf, b&h)."""
    by_year: dict[int, dict[str, list[Candle]]] = defaultdict(dict)
    for sym, candles in series.items():
        buckets: dict[int, list[Candle]] = defaultdict(list)
        for c in candles:
            buckets[_year(c)].append(c)
        for year, chunk in buckets.items():
            if len(chunk) >= min_bars:
                by_year[year][sym] = chunk
    results = []
    for year in sorted(by_year):
        seg = by_year[year]
        perf = run_segment(seg, cash, cooldown)
        results.append((year, perf, buy_and_hold_pct(seg)))
    return results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="babayaga.backtest", description="Walk-forward backtest on real history"
    )
    p.add_argument("files", nargs="+", help="CSV files (Date,Open,High,Low,Close)")
    p.add_argument("--cash", type=float, default=10_000.0)
    p.add_argument("--cooldown", type=int, default=3)
    args = p.parse_args(argv)

    series: dict[str, list[Candle]] = {}
    for f in args.files:
        sym, candles = load_csv(f)
        if candles:
            series[sym] = candles
            print(f"loaded {sym:8} {len(candles):6} bars "
                  f"({dt.datetime.fromtimestamp(candles[0].timestamp, tz=dt.timezone.utc):%Y-%m-%d} "
                  f"→ {dt.datetime.fromtimestamp(candles[-1].timestamp, tz=dt.timezone.utc):%Y-%m-%d})")
        else:
            print(f"WARNING: no usable rows in {f}")
    if not series:
        print("No data loaded.")
        return 1

    print(f"\nWalk-forward, one independent segment per calendar year "
          f"(${args.cash:,.0f} start, cooldown {args.cooldown}):\n")
    print(f"{'year':>6} {'return%':>9} {'maxDD%':>8} {'trades':>7} {'win%':>6} {'buy&hold%':>10}")
    rows = walk_forward(series, cash=args.cash, cooldown=args.cooldown)
    rets = []
    for year, perf, bh in rows:
        rets.append(perf.total_return_pct)
        print(f"{year:>6} {perf.total_return_pct:>+9.2f} {perf.max_drawdown_pct:>8.2f} "
              f"{perf.num_trades:>7} {perf.win_rate_pct:>6.1f} {bh:>+10.2f}")

    if rets:
        pos = sum(1 for r in rets if r > 0)
        print(f"\nyears: {len(rets)}   profitable: {pos}/{len(rets)}"
              f"   median: {statistics.median(rets):+.2f}%"
              f"   mean: {statistics.mean(rets):+.2f}%"
              f"   worst: {min(rets):+.2f}%")
        print("\nHow to read this (no marketing):")
        if statistics.median(rets) <= 0.5:
            print("  ✗ Median yearly return is ~zero or negative: NO edge demonstrated.")
            print("    Do not fund this. Change the strategy and re-run this test.")
        elif pos / len(rets) < 0.6:
            print("  ~ Some good years, but too many losers for confidence. Not fundable yet.")
        else:
            print("  ✓ Consistently positive across years — a *candidate* edge. Now demo it")
            print("    for weeks on real prices before any live money. Real trading still")
            print("    adds swap, news slippage and spread widening on top of these costs.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
