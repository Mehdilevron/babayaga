"""Technical indicators implemented in pure Python (no numpy/pandas).

Each function takes a sequence of floats (typically closing prices) and returns
either a single latest value or a list aligned to the input. Functions return
``None`` when there is not enough data, so callers can guard cleanly.
"""

from __future__ import annotations

from collections.abc import Sequence


def sma(values: Sequence[float], period: int) -> float | None:
    """Simple moving average of the last ``period`` values."""
    if period <= 0 or len(values) < period:
        return None
    window = values[-period:]
    return sum(window) / period


def ema_series(values: Sequence[float], period: int) -> list[float]:
    """Full exponential moving average series (same length as input)."""
    if not values or period <= 0:
        return []
    k = 2.0 / (period + 1.0)
    out: list[float] = [values[0]]
    prev = values[0]
    for v in values[1:]:
        prev = v * k + prev * (1.0 - k)
        out.append(prev)
    return out


def ema_last(values: Sequence[float], period: int) -> float | None:
    """Latest EMA value only — O(1) memory, no intermediate list built."""
    if not values or period <= 0:
        return None
    k = 2.0 / (period + 1.0)
    prev = values[0]
    for v in values[1:]:
        prev = v * k + prev * (1.0 - k)
    return prev


def ema(values: Sequence[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return ema_last(values, period)


def trend_and_macd(
    values: Sequence[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[float, float, float, float | None, float | None] | None:
    """Fast EMA, slow EMA, MACD line, signal line and histogram in ONE pass.

    Computes the fast/slow EMA series a single time and derives everything from
    them, instead of the technical agent calling ``ema`` twice and ``macd``
    (which recomputes both series again). Behaviour matches the separate calls
    exactly: EMAs are available once ``len >= slow`` (26); the signal line and
    histogram are ``None`` until ``len >= slow + signal`` (35), mirroring
    ``ema``/``macd`` returning None below their own thresholds.
    """
    if len(values) < slow:
        return None
    fast_e = ema_series(values, fast)
    slow_e = ema_series(values, slow)
    macd_line = [f - s for f, s in zip(fast_e, slow_e)]
    macd_last = macd_line[-1]
    if len(values) < slow + signal:
        return fast_e[-1], slow_e[-1], macd_last, None, None
    signal_last = ema_last(macd_line, signal)
    return fast_e[-1], slow_e[-1], macd_last, signal_last, macd_last - signal_last


def rsi(values: Sequence[float], period: int = 14) -> float | None:
    """Relative Strength Index using Wilder's smoothing. Range 0..100."""
    if len(values) <= period:
        return None
    gains = 0.0
    losses = 0.0
    # Seed with the first ``period`` deltas.
    for i in range(1, period + 1):
        delta = values[i] - values[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period
    # Wilder smoothing over the remainder.
    for i in range(period + 1, len(values)):
        delta = values[i] - values[i - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def macd(
    values: Sequence[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[float, float, float] | None:
    """Return (macd_line, signal_line, histogram) for the latest bar."""
    if len(values) < slow + signal:
        return None
    fast_e = ema_series(values, fast)
    slow_e = ema_series(values, slow)
    macd_line = [f - s for f, s in zip(fast_e, slow_e)]
    signal_line = ema_series(macd_line, signal)
    hist = macd_line[-1] - signal_line[-1]
    return macd_line[-1], signal_line[-1], hist


def true_range(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> list[float]:
    tr: list[float] = []
    for i in range(len(closes)):
        if i == 0:
            tr.append(highs[i] - lows[i])
            continue
        prev_close = closes[i - 1]
        tr.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - prev_close),
                abs(lows[i] - prev_close),
            )
        )
    return tr


def atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> float | None:
    """Average True Range — a volatility measure used for stop sizing."""
    if len(closes) <= period:
        return None
    tr = true_range(highs, lows, closes)
    # Wilder-smoothed ATR.
    atr_val = sum(tr[1 : period + 1]) / period
    for i in range(period + 1, len(tr)):
        atr_val = (atr_val * (period - 1) + tr[i]) / period
    return atr_val


def bollinger(values: Sequence[float], period: int = 20, num_std: float = 2.0):
    """Return (lower, mid, upper) Bollinger bands for the latest bar."""
    if len(values) < period:
        return None
    window = values[-period:]
    mid = sum(window) / period
    var = sum((v - mid) ** 2 for v in window) / period
    std = var ** 0.5
    return mid - num_std * std, mid, mid + num_std * std


def efficiency_ratio(values: Sequence[float], period: int = 20) -> float | None:
    """Kaufman Efficiency Ratio over the last ``period`` bars.

    ER = |net change over the window| / sum(|bar-to-bar changes|). It is ~1.0
    when the market moves in a clean straight line (a strong trend) and ~0.0
    when it thrashes back and forth (a choppy/ranging market). Used to decide
    *which* regime we're in — this is the core of the regime-switch strategy
    that survived out-of-sample in ``scripts/deep_search.py``. Look-ahead free:
    only past/current closes are read.
    """
    if period <= 0 or len(values) < period + 1:
        return None
    net = abs(values[-1] - values[-1 - period])
    noise = sum(abs(values[-1 - i] - values[-2 - i]) for i in range(period))
    if noise == 0:
        return 0.0
    return net / noise


def stddev(values: Sequence[float], period: int) -> float | None:
    if len(values) < period:
        return None
    window = values[-period:]
    m = sum(window) / period
    return (sum((v - m) ** 2 for v in window) / period) ** 0.5
