import math

from babayaga.analytics import indicators as ind


def test_sma_basic():
    assert ind.sma([1, 2, 3, 4], 2) == 3.5
    assert ind.sma([1, 2], 5) is None


def test_efficiency_ratio_trend_vs_chop():
    # A straight line moves with perfect efficiency -> ER == 1.0.
    line = [1.0 + 0.01 * i for i in range(40)]
    assert abs(ind.efficiency_ratio(line, 30) - 1.0) < 1e-9
    # A tight zigzag goes nowhere with lots of motion -> ER ~ 0.
    zig = [1.02 if i % 2 else 0.98 for i in range(40)]
    er = ind.efficiency_ratio(zig, 30)
    assert er is not None and er < 0.1
    # Not enough data -> None.
    assert ind.efficiency_ratio([1.0, 1.1], 30) is None


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


def test_trend_and_macd_matches_separate_calls():
    # The single-pass optimization must be numerically identical to calling
    # ema()/ema()/macd() separately, or it would change strategy behavior.
    values = [math.sin(i / 5) + i * 0.01 for i in range(80)]
    tm = ind.trend_and_macd(values, 12, 26, 9)
    assert tm is not None
    fast_e, slow_e, macd_last, signal_last, hist = tm
    assert fast_e == ind.ema(values, 12)
    assert slow_e == ind.ema(values, 26)
    ref = ind.macd(values, 12, 26, 9)
    assert ref is not None
    assert (macd_last, signal_last, hist) == ref


def test_trend_and_macd_emas_before_signal_ready():
    # Between slow (26) and slow+signal (35) bars: EMAs present, signal None.
    values = [1.0 + 0.01 * i for i in range(30)]
    tm = ind.trend_and_macd(values, 12, 26, 9)
    assert tm is not None
    assert tm[0] is not None and tm[1] is not None  # EMAs available
    assert tm[3] is None and tm[4] is None           # signal/hist not yet
    assert ind.macd(values, 12, 26, 9) is None        # matches macd() gating


def test_ema_last_matches_ema_series():
    values = [1.0, 2.0, 1.5, 3.0, 2.5, 4.0, 3.5]
    assert ind.ema_last(values, 3) == ind.ema_series(values, 3)[-1]


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
