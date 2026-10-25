"""Daily pre-market report for the phone: US stocks, forex and gold.

Standard library only. Prices: Yahoo Finance daily bars. Stock list: the
day-trader-skill scanner's trader/watchlist.json. Headlines: its news tool's
--json output. Calendar: Forex Factory's weekly JSON feed. Sends three ntfy
messages (stocks, forex, then the plan, so the plan sits on top of the list).

Every buy/sell line comes from ONE fixed rule, tested on each market's own
last two years. It is a rule, not a prediction and not advice:

  BUY  when close > 20-day avg > 50-day avg and RSI 40-70:
       buy stop at the last day's high, stop 1 ATR below, target 2 ATR above.
  SELL when close < 20-day avg < 50-day avg and RSI 30-60:
       sell stop at the last day's low, stop 1 ATR above, target 2 ATR below.
  The order lives for one day. Stocks are buy-only.

The test fills at the open when the price gaps past the entry, counts a day
that touches both stop and target as a loss, and closes after 10 days.
"""
import argparse
import datetime
import json
import sys
import time
import urllib.request

UA = "Mozilla/5.0 (compatible; daily-report/2.0)"
LINE = "━━━━━━━━━━━━━━━━━━"
HOLD_DAYS = 10
MIN_TRADES = 8
TOP_N = 5
STOCKS_N = 12
MAX_BYTES = 3900

FX = [  # name, Yahoo symbol, decimals, tradable
    ("EUR/USD", "EURUSD=X", 5, True),
    ("GBP/USD", "GBPUSD=X", 5, True),
    ("USD/JPY", "USDJPY=X", 3, True),
    ("AUD/USD", "AUDUSD=X", 5, True),
    ("USD/CAD", "USDCAD=X", 5, True),
    ("USD/CHF", "USDCHF=X", 5, True),
    ("NZD/USD", "NZDUSD=X", 5, True),
    ("Gold", "GC=F", 2, True),
    ("Dollar index", "DX-Y.NYB", 3, False),
]
FLAGS = {"USD": "🇺🇸", "EUR": "🇪🇺", "GBP": "🇬🇧", "JPY": "🇯🇵",
         "AUD": "🇦🇺", "CAD": "🇨🇦", "CHF": "🇨🇭", "NZD": "🇳🇿"}
SETUP_NAMES = {"breakout_20d": "20-day breakout", "bull_flag": "Bull flag",
               "reclaim_ma20": "Back above 20-day avg", "oversold": "Oversold",
               "oversold_bounce": "Oversold bounce"}
SHORT_NAMES = {"breakout_20d": "Breakout", "bull_flag": "Flag", "reclaim_ma20": "Above avg",
               "oversold": "Oversold", "oversold_bounce": "Bounce"}
CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
ICON = {"BUY": "🟢", "SELL": "🔴", None: "🟡"}

try:
    from zoneinfo import ZoneInfo
    NY = ZoneInfo("America/New_York")
except Exception:  # no tz database: close enough for a date
    NY = datetime.timezone(datetime.timedelta(hours=-5))


# ---------------------------------------------------------------- data

def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def session_day(ts):
    # Yahoo stamps a forex day at 23:00 UTC the evening before (London
    # midnight) and a live bar at its last trade; +2h maps both to the day.
    return (datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
            + datetime.timedelta(hours=2)).date()


def bars(symbol):
    """(completed, today): completed daily bars as (day, open, high, low,
    close), one per weekday, oldest first; today's live bar or None.

    Yahoo can send two bars for one day (a snapshot and the live bar) and a
    flat weekend stub, so keep the latest bar of each weekday."""
    url = "https://query2.finance.yahoo.com/v8/finance/chart/%s?range=2y&interval=1d" % symbol
    res = get_json(url)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    by_day = {}
    for i, ts in enumerate(res.get("timestamp") or []):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        day = session_day(ts)
        if None not in (o, h, l, c) and day.weekday() < 5:
            by_day[day] = (day, o, h, l, c)
    today = session_day(time.time())
    done = [by_day[d] for d in sorted(by_day) if d < today]
    return done, by_day.get(today)


# ---------------------------------------------------------------- indicators

def sma(c, n):
    out, s = [None] * len(c), 0.0
    for i, x in enumerate(c):
        s += x
        if i >= n:
            s -= c[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def rsi(c, n=14):
    out = [None] * len(c)
    if len(c) <= n:
        return out
    g = [max(c[i] - c[i - 1], 0) for i in range(1, len(c))]
    l = [max(c[i - 1] - c[i], 0) for i in range(1, len(c))]
    ag, al = sum(g[:n]) / n, sum(l[:n]) / n
    for i in range(n, len(c)):
        if i > n:
            ag = (ag * (n - 1) + g[i - 1]) / n
            al = (al * (n - 1) + l[i - 1]) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def atr(b, n=14):
    out = [None] * len(b)
    if len(b) <= n:
        return out
    tr = [None] + [max(b[i][2] - b[i][3], abs(b[i][2] - b[i - 1][4]), abs(b[i][3] - b[i - 1][4]))
                   for i in range(1, len(b))]
    a = sum(tr[1:n + 1]) / n
    out[n] = a
    for i in range(n + 1, len(b)):
        a = (a * (n - 1) + tr[i]) / n
        out[i] = a
    return out


# ---------------------------------------------------------------- the rule

def signal(i, c, s20, s50, r):
    if None in (s20[i], s50[i], r[i]):
        return None
    if c[i] > s20[i] > s50[i] and 40 <= r[i] <= 70:
        return "BUY"
    if c[i] < s20[i] < s50[i] and 30 <= r[i] <= 60:
        return "SELL"
    return None


def levels(side, bar, a):
    if side == "BUY":
        return bar[2], bar[2] - a, bar[2] + 2 * a
    return bar[3], bar[3] + a, bar[3] - 2 * a


def simulate(b, i, side, entry, stop, target):
    """(R, exit index) for an order placed after day i, or (None, i)."""
    if i + 1 >= len(b):
        return None, i
    buy = side == "BUY"
    d = b[i + 1]
    if (d[2] < entry) if buy else (d[3] > entry):
        return None, i  # never triggered
    fill = max(d[1], entry) if buy else min(d[1], entry)
    if (fill >= target) if buy else (fill <= target):
        return None, i  # gapped past the target
    risk = abs(fill - stop)
    for j in range(i + 1, min(i + 1 + HOLD_DAYS, len(b))):
        o, h, l = b[j][1], b[j][2], b[j][3]
        if (l <= stop) if buy else (h >= stop):
            px = stop if j == i + 1 else (min(o, stop) if buy else max(o, stop))
            return ((px - fill) if buy else (fill - px)) / risk, j
        if (h >= target) if buy else (l <= target):
            return ((target - fill) if buy else (fill - target)) / risk, j
    if i + HOLD_DAYS >= len(b):
        return None, i  # still open today: no result yet
    px = b[i + HOLD_DAYS][4]
    return ((px - fill) if buy else (fill - px)) / risk, i + HOLD_DAYS


def analyse(symbol, long_only=False):
    done, today = bars(symbol)
    if len(done) < 60:
        raise ValueError("only %d days" % len(done))
    c = [x[4] for x in done]
    s20, s50, r, a = sma(c, 20), sma(c, 50), rsi(c), atr(done)
    results, i, last = [], 50, len(done) - 1
    while i < last:
        side = signal(i, c, s20, s50, r)
        if side and not (long_only and side == "SELL") and a[i]:
            res, j = simulate(done, i, side, *levels(side, done[i], a[i]))
            if res is not None:
                results.append(res)
                i = j
        i += 1
    side = signal(last, c, s20, s50, r)
    trend = ("up" if c[last] > s20[last] > s50[last] else
             "down" if c[last] < s20[last] < s50[last] else "mixed")
    out = {
        "day": done[-1][0], "close": c[last], "prev": c[last - 1], "week": c[last - 5],
        "rsi": r[last], "atr": a[last], "trend": trend,
        "hi20": max(x[2] for x in done[-20:]), "lo20": min(x[3] for x in done[-20:]),
        "side": None, "today": today,
        "trades": len(results),
        "won": sum(1 for x in results if x > 0),
        "avg_r": (sum(results) / len(results)) if results else None,
    }
    if side and not (long_only and side == "SELL"):
        out["side"] = side
        out["entry"], out["stop"], out["target"] = levels(side, done[-1], a[last])
    return out


def strong(x):
    return (x and x.get("side") and x["trades"] >= MIN_TRADES
            and x["avg_r"] is not None and x["avg_r"] > 0)


# ---------------------------------------------------------------- calendar

def calendar(now_utc):
    events = get_json(CALENDAR_URL)
    high, medium = [], []
    for ev in events:
        if ev.get("country") not in FLAGS or ev.get("impact") not in ("High", "Medium"):
            continue
        try:
            t = datetime.datetime.fromisoformat(ev["date"])
        except (KeyError, ValueError):
            continue
        if not (now_utc <= t.astimezone(datetime.timezone.utc) <= now_utc + datetime.timedelta(hours=36)):
            continue
        (high if ev["impact"] == "High" else medium).append((t.astimezone(NY), ev))
    return sorted(high, key=lambda x: x[0]), sorted(medium, key=lambda x: x[0])


def event_lines(rows):
    out = []
    for t, ev in rows:
        out.append("%s %s %s" % (t.strftime("%a %H:%M"), FLAGS[ev["country"]], ev.get("title", "")))
        extra = []
        if ev.get("forecast"):
            extra.append("forecast " + ev["forecast"])
        if ev.get("previous"):
            extra.append("previous " + ev["previous"])
        if extra:
            out.append("   " + " · ".join(extra))
    return out


# ---------------------------------------------------------------- text

def fmt(x, dp):
    return ("%." + str(dp) + "f") % x


def move(a, b):
    p = (a / b - 1) * 100
    return "%s %.2f%%" % ("▲" if p >= 0 else "▼", abs(p))


def history(x, years="2y"):
    if not x["trades"]:
        return "Past %s: no trades" % years
    return "Past %s: %d trades · %d%% won · %+.2fR" % (
        years, x["trades"], round(100.0 * x["won"] / x["trades"]), x["avg_r"])


def why_not(x, long_only=False):
    if x["trend"] == "down" and long_only:
        return "Downtrend. No buy."
    if x["trend"] == "mixed":
        return "No clear trend. Wait."
    if x["rsi"] > 70:
        return "Too stretched (RSI over 70). Wait for a dip."
    if x["rsi"] < 30:
        return "Too stretched (RSI under 30). Wait for a bounce."
    return "Trend too weak (RSI near 50). Wait."


def pct_from_close(x):
    # Gold here is futures; the same % moves apply to spot XAUUSD.
    p = lambda v: "%+.2f%%" % ((v / x["close"] - 1) * 100)
    return ["On XAUUSD, from its last close:",
            "entry %s · stop %s · target %s" % (p(x["entry"]), p(x["stop"]), p(x["target"]))]


def setup_lines(x, dp, indent="   ", gold=False):
    word = "above" if x["side"] == "BUY" else "below"
    out = [indent + "%s %s %s" % (x["side"], word, fmt(x["entry"], dp)),
           indent + "Stop %s · Target %s" % (fmt(x["stop"], dp), fmt(x["target"], dp))]
    if gold:
        out += [indent + s for s in pct_from_close(x)]
    out.append(indent + history(x))
    t = x.get("today")
    if t and ((t[2] >= x["entry"]) if x["side"] == "BUY" else (t[3] <= x["entry"])):
        out.append(indent + "⚡ Entry already reached today (now %s)" % fmt(t[4], dp))
    if not strong(x):
        out.append(indent + "⚠️ Weak: this rule did not make money here")
    return out


def short(s, n=64):
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def stocks_message(watch, news, note, rows):
    out = []
    if note:
        out.append(note)
    if watch is None:
        out.append("Stock scan did not run today.")
        return "\n".join(out)
    hits = watch.get("hits", [])
    counts = {}
    for h in hits:
        for s in h.get("setups", []):
            counts[s] = counts.get(s, 0) + 1
    out.append("Scanned %s · matched %s" % (format(watch.get("scanned", 0), ","), format(len(hits), ",")))
    names = ["%s %d" % (SHORT_NAMES.get(k, k), v)
             for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]
    for k in range(0, len(names), 3):
        out.append(" · ".join(names[k:k + 3]))
    out.append("Showing the %d most traded. Buy-only." % len(rows))
    buys = sorted([r for r in rows if r[1] and r[1].get("side")],
                  key=lambda r: -(r[1]["avg_r"] if r[1]["avg_r"] is not None else -9))
    rest = [r for r in rows if r not in buys]
    if buys:
        out += ["", LINE, "🟢 BUY SETUPS (best first)"]
        for h, x in buys:
            out.append("")
            out.append("🟢 %s  $%.2f  %s" % (h["symbol"], x["close"], move(x["close"], x["prev"])))
            out.append("   %s · RSI %.0f" % (", ".join(SETUP_NAMES.get(s, s) for s in h["setups"]), x["rsi"]))
            out += setup_lines(x, 2)
            if news.get(h["symbol"]):
                out.append("   📰 " + short(news[h["symbol"]]))
    if rest:
        out += ["", LINE, "🟡 NO SETUP TODAY"]
        for h, x in rest:
            out.append("")
            if x is None:
                out.append("⚪ %s  no data" % h["symbol"])
                continue
            icon = "🔴" if x["trend"] == "down" else "🟡"
            out.append("%s %s  $%.2f  %s" % (icon, h["symbol"], x["close"], move(x["close"], x["prev"])))
            out.append("   %s · trend %s · RSI %.0f" % (
                ", ".join(SETUP_NAMES.get(s, s) for s in h["setups"]), x["trend"], x["rsi"]))
            out.append("   " + why_not(x, long_only=True))
            if news.get(h["symbol"]):
                out.append("   📰 " + short(news[h["symbol"]]))
    return "\n".join(out)


def forex_message(fx, medium):
    out = ["🟢 buy setup · 🔴 sell setup · 🟡 wait"]
    order = sorted(fx, key=lambda r: (r[1] is None, not (r[1] and r[1].get("side")),
                                      -(r[1]["avg_r"] or 0) if r[1] and r[1].get("avg_r") is not None else 0))
    for (name, symbol, dp, tradable), x in order:
        out.append("")
        if x is None:
            out.append("⚪ %s  no data" % name)
            continue
        icon = ICON[x["side"]] if tradable else "📊"
        out.append("%s %s  %s" % (icon, name, fmt(x["close"], dp)))
        out.append("   %s day · %s week" % (move(x["close"], x["prev"]), move(x["close"], x["week"])))
        out.append("   Trend %s · RSI %.0f" % (x["trend"], x["rsi"]))
        out.append("   20-day %s – %s" % (fmt(x["lo20"], dp), fmt(x["hi20"], dp)))
        if tradable and x["side"]:
            out += setup_lines(x, dp, gold=symbol == "GC=F")
        elif tradable:
            out.append("   No setup: " + why_not(x))
    out += ["", "Gold = COMEX futures. Spot XAUUSD on TradingView is a little lower."]
    if medium:
        out += ["", LINE, "📅 OTHER EVENTS (New York time)"] + event_lines(medium)
    return "\n".join(out)


def plan_message(data_day, top, high, cal_error):
    out = ["Data: %s close" % data_day.strftime("%a %d %b"), LINE, "🎯 TOP SETUPS (best first)"]
    if not top:
        out += ["", "No strong setups today.", "Waiting is also a decision."]
    for n, (label, dp, x, kind) in enumerate(top, 1):
        out.append("")
        out.append("%d) %s %s %s%s" % (n, ICON[x["side"]], x["side"], label, kind))
        word = "above" if x["side"] == "BUY" else "below"
        out.append("   Entry  %s %s" % (word, fmt(x["entry"], dp)))
        out.append("   Stop   %s" % fmt(x["stop"], dp))
        out.append("   Target %s" % fmt(x["target"], dp))
        if label == "Gold":
            out += ["   " + s for s in pct_from_close(x)]
        out.append("   " + history(x))
        t = x.get("today")
        if t and ((t[2] >= x["entry"]) if x["side"] == "BUY" else (t[3] <= x["entry"])):
            out.append("   ⚡ Entry already reached (now %s)" % fmt(t[4], dp))
    out += ["", LINE, "⚠️ BIG NEWS (New York time)"]
    if cal_error:
        out += ["Calendar not available (%s)." % cal_error,
                "Add nfs.faireconomy.media in",
                "Network access → Allowed domains."]
    elif high:
        out += event_lines(high)
    else:
        out.append("No big news in the next 36 hours.")
    out += ["", LINE, "How to read this:",
            "• No entry price = no trade.",
            "• Set the stop when you enter.",
            "• Big news can jump past a stop.",
            "• R = your risk. +0.30R = won 30% of",
            "  the risk per trade on average.",
            "Rule-based levels, not advice."]
    return "\n".join(out)


# ---------------------------------------------------------------- ntfy

def split(title, text):
    if len(text.encode("utf-8")) <= MAX_BYTES:
        return [(title, text)]
    parts, cur = [], ""
    for block in text.split("\n\n"):
        cand = (cur + "\n\n" + block) if cur else block
        if cur and len(cand.encode("utf-8")) > MAX_BYTES:
            parts.append(cur)
            cur = block
        else:
            cur = cand
    parts.append(cur)
    n = len(parts)
    return [("%s (%d/%d)" % (title, k, n), p) for k, p in enumerate(parts, 1)]


def send(topic, title, text, priority, tags):
    body = json.dumps({"topic": topic, "title": title, "message": text,
                       "priority": priority, "tags": tags}).encode("utf-8")
    req = urllib.request.Request("https://ntfy.sh/", data=body,
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return str(r.status)
    except Exception as e:
        return "%s %s" % (type(e).__name__, getattr(e, "code", "") or e)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watchlist", default="trader/watchlist.json")
    ap.add_argument("--news", default="trader/news.json")
    ap.add_argument("--stocks-note", default="")
    ap.add_argument("--topic", required=True)
    ap.add_argument("--test", action="store_true", help='put "TEST - " in front of each title')
    ap.add_argument("--dry-run", action="store_true", help="print, do not send")
    a = ap.parse_args()

    now = datetime.datetime.now(datetime.timezone.utc)
    pre = "TEST - " if a.test else ""

    try:
        with open(a.watchlist, encoding="utf-8") as fh:
            watch = json.load(fh)
    except (OSError, ValueError):
        watch = None
    news = {}
    try:
        with open(a.news, encoding="utf-8") as fh:
            for it in sorted(json.load(fh).get("items", []), key=lambda it: it.get("time", "")):
                news[it.get("ticker")] = it.get("title")  # newest wins
    except (OSError, ValueError, AttributeError):
        pass

    fx = []
    for row in FX:
        try:
            fx.append((row, analyse(row[1])))
        except Exception as e:
            print("no data for %s: %s" % (row[1], e), file=sys.stderr)
            fx.append((row, None))
        time.sleep(0.3)

    stock_rows = []
    for h in (watch or {}).get("hits", [])[:STOCKS_N]:
        try:
            stock_rows.append((h, analyse(h["symbol"], long_only=True)))
        except Exception as e:
            print("no data for %s: %s" % (h["symbol"], e), file=sys.stderr)
            stock_rows.append((h, None))
        time.sleep(0.3)

    try:
        high, medium = calendar(now)
        cal_error = ""
    except Exception as e:
        high, medium, cal_error = [], [], type(e).__name__

    top = [(row[0], row[2], x, "") for row, x in fx if row[3] and strong(x)]
    top += [(h["symbol"], 2, x, " (stock)") for h, x in stock_rows if strong(x)]
    top = sorted(top, key=lambda t: -t[2]["avg_r"])[:TOP_N]

    days = [x["day"] for _, x in fx + stock_rows if x]
    data_day = max(days) if days else now.date()
    stamp = data_day.strftime("%a %d %b")
    today = now.astimezone(NY).strftime("%a %d %b")

    messages = []  # sent in this order; ntfy shows the newest on top
    messages += [(t, m, 3, ["chart_with_upwards_trend"]) for t, m in reversed(split(
        "%s📈 US stocks · %s" % (pre, stamp), stocks_message(watch, news, a.stocks_note, stock_rows)))]
    messages += [(t, m, 3, ["currency_exchange"]) for t, m in reversed(split(
        "%s💱 Forex & gold · %s" % (pre, stamp), forex_message(fx, medium)))]
    messages += [(t, m, 4, ["dart"]) for t, m in reversed(split(
        "%s🎯 Today's plan · %s" % (pre, today), plan_message(data_day, top, high, cal_error)))]

    ok = True
    for title, text, prio, tags in messages:
        if a.dry_run:
            print("=" * 40 + "\n" + title + "\n" + "=" * 40 + "\n" + text + "\n")
            continue
        status = send(a.topic, title, text, prio, tags)
        ok = ok and status == "200"
        print("%s -> %s" % (title, status))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
