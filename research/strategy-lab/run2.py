"""Engine check, trend-filtered and small-target variants, gold on its own,
and a classic daily high-win-rate strategy on long history."""
import datetime
import json
import os
import random
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strategy_lab import HEADER, MARKETS, UA, by_session, row, stats, trade  # noqa: E402
from run import data, run  # noqa: E402
import strategies as S  # noqa: E402

T = datetime.time


def random_control(bars5, cost, seed=7):
    """Random side at 9:00 New York, stop/target = 1x the 8:30-8:45 range. If the
    engine is fair this loses about the cost and nothing more."""
    rnd = random.Random(seed)
    days = by_session(bars5)
    flat, index = S.flat(days)
    out = []
    for d, bs in days:
        rng = [b for b in bs if T(8, 30) <= b[0].time() < T(8, 45)]
        k = next((i for i, b in enumerate(bs) if b[0].time() == T(9, 0)), None)
        if len(rng) != 3 or k is None:
            continue
        size = max(b[2] for b in rng) - min(b[3] for b in rng)
        j = index[d] + k
        fill = flat[j][1]
        side = rnd.choice(("BUY", "SELL"))
        stop = fill - size if side == "BUY" else fill + size
        tgt = fill + size if side == "BUY" else fill - size
        r = trade(flat, j, side, fill, stop, tgt, T(12, 0), cost)
        if r is not None:
            out.append((flat[j][0], r))
    return out


def daily_trend(bars5):
    """{session date: +1 / -1}: yesterday's close vs the 20-day average of closes."""
    closes, out = [], {}
    for d, bs in by_session(bars5):
        if len(closes) >= 20:
            out[d] = 1 if closes[-1] > sum(closes[-20:]) / 20 else -1
        closes.append(bs[-1][4])
    return out


def with_trend(fn):
    def wrapped(bars5, cost):
        tr = daily_trend(bars5)
        res = fn(bars5, cost, sides=True)
        return [(t, r) for t, r, side, d in res if tr.get(d) == (1 if side == "BUY" else -1)]
    return wrapped


def orb_sides(bars5, cost, target_r=1.0, sides=False, minutes=30):
    """S.orb, but also returning side and session so a filter can be applied."""
    days = by_session(bars5)
    flat, index = S.flat(days)
    end = (datetime.datetime(2000, 1, 1, 8, 30) + datetime.timedelta(minutes=minutes)).time()
    out = []
    for d, bs in days:
        rng = [b for b in bs if T(8, 30) <= b[0].time() < end]
        if len(rng) != minutes // 5:
            continue
        hi, lo = max(b[2] for b in rng), min(b[3] for b in rng)
        for k in range(len(bs) - 1):
            t = bs[k][0].time()
            if t < end or t >= T(12, 0):
                continue
            c = bs[k][4]
            side = "BUY" if c > hi else "SELL" if c < lo else None
            if not side:
                continue
            j = index[d] + k + 1
            fill = flat[j][1]
            stop = lo if side == "BUY" else hi
            risk = (fill - stop) if side == "BUY" else (stop - fill)
            if risk > 0:
                tgt = fill + target_r * risk if side == "BUY" else fill - target_r * risk
                r = trade(flat, j, side, fill, stop, tgt, T(12, 0), cost)
                if r is not None:
                    out.append((flat[j][0], r, side, d) if sides else (flat[j][0], r))
            break
    return out


# ---------------------------------------------------------------- daily RSI(2)

def daily(symbol):
    # range=max comes back as monthly bars; an explicit window keeps them daily
    url = ("https://query2.finance.yahoo.com/v8/finance/chart/%s?period1=946684800&period2=%d&interval=1d"
           % (symbol, int(datetime.datetime.now().timestamp())))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    res = json.loads(urllib.request.urlopen(req, timeout=60).read())["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(res["timestamp"]):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None not in (o, h, l, c):
            out.append((datetime.date.fromtimestamp(t), o, h, l, c))
    return out


def rsi2_strategy(b, cost_pct=0.0005, entry_level=10, start=datetime.date(2005, 1, 1)):
    """Connors-style: buy at the close when close > 200-day average and RSI(2)
    < entry_level; sell at the close when close > 5-day average. No stop.
    R here = % return of the trade (there is no stop to measure risk by)."""
    c = [x[4] for x in b]
    out, pos, i = [], None, 200
    ag = al = None
    rsi = [None] * len(c)
    for k in range(1, len(c)):
        g, l = max(c[k] - c[k - 1], 0), max(c[k - 1] - c[k], 0)
        ag = g if ag is None else (ag + g) / 2
        al = l if al is None else (al + l) / 2
        rsi[k] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for k in range(200, len(c)):
        if b[k][0] < start:
            continue
        sma200 = sum(c[k - 199:k + 1]) / 200
        sma5 = sum(c[k - 4:k + 1]) / 5
        if pos is None and c[k] > sma200 and rsi[k] < entry_level:
            pos = (b[k][0], c[k])
        elif pos is not None and c[k] > sma5:
            ret = (c[k] / pos[1] - 1) - cost_pct
            out.append((pos[0], b[k][0], ret))
            pos = None
    return out


def rsi2_report(symbols):
    print("\nDAILY RSI(2) PULLBACK, 2005-2026, long only (costs 0.05% a trade)")
    print("%-8s %5s %6s %8s %8s %9s %9s %8s %s" % ("market", "n", "win", "avg", "worst", "total", "maxDD", "days", "2005-15 / 2016-26 avg"))
    for s in symbols:
        try:
            tr = rsi2_strategy(daily(s))
        except Exception as e:
            print(s, "no data", e)
            continue
        rets = [r for _, _, r in tr]
        if not rets:
            continue
        eq = peak = 1.0
        dd = 0.0
        for r in rets:
            eq *= 1 + r
            peak = max(peak, eq)
            dd = max(dd, 1 - eq / peak)
        a = [r for e, _, r in tr if e.year <= 2015]
        z = [r for e, _, r in tr if e.year > 2015]
        held = sum((x - e).days for e, x, _ in tr) / len(tr)
        avg = lambda xs: 100 * sum(xs) / len(xs) if xs else 0
        print("%-8s %5d %5.0f%% %+7.2f%% %+7.1f%% %+8.0f%% %8.0f%% %8.1f   %+.2f%% / %+.2f%%"
              % (s, len(rets), 100 * sum(1 for r in rets if r > 0) / len(rets), avg(rets),
                 100 * min(rets), 100 * (eq - 1), 100 * dd, held, avg(a), avg(z)))


if __name__ == "__main__":
    run("ENGINE CHECK: random entries (should lose about the cost, ~-0.05R)",
        [("random side at 9:00, 1R", random_control)], "5m", "60d")
    run("HIGHER WIN RATE: smaller targets, and only with the daily trend",
        [("ORB 8:30 30m, 0.5R", lambda b, c: orb_sides(b, c, 0.5)),
         ("ORB 8:30 30m, 1R, with daily trend only", with_trend(lambda b, c, sides: orb_sides(b, c, 1.0, sides))),
         ("ORB 8:30 30m, 0.5R, with daily trend only", with_trend(lambda b, c, sides: orb_sides(b, c, 0.5, sides))),
         ("S/R fade, 0.5R", lambda b, c: S.pd_sweep_fade(b, c, 0.5)),
         ("ICT model, 1R", lambda b, c: S.ict(b, c, "1R"))], "5m", "60d")
    gold = {"GC=F": MARKETS["GC=F"]}
    run("GOLD ONLY (5m, ~60 days)",
        [("ORB 8:30 15m, 1R", lambda b, c: S.orb(b, c, T(8, 30), 15, "opposite", 1.0)),
         ("ORB 8:30 30m, 1R", lambda b, c: S.orb(b, c, T(8, 30), 30, "opposite", 1.0)),
         ("ORB 8:30 30m, 2R", lambda b, c: S.orb(b, c, T(8, 30), 30, "opposite", 2.0)),
         ("S/R fade, 1R", lambda b, c: S.pd_sweep_fade(b, c, 1.0)),
         ("S/R breakout, 2R", lambda b, c: S.pd_breakout(b, c, 2.0)),
         ("ICT model, 2R", lambda b, c: S.ict(b, c, "2R")),
         ("ICT model, opposite liquidity", lambda b, c: S.ict(b, c, "liquidity"))], "5m", "60d", gold)
    rsi2_report(["SPY", "QQQ", "IWM", "DIA", "GLD", "^GSPC"])
