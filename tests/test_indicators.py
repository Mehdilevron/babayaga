import math

from babayaga.analytics import indicators as ind


def test_sma_basic():
    assert ind.sma([1, 2, 3, 4], 2) == 3.5
    assert ind.sma([1, 2], 5) is None


def test_ema_tracks_trend():
    up = list(range(1, 60))
    e = ind.ema(up, 10)
    assert e is not None
    # EMA of a rising series lags the last value but is well above the start.
    assert up[0] < e < up[-1]


def test_rsi_bounds_and_extremes():
    rising = [float(i) for i in range(1, 40)]
    r = ind.rsi(rising, 14)
    assert r is not None and r > 90  # persistent gains -> high RSI

    falling = [float(i) for i in range(40, 1, -1)]
    r2 = ind.rsi(falling, 14)
    assert r2 is not None and r2 < 10


def test_rsi_insufficient_data():
    assert ind.rsi([1, 2, 3], 14) is None


def test_macd_returns_triplet():
    values = [math.sin(i / 5) + i * 0.01 for i in range(80)]
    out = ind.macd(values)
    assert out is not None
    macd_line, signal_line, hist = out
    assert math.isclose(hist, macd_line - signal_line, rel_tol=1e-9)


def test_atr_positive():
    n = 40
    highs = [10 + i * 0.1 + 0.5 for i in range(n)]
    lows = [10 + i * 0.1 - 0.5 for i in range(n)]
    closes = [10 + i * 0.1 for i in range(n)]
    a = ind.atr(highs, lows, closes, 14)
    assert a is not None and a > 0


def test_bollinger_ordering():
    values = [1.0 + 0.01 * (i % 7) for i in range(40)]
    bands = ind.bollinger(values, 20)
    assert bands is not None
    lower, mid, upper = bands
    assert lower <= mid <= upper
