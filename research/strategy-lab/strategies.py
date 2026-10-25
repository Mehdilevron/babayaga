"""The strategies under test. Each takes (bars, cost) and returns [(time, R)]."""
import datetime

from strategy_lab import by_session, session, trade

T = datetime.time


def prev_levels(days):
    """{session date: (prev high, prev low)} from the previous session's bars."""
    out, prev = {}, None
    for d, bars in days:
        if prev:
            out[d] = prev
        prev = (max(b[2] for b in bars), min(b[3] for b in bars))
    return out


def flat(days):
    bars, index = [], {}
    for d, bs in days:
        index[d] = len(bars)
        bars += bs
    return bars, index


# ---------------------------------------------------------------- ORB

def orb(bars5, cost, start=T(8, 30), minutes=15, stop_at="opposite", target_r=2.0,
        exit_at=T(12, 0)):
    """Opening range breakout: range = first `minutes` from `start` (New York).
    First 5m close outside the range -> enter at the next open, one trade a day."""
    days = by_session(bars5)
    bars, index = flat(days)
    end = (datetime.datetime.combine(datetime.date(2000, 1, 1), start)
           + datetime.timedelta(minutes=minutes)).time()
    out = []
    for d, bs in days:
        rng = [b for b in bs if start <= b[0].time() < end]
        if len(rng) != minutes // 5:
            continue  # missing bars: halt or holiday
        hi, lo = max(b[2] for b in rng), min(b[3] for b in rng)
        base = index[d]
        for k in range(len(bs) - 1):
            t = bs[k][0].time()
            if t < end or bs[k][0].time() >= exit_at or t < start:
                continue
            c = bs[k][4]
            side = "BUY" if c > hi else "SELL" if c < lo else None
            if not side:
                continue
            j = base + k + 1
            fill = bars[j][1]
            stop = (lo if side == "BUY" else hi) if stop_at == "opposite" else (hi + lo) / 2
            risk = (fill - stop) if side == "BUY" else (stop - fill)
            if risk <= 0:
                break
            tgt = fill + target_r * risk if side == "BUY" else fill - target_r * risk
            r = trade(bars, j, side, fill, stop, tgt, exit_at, cost)
            if r is not None:
                out.append((bars[j][0], r))
            break
    return out


# ---------------------------------------------------------------- previous-day high/low

def pd_sweep_fade(bars5, cost, target_r=1.0, window=(T(3, 0), T(12, 0)), exit_at=T(15, 0)):
    """Support/resistance fade: price pokes beyond yesterday's high (low) and the
    same 5m bar closes back inside -> sell (buy) at the next open, stop beyond
    the poke. One trade per side per day."""
    days = by_session(bars5)
    bars, index = flat(days)
    lv = prev_levels(days)
    out = []
    for d, bs in days:
        if d not in lv:
            continue
        pdh, pdl = lv[d]
        done = set()
        for k in range(len(bs) - 1):
            t, o, h, l, c = bs[k]
            if not (window[0] <= t.time() < window[1]):
                continue
            for side, cond, stop in (("SELL", h > pdh and c < pdh, h), ("BUY", l < pdl and c > pdl, l)):
                if cond and side not in done:
                    done.add(side)
                    j = index[d] + k + 1
                    fill = bars[j][1]
                    risk = (stop - fill) if side == "SELL" else (fill - stop)
                    if risk <= 0:
                        continue
                    tgt = fill - target_r * risk if side == "SELL" else fill + target_r * risk
                    r = trade(bars, j, side, fill, stop, tgt, exit_at, cost)
                    if r is not None:
                        out.append((bars[j][0], r))
    return out


def pd_breakout(bars5, cost, target_r=2.0, window=(T(8, 0), T(12, 0)), exit_at=T(15, 0)):
    """Support/resistance breakout: first 5m close above yesterday's high (below
    its low) -> buy (sell) at the next open, stop at yesterday's high/low
    minus a quarter of yesterday's range."""
    days = by_session(bars5)
    bars, index = flat(days)
    lv = prev_levels(days)
    out = []
    for d, bs in days:
        if d not in lv:
            continue
        pdh, pdl = lv[d]
        pad = (pdh - pdl) / 4
        for k in range(len(bs) - 1):
            t, o, h, l, c = bs[k]
            if not (window[0] <= t.time() < window[1]):
                continue
            side = "BUY" if c > pdh else "SELL" if c < pdl else None
            if not side:
                continue
            j = index[d] + k + 1
            fill = bars[j][1]
            stop = pdh - pad if side == "BUY" else pdl + pad
            risk = (fill - stop) if side == "BUY" else (stop - fill)
            if risk > 0:
                tgt = fill + target_r * risk if side == "BUY" else fill - target_r * risk
                r = trade(bars, j, side, fill, stop, tgt, exit_at, cost)
                if r is not None:
                    out.append((bars[j][0], r))
            break
    return out


# ---------------------------------------------------------------- ICT model

def to15(bs):
    """5m bars of one session -> 15m bars (time, o, h, l, c, index of last 5m bar)."""
    groups = {}
    for i, b in enumerate(bs):
        t = b[0]
        key = t.replace(minute=t.minute - t.minute % 15, second=0)
        groups.setdefault(key, []).append((i, b))
    out = []
    for key in sorted(groups):
        g = groups[key]
        if len(g) == 3:
            out.append((key, g[0][1][1], max(x[1][2] for x in g), min(x[1][3] for x in g),
                        g[-1][1][4], g[-1][0]))
    return out


def asia_range(bs):
    a = [b for b in bs if b[0].time() >= T(19, 0)]  # 19:00-24:00 New York, start of the session
    return (max(b[2] for b in a), min(b[3] for b in a)) if len(a) >= 30 else None


def ict(bars5, cost, target="2R", use_bias=False, window=(T(2, 0), T(12, 0)), exit_at=T(15, 0)):
    """Coded version of the 4-step model in tradingview-mcp/scripts/check_signal.sh:
    1. liquidity = yesterday's high/low and the Asia range high/low
    2. sweep: a 15m bar trades beyond a pool (wick or close)
    3. CISD: within 8 15m bars, a 15m bar closes beyond the previous bar's
       high (bullish, after a low sweep) or low (bearish, after a high sweep)
    4. iFVG on 5m: the latest opposite FVG formed in the 2h before the CISD
       that price has closed through; price comes back to it and a 5m bar
       rejects it -> enter at the next open. Stop beyond the sweep extreme.
    Target: 2R / 3R, or the opposite liquidity (yesterday's high/low).
    use_bias: only trade with the 1h trend (last 1h close vs 20-hour average)."""
    days = by_session(bars5)
    bars, index = flat(days)
    lv = prev_levels(days)
    closes_1h = []  # rolling hourly closes for the bias filter
    out = []
    for d, bs in days:
        if d not in lv:
            continue
        pdh, pdl = lv[d]
        asia = asia_range(bs)
        highs = [pdh] + ([asia[0]] if asia else [])
        lows = [pdl] + ([asia[1]] if asia else [])
        m15 = to15(bs)
        traded = set()
        for s in range(1, len(m15)):
            t15 = m15[s][0].time()
            if not (window[0] <= t15 < window[1]):
                continue
            for side in ("BUY", "SELL"):
                if side in traded:
                    continue
                buy = side == "BUY"
                # a fresh sweep: this bar goes beyond a pool the previous bar had not
                fresh = ([p for p in lows if m15[s][3] < p <= m15[s - 1][3]] if buy else
                         [p for p in highs if m15[s][2] > p >= m15[s - 1][2]])
                if not fresh:
                    continue
                extreme = m15[s][3] if buy else m15[s][2]
                cisd = None
                for u in range(s + 1, min(s + 9, len(m15))):
                    extreme = min(extreme, m15[u][3]) if buy else max(extreme, m15[u][2])
                    if (m15[u][4] > m15[u - 1][2]) if buy else (m15[u][4] < m15[u - 1][3]):
                        cisd = u
                        break
                if cisd is None:
                    continue
                if use_bias and len(closes_1h) >= 20:
                    avg = sum(closes_1h[-20:]) / 20
                    if (closes_1h[-1] < avg) if buy else (closes_1h[-1] > avg):
                        continue
                ci = m15[cisd][5]  # index of the CISD's last 5m bar in bs
                # opposite FVG (bearish for a buy) in the 2h before the CISD
                zone = zi = None
                for i in range(max(2, ci - 24), ci + 1):
                    if buy and bs[i][2] < bs[i - 2][3]:
                        zone, zi = (bs[i][2], bs[i - 2][3]), i   # (bottom, top) of a bearish FVG
                    if not buy and bs[i][3] > bs[i - 2][2]:
                        zone, zi = (bs[i - 2][2], bs[i][3]), i   # bullish FVG
                if not zone:
                    continue
                bottom, top = zone
                # the FVG must be closed through (inverted) after it formed; then,
                # after the CISD and within 2h, a 5m bar taps it and rejects
                inverted = False
                for k in range(zi + 1, min(ci + 25, len(bs) - 1)):
                    t, o, h, l, c = bs[k]
                    if t.time() >= exit_at:
                        break
                    if not inverted:
                        inverted = (c > top) if buy else (c < bottom)
                        continue
                    if k <= ci:
                        continue
                    if (buy and l <= top and c > top) or (not buy and h >= bottom and c < bottom):
                        j = index[d] + k + 1
                        fill = bars[j][1]
                        stop = extreme
                        risk = (fill - stop) if buy else (stop - fill)
                        if risk <= 0:
                            break
                        if target == "liquidity":
                            tgt = pdh if buy else pdl
                            if (tgt <= fill) if buy else (tgt >= fill):
                                break
                        else:
                            n = float(target.rstrip("R"))
                            tgt = fill + n * risk if buy else fill - n * risk
                        r = trade(bars, j, side, fill, stop, tgt, exit_at, cost)
                        if r is not None:
                            out.append((bars[j][0], r))
                            traded.add(side)
                        break
        # hourly closes for the bias filter, from this session's bars
        for b in bs:
            if b[0].minute == 55:
                closes_1h.append(b[4])
    return out
