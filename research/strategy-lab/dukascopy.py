"""Dukascopy's free 1-minute history -> 5-minute bars in New York time.

One file per day: datafeed.dukascopy.com/datafeed/<SYM>/<YYYY>/<MM-1>/<DD>/BID_candles_min_1.bi5,
LZMA-compressed records of (seconds from 00:00 UTC, open, close, low, high, volume)
with prices as integers scaled by the symbol's point. The field order is checked
on the data itself, so a wrong guess fails loudly instead of corrupting a test.
"""
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


def fetch_day(symbol, day, attempts=8):
    """bi5 bytes, b"" when the day has no file, or None when the server kept
    refusing. The feed throttles hard (503/429, cut-off transfers), so wait
    longer after each refusal."""
    url = URL % (symbol, day.year, day.month - 1, day.day)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return b""  # no file: market closed
            time.sleep(min(10 * 2 ** attempt, 60))  # busy or rate-limited
        except Exception:  # timeout or connection cut off mid-transfer
            time.sleep(5)
    return None


def day_path(symbol, day):
    return os.path.join(CACHE, symbol, day.isoformat() + ".pkl")


def trading_days(start, end):
    """Every calendar day except Saturday (gold and FX trade Sunday evening)."""
    return [start + datetime.timedelta(days=i) for i in range((end - start).days + 1)
            if (start + datetime.timedelta(days=i)).weekday() != 5]


def download(symbol, start, end, pause=1.0):
    """Fetch the missing days one at a time, newest first, saving each day as it
    arrives. Returns the days the server would not give."""
    os.makedirs(os.path.join(CACHE, symbol), exist_ok=True)
    todo = [d for d in reversed(trading_days(start, end)) if not os.path.exists(day_path(symbol, d))]
    failed = []
    for n, d in enumerate(todo, 1):
        raw = fetch_day(symbol, d)
        if raw is None:
            failed.append(d)
        else:
            pickle.dump(decode(raw, d, POINT[symbol]), open(day_path(symbol, d), "wb"))
        if n % 20 == 0 or n == len(todo):
            print("%s: %d of %d days fetched, back to %s, %d refused"
                  % (symbol, n, len(todo), d, len(failed)), file=sys.stderr, flush=True)
        time.sleep(pause)
    return failed


def minutes(symbol, start, end):
    """1-minute candles from the cache for start..end, and the share of days present."""
    days = trading_days(start, end)
    out, have = [], 0
    for d in days:
        path = day_path(symbol, d)
        if os.path.exists(path):
            out += pickle.load(open(path, "rb"))
            have += 1
    return out, have / len(days) if days else 0.0


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
