"""RSI(2) pullback alert, run near the US close. Standard library only.

The rule (tested 2005-2026 in research/strategy-lab, about 71% of trades won):
  BUY  at the close when close > 200-day average and RSI(2) < 10.
  SELL at the close when close > 5-day average.
  No stop. One position per fund.

Run at about 3:40 PM New York time: today's latest price stands in for the
close, so the user can act in the last minutes of the session. The rule's
open positions are rebuilt from past closes, so nothing is stored between runs.
"""
import argparse
import datetime
import json
import sys
import time
import urllib.request

UA = "Mozilla/5.0 (compatible; rsi2-alert/1.0)"
LINE = "━━━━━━━━━━━━━━━━━━"
FUNDS = [("SPY", "S&P 500"), ("QQQ", "Nasdaq 100"), ("IWM", "Russell 2000"),
         ("DIA", "Dow 30"), ("GLD", "Gold")]
BUY_BELOW = 10
COST = 0.0005
HISTORY_FROM = datetime.date(2005, 1, 1)

try:
    from zoneinfo import ZoneInfo
    NY = ZoneInfo("America/New_York")
except Exception:  # no tz database: close enough for a date
    NY = datetime.timezone(datetime.timedelta(hours=-5))


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch(symbol):
    """(completed daily closes as [(date, close)], meta). Today's live bar,
    if any, is left out of the list; meta carries the live price."""
    start = int(datetime.datetime(2004, 1, 1, tzinfo=datetime.timezone.utc).timestamp())
    url = ("https://query2.finance.yahoo.com/v8/finance/chart/%s?period1=%d&period2=%d&interval=1d"
           % (symbol, start, int(time.time()) + 86400))
    res = get_json(url)["chart"]["result"][0]
    closes = res["indicators"]["quote"][0]["close"]
    out = [(datetime.datetime.fromtimestamp(t, NY).date(), c)
           for t, c in zip(res["timestamp"], closes) if c is not None]
    return out, res["meta"]


def rsi2(c):
    out, ag, al = [None] * len(c), None, None
    for k in range(1, len(c)):
        g, l = max(c[k] - c[k - 1], 0), max(c[k - 1] - c[k], 0)
        ag = g if ag is None else (ag + g) / 2
        al = l if al is None else (al + l) / 2
        out[k] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def sma(c, k, n):
    return sum(c[k - n + 1:k + 1]) / n


def replay(days):
    """Walk the rule over completed closes. Returns (open position or None,
    list of closed trade returns since HISTORY_FROM)."""
    c = [x[1] for x in days]
    r = rsi2(c)
    pos, trades = None, []
    for k in range(200, len(c)):
        if pos is None:
            if days[k][0] >= HISTORY_FROM and c[k] > sma(c, k, 200) and r[k] < BUY_BELOW:
                pos = (days[k][0], c[k])
        elif c[k] > sma(c, k, 5):
            trades.append(c[k] / pos[1] - 1 - COST)
            pos = None
    return pos, trades


def decide(days, live):
    """Today's action if `live` were the close: BUY, SELL, HOLD or None."""
    pos, trades = replay(days)
    c = [x[1] for x in days] + [live]
    k = len(c) - 1
    r = rsi2(c)[k]
    info = {"pos": pos, "trades": trades, "rsi": r, "sma5": sma(c, k, 5),
            "sma200": sma(c, k, 200), "price": live}
    if pos:
        info["action"] = "SELL" if live > info["sma5"] else "HOLD"
    elif live > info["sma200"] and r < BUY_BELOW:
        info["action"] = "BUY"
    else:
        info["action"] = None
    return info


def record(trades):
    if not trades:
        return "Since 2005: no trades"
    return "Since 2005: %d trades · %d%% won · avg %+.2f%%" % (
        len(trades), round(100.0 * sum(1 for t in trades if t > 0) / len(trades)),
        100 * sum(trades) / len(trades))


def lines(symbol, name, x):
    p, out = x["price"], []
    if x["action"] == "BUY":
        out.append("🟢 BUY  %s  $%.2f  (%s)" % (symbol, p, name))
        out.append("   RSI(2) %.1f · above its 200-day avg" % x["rsi"])
        out.append("   Sell later: first close above the 5-day avg")
        out.append("   " + record(x["trades"]))
    elif x["action"] == "SELL":
        d, e = x["pos"]
        out.append("🔴 SELL %s  $%.2f  (%s)" % (symbol, p, name))
        out.append("   Bought %s at %.2f → %+.1f%%" % (d.strftime("%a %d %b"), e, 100 * (p / e - 1)))
        out.append("   Price is above the 5-day avg %.2f" % x["sma5"])
    elif x["action"] == "HOLD":
        d, e = x["pos"]
        out.append("🔵 HOLD %s  $%.2f  (%s)" % (symbol, p, name))
        out.append("   Bought %s at %.2f → %+.1f%%" % (d.strftime("%a %d %b"), e, 100 * (p / e - 1)))
        out.append("   Sell on a close above %.2f (5-day avg)" % x["sma5"])
    else:
        why = ("below its 200-day avg" if p <= x["sma200"] else "RSI(2) %.0f, needs under %d" % (x["rsi"], BUY_BELOW))
        out.append("⚪ %s  $%.2f  no signal (%s)" % (symbol, p, why))
    return out


def market_state(meta, now):
    """'open', 'closed-early' or 'closed' for today, from Yahoo's trading period."""
    reg = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    start, end = reg.get("start"), reg.get("end")
    if not start or not end:
        return "closed"
    if datetime.datetime.fromtimestamp(start, NY).date() != now.date():
        return "closed"  # weekend or holiday: the period shown is another day
    if now.timestamp() >= end:
        return "closed-early"
    return "open" if now.timestamp() >= start else "closed"


def build(now, force=False):
    """(title, message, priority) or None when there is no session today."""
    rows, actions, state = [], 0, None
    for symbol, name in FUNDS:
        try:
            days, meta = fetch(symbol)
        except Exception as e:
            rows.append(["⚪ %s  no data (%s)" % (symbol, type(e).__name__)])
            continue
        if state is None:
            state = "open" if force else market_state(meta, now)
            if state == "closed":
                return None
        if force:
            live, days = days[-1][1], days[:-1]  # test: treat the last close as live
        else:
            if days and days[-1][0] == now.date():
                days = days[:-1]  # today's bar is still forming
            live = meta.get("regularMarketPrice")
        if live is None or len(days) < 210:
            rows.append(["⚪ %s  no data" % symbol])
            continue
        x = decide(days, live)
        actions += x["action"] in ("BUY", "SELL")
        rows.append(lines(symbol, name, x))
        time.sleep(0.3)
    stamp = now.strftime("%a %d %b")
    if state == "closed-early":
        return ("📊 RSI(2) · %s" % stamp, "The market closed early today. No RSI(2) alerts.", 2)
    order = sorted(rows, key=lambda r: "🟢🔴🔵⚪".find(r[0][0]) if r and r[0][0] in "🟢🔴🔵⚪" else 9)
    head = ("%d action%s near the close" % (actions, "" if actions == 1 else "s")) if actions else "No action today"
    body = [head, LINE]
    for r in order:
        body += r + [""]
    body += [LINE, "How to use it:",
             "• Act in the last minutes, 3:45-4:00 PM.",
             "• Same money in each fund, one at a time.",
             "• No stop in the test. Worst trade -13%.",
             "• 2005-2026, 5 funds: 71% won, max",
             "  drawdown 12%, about 2.7% a year.",
             "Rule-based, not advice."]
    return ("📊 RSI(2) at %s · %s" % (now.strftime("%-I:%M %p"), stamp), "\n".join(body), 4 if actions else 2)


def send(topic, title, text, priority):
    body = json.dumps({"topic": topic, "title": title, "message": text, "priority": priority,
                       "tags": ["bar_chart"]}).encode("utf-8")
    req = urllib.request.Request("https://ntfy.sh/", data=body,
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return str(r.status)
    except Exception as e:
        return "%s %s" % (type(e).__name__, getattr(e, "code", "") or e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--test", action="store_true", help='put "TEST - " in front of the title')
    ap.add_argument("--force", action="store_true", help="run on a closed day, using the last close as live")
    ap.add_argument("--dry-run", action="store_true", help="print, do not send")
    a = ap.parse_args()
    now = datetime.datetime.now(NY)
    msg = build(now, a.force)
    if msg is None:
        print("No session today (weekend or holiday): nothing sent.")
        return 0
    title, text, prio = msg
    title = ("TEST - " if a.test else "") + title
    if a.dry_run:
        print(title + "\n" + "=" * 40 + "\n" + text)
        return 0
    status = send(a.topic, title, text, prio)
    print("%s -> %s" % (title, status))
    return 0 if status == "200" else 1


if __name__ == "__main__":
    sys.exit(main())
