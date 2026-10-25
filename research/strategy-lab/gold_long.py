"""Gold (spot XAUUSD) on 2 years of Dukascopy 1-minute data, as 5-minute bars:
ORB at 8:30 New York, yesterday's high/low, and the coded ICT model.

    python3 gold_long.py [years]   # default 2
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dukascopy  # noqa: E402
import strategies as S  # noqa: E402
from strategy_lab import HEADER, row, stats  # noqa: E402

T = datetime.time
COST = 0.30  # spot gold spread + commission, dollars per ounce per trade

VARIANTS = [
    ("ORB 8:30 15m, stop opposite, 1R", lambda b: S.orb(b, COST, T(8, 30), 15, "opposite", 1.0)),
    ("ORB 8:30 15m, stop opposite, 2R", lambda b: S.orb(b, COST, T(8, 30), 15, "opposite", 2.0)),
    ("ORB 8:30 30m, stop opposite, 1R", lambda b: S.orb(b, COST, T(8, 30), 30, "opposite", 1.0)),
    ("ORB 8:30 30m, stop opposite, 2R", lambda b: S.orb(b, COST, T(8, 30), 30, "opposite", 2.0)),
    ("ORB 8:30 15m, stop middle, 1R", lambda b: S.orb(b, COST, T(8, 30), 15, "mid", 1.0)),
    ("S/R fade: yesterday's high/low sweep, 1R", lambda b: S.pd_sweep_fade(b, COST, 1.0)),
    ("S/R fade: yesterday's high/low sweep, 2R", lambda b: S.pd_sweep_fade(b, COST, 2.0)),
    ("S/R breakout: yesterday's high/low, 2R", lambda b: S.pd_breakout(b, COST, 2.0)),
    ("ICT model, 1R", lambda b: S.ict(b, COST, "1R")),
    ("ICT model, 2R", lambda b: S.ict(b, COST, "2R")),
    ("ICT model, 3R", lambda b: S.ict(b, COST, "3R")),
    ("ICT model, target = opposite liquidity", lambda b: S.ict(b, COST, "liquidity")),
    ("ICT model + 1h trend filter, 2R", lambda b: S.ict(b, COST, "2R", use_bias=True)),
]


def main():
    years = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0
    end = datetime.date.today() - datetime.timedelta(days=1)
    start = end - datetime.timedelta(days=int(365.25 * years))
    rows = dukascopy.minutes("XAUUSD", start, end)
    bars = dukascopy.to5m(rows)
    print("XAUUSD %s to %s: %d one-minute candles -> %d five-minute bars (cost $%.2f a trade)"
          % (start, end, len(rows), len(bars), COST))
    print(HEADER)
    for name, fn in VARIANTS:
        print(row(name, stats(fn(bars))))


if __name__ == "__main__":
    main()
