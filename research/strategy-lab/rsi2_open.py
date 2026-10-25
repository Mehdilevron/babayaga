"""RSI(2) pullback traded at the next day's OPEN instead of the close.

Same signals as rsi2 at the close (close > 200-day average and RSI(2) < 10 to
buy, close > 5-day average to sell), but the order fills at the next open, so
the alert can arrive overnight and be acted on in the morning (Dubai time)."""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run2 import daily  # noqa: E402
from portfolio import rsi2_series  # noqa: E402

START = datetime.date(2005, 1, 1)
COST = 0.0005
FUNDS = ["SPY", "QQQ", "IWM", "DIA", "GLD"]


def trades(b, level=10, at="open"):
    c = [x[4] for x in b]
    r = rsi2_series(c)
    out, pos, k = [], None, 200
    while k < len(c) - 1:
        if pos is None:
            if b[k][0] >= START and c[k] > sum(c[k - 199:k + 1]) / 200 and r[k] < level:
                pos = (k, b[k + 1][1] if at == "open" else c[k])
        elif c[k] > sum(c[k - 4:k + 1]) / 5:
            px = b[k + 1][1] if at == "open" else c[k]
            out.append((b[pos[0]][0], px / pos[1] - 1 - COST))
            pos = None
        k += 1
    return out


def summary(rets):
    if not rets:
        return "no trades"
    worst = min(rets)
    return "%4d trades  %3.0f%% won  avg %+.2f%%  worst %+.1f%%" % (
        len(rets), 100 * sum(1 for x in rets if x > 0) / len(rets), 100 * sum(rets) / len(rets), 100 * worst)


if __name__ == "__main__":
    allc, allo = [], []
    print("%-5s  %-48s  %s" % ("fund", "at the CLOSE (current alert)", "at the next OPEN"))
    for s in FUNDS:
        b = daily(s)
        tc = [x for _, x in trades(b, at="close")]
        to = [x for _, x in trades(b, at="open")]
        allc += tc
        allo += to
        print("%-5s  %-48s  %s" % (s, summary(tc), summary(to)))
    print("%-5s  %-48s  %s" % ("ALL", summary(allc), summary(allo)))
