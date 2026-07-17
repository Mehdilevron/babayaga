"""Honest signal research on YOUR real forex data, with out-of-sample discipline.

    python3 scripts/research.py            # after fetch_history.py has filled data/

Tests several strategy families on the real history in ./data/, splitting time
into IN-SAMPLE (older years) and OUT-OF-SAMPLE (recent years). The only result
that means anything is out-of-sample: a strategy that looks good in-sample but
fails out-of-sample is overfit and worthless. Reports every family honestly —
no cherry-picking.

Families tested:
  * trend      — the current EMA/MACD trend-follower (regime filter, wide target)
  * meanrev    — fade Bollinger extremes (no trend filter, symmetric target)
  * flat       — do nothing (the benchmark every strategy must beat)
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

from babayaga.agents.mean_reversion import MeanReversionAgent
from babayaga.agents.risk import RiskLimits
from babayaga.agents.sentiment import SentimentAgent
from babayaga.agents.technical import TechnicalAgent
from babayaga.backtest import load_csv, run_segment, _year
from babayaga.config import Config
from babayaga.integration.market_data import ReplayFeed
from babayaga.kernel.events import Candle
from babayaga.os import TradingOS

CASH = 500.0
SPLIT_YEAR = 2019  # < SPLIT = in-sample, >= SPLIT = out-of-sample


def _make_os(kind: str, symbols: tuple[str, ...]) -> TradingOS:
    if kind == "trend":
        risk = RiskLimits(min_trend_strength=1.0, atr_stop_mult=1.5, atr_target_mult=6.0)
        specs = [TechnicalAgent(), SentimentAgent()]
    elif kind == "meanrev":
        risk = RiskLimits(min_trend_strength=0.0, atr_stop_mult=2.0,
                          atr_target_mult=2.0, min_confidence=0.1)
        specs = [MeanReversionAgent()]
    else:  # flat
        risk = RiskLimits(min_confidence=2.0)  # nothing ever passes -> no trades
        specs = [TechnicalAgent()]
    os_ = TradingOS(Config(symbols=symbols, starting_cash=CASH, sim_steps=0,
                           slippage=0.00003, flip_cooldown_bars=3, risk=risk))
    os_.coordinator.specialists = specs
    return os_


def _returns_by_year(kind: str, data: dict[str, list[Candle]]) -> dict[int, float]:
    by_year: dict[int, dict[str, list[Candle]]] = {}
    for sym, candles in data.items():
        for c in candles:
            by_year.setdefault(_year(c), {}).setdefault(sym, []).append(c)
    out: dict[int, float] = {}
    for year, seg in sorted(by_year.items()):
        if sum(len(v) for v in seg.values()) < 100:
            continue
        os_ = _make_os(kind, tuple(seg))
        for sym, candles in seg.items():
            os_.attach_feed(sym, ReplayFeed(candles))
        import asyncio
        asyncio.run(os_.run())
        out[year] = os_.performance().total_return_pct
        os_.shutdown()
    return out


def _summary(label: str, rets: list[float]) -> str:
    if not rets:
        return f"{label:26} (no data)"
    prof = sum(1 for r in rets if r > 0)
    return (f"{label:26} median {statistics.median(rets):+6.2f}%  "
            f"mean {statistics.mean(rets):+6.2f}%  profitable {prof}/{len(rets)}")


def main() -> int:
    data_dir = Path(__file__).resolve().parent.parent / "data"
    files = sorted(data_dir.glob("*.csv"))
    if not files:
        print("No data/*.csv found. Run: python3 scripts/fetch_history.py")
        return 1
    data = {}
    for f in files:
        sym, candles = load_csv(f)
        if candles:
            data[sym] = candles
    print(f"Loaded {len(data)} pairs: {', '.join(data)}\n")
    print(f"IN-SAMPLE = years < {SPLIT_YEAR}   OUT-OF-SAMPLE = years >= {SPLIT_YEAR}\n")

    for kind in ("trend", "meanrev", "flat"):
        by_year = _returns_by_year(kind, data)
        ins = [r for y, r in by_year.items() if y < SPLIT_YEAR]
        oos = [r for y, r in by_year.items() if y >= SPLIT_YEAR]
        print(f"### {kind}")
        print("  " + _summary("in-sample", ins))
        print("  " + _summary("OUT-OF-SAMPLE", oos))
        print()

    print("How to read this (no marketing):")
    print("  The ONLY number that matters is a strategy's OUT-OF-SAMPLE median.")
    print("  Positive out-of-sample across many years = a candidate worth a demo.")
    print("  Zero/negative = no edge; do not fund. In-sample gains alone are")
    print("  meaningless — they are what overfitting looks like.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
