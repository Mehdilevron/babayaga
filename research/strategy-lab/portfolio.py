"""RSI(2) pullback on several markets as one account vs buy-and-hold SPY.

Each market gets 1/N of the account when it signals (no leverage, cash earns
nothing). Daily mark-to-market, so the drawdown includes open trades."""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run2 import daily  # noqa: E402

START = datetime.date(2005, 1, 1)
COST = 0.0005


def rsi2_series(c):
    out, ag, al = [None] * len(c), None, None
    for k in range(1, len(c)):
        g, l = max(c[k] - c[k - 1], 0), max(c[k - 1] - c[k], 0)
        ag = g if ag is None else (ag + g) / 2
        al = l if al is None else (al + l) / 2
        out[k] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def positions(b, level):
    """{date: True if holding at that day's close} plus the trade list."""
    c = [x[4] for x in b]
    r = rsi2_series(c)
    held, trades, entry = {}, [], None
    for k in range(200, len(c)):
        d = b[k][0]
        if entry is None and d >= START and c[k] > sum(c[k - 199:k + 1]) / 200 and r[k] < level:
            entry = c[k]
        elif entry is not None and c[k] > sum(c[k - 4:k + 1]) / 5:
            trades.append(c[k] / entry - 1 - COST)
            entry = None
            held[d] = "exit"
            continue
        held[d] = entry is not None
    return held, trades


def run(symbols, level):
    data = {s: daily(s) for s in symbols}
    closes = {s: {x[0]: x[4] for x in b} for s, b in data.items()}
    hold = {}
    trades = []
    for s, b in data.items():
        hold[s], t = positions(b, level)
        trades += t
    days = sorted(d for d in closes["SPY"] if d >= START)
    eq, peak, dd, prev = 1.0, 1.0, 0.0, {}
    for d in days:
        ret = 0.0
        for s in symbols:
            c = closes[s].get(d)
            p = prev.get(s)
            if c is None:
                continue
            was = hold[s].get(p[0]) if p else None
            if p and was is True:  # held through yesterday's close
                ret += (c / p[1] - 1) / len(symbols)
            if hold[s].get(d) == "exit" or (hold[s].get(d) is True and was is not True):
                ret -= COST / 2 / len(symbols)  # half the cost on each side
            prev[s] = (d, c)
        eq *= 1 + ret
        peak = max(peak, eq)
        dd = max(dd, 1 - eq / peak)
    years = (days[-1] - days[0]).days / 365.25
    spy = [closes["SPY"][d] for d in days]
    bh_peak, bh_dd = spy[0], 0.0
    for p in spy:
        bh_peak = max(bh_peak, p)
        bh_dd = max(bh_dd, 1 - p / bh_peak)
    exposure = sum(1 for s in symbols for d in days if hold[s].get(d) is True) / (len(days) * len(symbols))
    print("RSI(2) < %d on %s" % (level, ", ".join(symbols)))
    print("  trades %d, won %.0f%%, avg %+.2f%%" % (len(trades), 100 * sum(1 for t in trades if t > 0) / len(trades),
                                                 100 * sum(trades) / len(trades)))
    print("  account: %+.0f%% total, %.1f%% a year, max drawdown %.0f%%, money in the market %.0f%% of the time"
          % (100 * (eq - 1), 100 * (eq ** (1 / years) - 1), 100 * dd, 100 * exposure))
    print("  buy-and-hold SPY (price only): %.1f%% a year, max drawdown %.0f%%"
          % (100 * ((spy[-1] / spy[0]) ** (1 / years) - 1), 100 * bh_dd))


if __name__ == "__main__":
    for level in (10, 5):
        run(["SPY", "QQQ", "IWM", "DIA", "GLD"], level)
