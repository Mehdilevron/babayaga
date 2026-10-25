"""Run every strategy variant on every market and print one honest table."""
import datetime
import json
import os
import pickle
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strategy_lab import HEADER, MARKETS, load, row, stats  # noqa: E402
import strategies as S  # noqa: E402

T = datetime.time
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
os.makedirs(CACHE, exist_ok=True)


def data(symbol, interval, rng):
    path = os.path.join(CACHE, "%s_%s_%s.pkl" % (symbol.replace("=", "_"), interval, rng))
    if os.path.exists(path):
        return pickle.load(open(path, "rb"))
    bars = load(symbol, interval, rng)
    pickle.dump(bars, open(path, "wb"))
    time.sleep(0.3)
    return bars


def run(title, variants, interval, rng, markets=MARKETS):
    print("\n" + title)
    print(HEADER)
    per_market = {}
    for name, fn in variants:
        pooled = []
        for sym, (mname, cost) in markets.items():
            res = fn(data(sym, interval, rng), cost)
            pooled += res
            per_market.setdefault(name, {})[mname] = stats(res)
        print(row(name, stats(pooled)))
    return per_market


FIVE = [
    ("ORB 8:30 15m, stop opposite, 1R", lambda b, c: S.orb(b, c, T(8, 30), 15, "opposite", 1.0)),
    ("ORB 8:30 15m, stop opposite, 2R", lambda b, c: S.orb(b, c, T(8, 30), 15, "opposite", 2.0)),
    ("ORB 8:30 15m, stop middle, 1R", lambda b, c: S.orb(b, c, T(8, 30), 15, "mid", 1.0)),
    ("ORB 8:30 15m, stop middle, 2R", lambda b, c: S.orb(b, c, T(8, 30), 15, "mid", 2.0)),
    ("ORB 8:30 30m, stop opposite, 1R", lambda b, c: S.orb(b, c, T(8, 30), 30, "opposite", 1.0)),
    ("ORB 8:30 30m, stop opposite, 2R", lambda b, c: S.orb(b, c, T(8, 30), 30, "opposite", 2.0)),
    ("ORB 9:30 15m, stop opposite, 1R", lambda b, c: S.orb(b, c, T(9, 30), 15, "opposite", 1.0)),
    ("ORB 9:30 15m, stop opposite, 2R", lambda b, c: S.orb(b, c, T(9, 30), 15, "opposite", 2.0)),
    ("S/R fade: yesterday's high/low sweep, 1R", lambda b, c: S.pd_sweep_fade(b, c, 1.0)),
    ("S/R fade: yesterday's high/low sweep, 2R", lambda b, c: S.pd_sweep_fade(b, c, 2.0)),
    ("S/R breakout: yesterday's high/low, 1R", lambda b, c: S.pd_breakout(b, c, 1.0)),
    ("S/R breakout: yesterday's high/low, 2R", lambda b, c: S.pd_breakout(b, c, 2.0)),
    ("ICT model, 2R", lambda b, c: S.ict(b, c, "2R")),
    ("ICT model, 3R", lambda b, c: S.ict(b, c, "3R")),
    ("ICT model, target = opposite liquidity", lambda b, c: S.ict(b, c, "liquidity")),
    ("ICT model + 1h trend filter, 2R", lambda b, c: S.ict(b, c, "2R", use_bias=True)),
]

HOURLY = [
    ("S/R fade on 1h bars, 1R", lambda b, c: S.pd_sweep_fade(b, c, 1.0)),
    ("S/R fade on 1h bars, 2R", lambda b, c: S.pd_sweep_fade(b, c, 2.0)),
    ("S/R breakout on 1h bars, 1R", lambda b, c: S.pd_breakout(b, c, 1.0)),
    ("S/R breakout on 1h bars, 2R", lambda b, c: S.pd_breakout(b, c, 2.0)),
]

if __name__ == "__main__":
    pm = run("5-MINUTE BARS, last ~60 days, 7 markets pooled (costs included)", FIVE, "5m", "60d")
    json.dump({k: v for k, v in pm.items()}, open(os.path.join(CACHE, "per_market.json"), "w"), default=str)
    run("1-HOUR BARS, last ~2.4 years, 7 markets pooled (costs included)", HOURLY, "1h", "730d")
