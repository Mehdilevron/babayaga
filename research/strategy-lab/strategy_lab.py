"""Strategy lab: honest intraday backtests on Yahoo bars. Standard library only.

Rules every test follows:
- Decisions use only bars that have closed; fills happen after the signal.
- A bar that touches both the stop and the target counts as a loss.
- Every trade pays a cost (spread + commission) in price units.
- Results are pooled over several markets and split into first/second half,
  so a strategy that only worked in one period shows it.
"""
import datetime
import json
import time
import urllib.request
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UA = "Mozilla/5.0 (compatible; strategy-lab/1.0)"

# symbol: (name, cost per trade in price units)
MARKETS = {
    "GC=F": ("Gold", 0.30),
    "EURUSD=X": ("EUR/USD", 0.00012),
    "GBPUSD=X": ("GBP/USD", 0.00015),
    "USDJPY=X": ("USD/JPY", 0.015),
    "AUDUSD=X": ("AUD/USD", 0.00012),
    "ES=F": ("S&P 500 fut", 0.50),
    "NQ=F": ("Nasdaq fut", 1.50),
}


# ---------------------------------------------------------------- data

def load(symbol, interval="5m", rng="60d"):
    url = "https://query2.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=%s" % (symbol, rng, interval)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        res = json.loads(r.read().decode())["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(res["timestamp"]):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c) or h < l:
            continue
        out.append((datetime.datetime.fromtimestamp(t, NY), o, h, l, c))
    # drop the last bar: it may still be forming
    return out[:-1]


def session(dt):
    """Futures/FX trading day: starts 18:00 New York time the evening before."""
    return (dt + datetime.timedelta(hours=6)).date()


def by_session(bars):
    days = {}
    for b in bars:
        days.setdefault(session(b[0]), []).append(b)
    return [(d, days[d]) for d in sorted(days) if d.weekday() < 5]


# ---------------------------------------------------------------- trade engine

def trade(bars, k, side, entry, stop, target, last_time, cost, stop_entry=False):
    """Walk bars from index k. Returns R after costs, or None if no fill.

    stop_entry: entry is a stop order at `entry` that must trade during bar k
    (else no trade); otherwise we buy/sell at bar k's open."""
    buy = side == "BUY"
    b = bars[k]
    if stop_entry:
        if (b[2] < entry) if buy else (b[3] > entry):
            return None
        fill = max(b[1], entry) if buy else min(b[1], entry)
    else:
        fill = b[1]
    risk = (fill - stop) if buy else (stop - fill)
    if risk <= 0:
        return None
    for j in range(k, len(bars)):
        t, o, h, l, c = bars[j]
        if t.time() >= last_time or (j > k and session(t) != session(b[0])):
            px = bars[j - 1][4] if j > k else c
            break
        if (l <= stop) if buy else (h >= stop):
            px = stop if j == k else (min(o, stop) if buy else max(o, stop))
            break
        if (h >= target) if buy else (l <= target):
            px = target
            break
    else:
        return None  # data ended with the trade still open
    pnl = (px - fill) if buy else (fill - px)
    return (pnl - cost) / risk


# ---------------------------------------------------------------- stats

def stats(results):
    """results: list of (time, R)."""
    rs = [r for _, r in sorted(results)]
    if not rs:
        return None
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    eq = peak = dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    half = len(rs) // 2
    avg = lambda xs: sum(xs) / len(xs) if xs else 0.0
    return {
        "n": len(rs), "win": len(wins) / len(rs), "avg": avg(rs), "total": sum(rs),
        "pf": (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else float("inf"),
        "dd": dd, "first": avg(rs[:half]), "second": avg(rs[half:]),
    }


def row(name, s):
    if not s:
        return "%-44s no trades" % name
    return ("%-44s %4d  %4.0f%%  %+6.2fR  %5.2f  %+7.1fR  %5.1fR  %+5.2f / %+5.2f"
            % (name, s["n"], 100 * s["win"], s["avg"], min(s["pf"], 99), s["total"], s["dd"],
               s["first"], s["second"]))


HEADER = ("%-44s %4s  %5s  %7s  %5s  %8s  %6s  %s"
          % ("strategy", "n", "win", "avg", "PF", "total", "maxDD", "1st half / 2nd half avg"))
