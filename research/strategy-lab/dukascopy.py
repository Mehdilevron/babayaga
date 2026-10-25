"""Dukascopy's free 1-minute history -> 5-minute bars in New York time.

One file per day: datafeed.dukascopy.com/datafeed/<SYM>/<YYYY>/<MM-1>/<DD>/BID_candles_min_1.bi5,
LZMA-compressed records of (seconds from 00:00 UTC, open, close, low, high, volume)
with prices as integers scaled by the symbol's point. The field order is checked
on the data itself, so a wrong guess fails loudly instead of corrupting a test.
"""
import concurrent.futures
import datetime
import lzma
import os
import pickle
import struct
import sys
import time
import urllib.error
import urllib.request

from strategy_lab import NY, UA

URL = "https://datafeed.dukascopy.com/datafeed/%s/%04d/%02d/%02d/BID_candles_min_1.bi5"
POINT = {"XAUUSD": 1000, "EURUSD": 100000, "GBPUSD": 100000, "USDJPY": 1000, "AUDUSD": 100000}
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "dukascopy")


def decode(raw, day, point):
    """bi5 bytes -> [(utc datetime, open, high, low, close)], minutes with no ticks dropped."""
    if not raw:
        return []
    rows = list(struct.iter_unpack(">5if", lzma.decompress(raw)))
    base = datetime.datetime(day.year, day.month, day.day, tzinfo=datetime.timezone.utc)
    out = []
    for sec, o, c, l, h, vol in rows:
        if vol <= 0:
            continue
        o, h, l, c = o / point, h / point, l / point, c / point
        if not (l <= min(o, c) <= max(o, c) <= h):
            raise ValueError("unexpected field order on %s: %s" % (day, (o, h, l, c)))
        out.append((base + datetime.timedelta(seconds=sec), o, h, l, c))
    return out


def fetch_day(symbol, day):
    url = URL % (symbol, day.year, day.month - 1, day.day)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    err = None
    for attempt in range(7):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return b""  # no file: market closed
            err = e
        except Exception as e:  # connection cut off mid-transfer: back off and retry
            err = e
        time.sleep(min(2 ** attempt, 10))
    raise err


def minutes(symbol, start, end, workers=4):
    """All 1-minute candles from start to end (dates), cached per month."""
    os.makedirs(CACHE, exist_ok=True)
    out, day = [], start
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    while day <= end:
        month = day.replace(day=1)
        path = os.path.join(CACHE, "%s_%s.pkl" % (symbol, month.strftime("%Y-%m")))
        cached = pickle.load(open(path, "rb")) if os.path.exists(path) else {}
        nxt = (month + datetime.timedelta(days=32)).replace(day=1)
        want = [day + datetime.timedelta(days=i) for i in range((min(nxt - datetime.timedelta(days=1), end) - day).days + 1)]
        missing = [d for d in want if d.weekday() != 5 and d.isoformat() not in cached]  # no Saturday trading
        for d, raw in zip(missing, pool.map(lambda d: fetch_day(symbol, d), missing)):
            cached[d.isoformat()] = decode(raw, d, POINT[symbol])
        for d in want:
            out += cached.get(d.isoformat(), [])
        if missing and nxt <= datetime.date.today():  # only cache complete months
            pickle.dump(cached, open(path, "wb"))
        print("%s %s: %d days" % (symbol, month.strftime("%Y-%m"), len(want)), file=sys.stderr, flush=True)
        day = nxt
    pool.shutdown()
    return out


def to5m(rows):
    """1-minute (utc, o, h, l, c) -> 5-minute bars in New York time, the lab's format."""
    bars, cur, key = [], None, None
    for t, o, h, l, c in rows:
        ny = t.astimezone(NY)
        k = ny.replace(minute=ny.minute - ny.minute % 5, second=0, microsecond=0)
        if k != key:
            if cur:
                bars.append(tuple(cur))
            cur, key = [k, o, h, l, c], k
        else:
            cur[2], cur[3], cur[4] = max(cur[2], h), min(cur[3], l), c
    if cur:
        bars.append(tuple(cur))
    return bars
