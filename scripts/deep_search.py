"""Deep, honest search for a regime-matched edge — net of spread, out-of-sample.

    python3 scripts/fetch_history.py      # get real prices first (needs internet)
    python3 scripts/deep_search.py        # then search them honestly
    python3 scripts/deep_search.py --noise # sanity: prove no edge on random walks

WHAT THIS IS
------------
The owner keeps asking the right question: can the bot *match the market's
regime* — trend-follow when the market trends, fade extremes when it chops —
and can that survive real spread costs and out-of-sample testing?

This script answers it as honestly as a machine can:

  1. REGIME DETECTOR. Kaufman's Efficiency Ratio (ER) over a lookback window:
     |price change| / sum(|bar-to-bar changes|). ER near 1 = clean trend;
     ER near 0 = choppy/ranging. It uses only PAST bars (no look-ahead).

  2. REGIME-SWITCH STRATEGY. When ER >= threshold -> trend-follow
     (hold direction of the SMA); when ER < threshold -> mean-revert
     (fade the z-score of price vs its mean). This is the "match the regime"
     idea, made concrete.

  3. REAL COSTS. A per-pair half-spread is charged every time the position
     changes. Direction churn therefore *loses* money here, exactly as it
     does on a live account — so the engine can't reward false edges.

  4. WALK-FORWARD, NO PEEKING. The regime threshold + windows are chosen on
     the IN-SAMPLE years only, then LOCKED and judged on the later
     OUT-OF-SAMPLE years. In-sample gains are what overfitting looks like;
     only the out-of-sample column is allowed to mean anything.

  5. NOISE CONTROL. `--noise` runs the identical engine on random walks with
     the same costs. A trustworthy engine returns roughly *minus the cost of
     trading* there — no free edge. If it shows a profit on noise, the result
     is a bug, not a discovery, and the script says so.

This never claims a guaranteed win (see MISSION.md, iron rule #1). It is a
truth-teller: it will usually report that no edge survives costs
out-of-sample, because for retail FX that is the honest and common answer.
When something *does* survive here on real data, it has earned a demo — and
nothing more until the demo agrees.
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from babayaga.backtest import load_csv, _year  # noqa: E402
from babayaga.kernel.events import Candle  # noqa: E402

SPLIT_YEAR = 2019  # years < SPLIT are in-sample, >= SPLIT are out-of-sample

# Realistic round-trip-ish half-spread per pair, in PRICE units (not pips).
# Charged once per position change (open/flip). Deliberately not optimistic.
HALF_SPREAD = {
    "EUR/USD": 0.00005, "GBP/USD": 0.00007, "USD/JPY": 0.006,
    "AUD/USD": 0.00006, "USD/CAD": 0.00007, "USD/CHF": 0.00007,
    "NZD/USD": 0.00008, "GBP/JPY": 0.012,  "XAU/USD": 0.15,
    "NAS100/USD": 0.5,
}
DEFAULT_HALF_SPREAD = 0.0001


# ---------------------------------------------------------------------------
# indicators (pure, look-ahead-free: everything at index i uses closes[:i+1])
# ---------------------------------------------------------------------------
def efficiency_ratio(closes: list[float], i: int, win: int) -> float | None:
    """Kaufman ER over the last `win` bars ending at i. 1=trend, 0=chop."""
    if i < win:
        return None
    net = abs(closes[i] - closes[i - win])
    noise = sum(abs(closes[j] - closes[j - 1]) for j in range(i - win + 1, i + 1))
    if noise == 0:
        return 0.0
    return net / noise


def sma(closes: list[float], i: int, win: int) -> float | None:
    if i + 1 < win:
        return None
    return sum(closes[i + 1 - win:i + 1]) / win


def zscore(closes: list[float], i: int, win: int) -> float | None:
    if i + 1 < win:
        return None
    window = closes[i + 1 - win:i + 1]
    mu = sum(window) / win
    sd = statistics.pstdev(window)
    if sd == 0:
        return 0.0
    return (closes[i] - mu) / sd


# ---------------------------------------------------------------------------
# strategies. Each returns a target position in {-1, 0, +1} for bar i, decided
# from information available AT close of bar i; the P&L is then earned on the
# i -> i+1 move. No look-ahead.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Params:
    er_win: int = 20
    er_thr: float = 0.35     # >= trend regime, < range regime
    sma_win: int = 20
    z_win: int = 20
    z_enter: float = 1.0     # fade when |z| beyond this in a ranging regime
    long_only: bool = False  # stocks/gold often long-only; FX can short


def _trend_target(closes, i, p: Params) -> int:
    s = sma(closes, i, p.sma_win)
    if s is None:
        return 0
    if closes[i] > s:
        return 1
    return 0 if p.long_only else -1


def _revert_target(closes, i, p: Params) -> int:
    z = zscore(closes, i, p.z_win)
    if z is None:
        return 0
    if z <= -p.z_enter:
        return 1                      # oversold -> buy
    if z >= p.z_enter:
        return 0 if p.long_only else -1  # overbought -> sell/flat
    return 0


def regime_switch_target(closes, i, p: Params) -> int:
    er = efficiency_ratio(closes, i, p.er_win)
    if er is None:
        return 0
    return _trend_target(closes, i, p) if er >= p.er_thr else _revert_target(closes, i, p)


def ensemble_target(closes, i, p: Params) -> float:
    """ALL strategies together: average the regime-switch and mean-reversion
    votes. When they AGREE you get full size (+/-1); when one is flat you get
    half; when they CONFLICT they cancel to 0. Scaling exposure by agreement is
    exactly how diversification smooths an equity curve."""
    return (regime_switch_target(closes, i, p) + _revert_target(closes, i, p)) / 2.0


STRATEGIES = {
    "trend":         _trend_target,
    "meanrev":       _revert_target,
    "regime-switch": regime_switch_target,
    "ensemble":      ensemble_target,
}

# The owner's focus: 5 FX majors + gold. No single stocks — those were only
# ever test data. deep_search restricts to these when they're present.
FOCUS_BASKET = ("EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "XAU/USD")


# ---------------------------------------------------------------------------
# backtest one series, net of spread. Returns total return fraction + n trades.
# ---------------------------------------------------------------------------
def backtest(closes: list[float], target_fn, p: Params, half_spread: float
             ) -> tuple[float, int]:
    equity = 1.0
    pos = 0.0  # may be fractional for the ensemble (agreement-scaled exposure)
    trades = 0
    for i in range(len(closes) - 1):
        tgt = target_fn(closes, i, p)
        if tgt != pos:
            # pay half-spread on the size of the position change (in return terms)
            cost = abs(tgt - pos) * half_spread / closes[i]
            equity *= (1.0 - cost)
            trades += 1
            pos = tgt
        if pos != 0:
            ret = (closes[i + 1] - closes[i]) / closes[i]
            equity *= (1.0 + pos * ret)
    return equity - 1.0, trades


def _closes_by_year(candles: list[Candle]) -> dict[int, list[float]]:
    out: dict[int, list[float]] = {}
    for c in candles:
        out.setdefault(_year(c), []).append(c.close)
    return out


# ---------------------------------------------------------------------------
# walk-forward evaluation with an in-sample parameter search, then locked OOS
# ---------------------------------------------------------------------------
ER_THRS = (0.25, 0.35, 0.45)
ER_WINS = (10, 20, 30)
SMA_WINS = (10, 20, 50)


def _param_grid(long_only: bool):
    for er_win in ER_WINS:
        for er_thr in ER_THRS:
            for sma_win in SMA_WINS:
                yield Params(er_win=er_win, er_thr=er_thr, sma_win=sma_win,
                             z_win=sma_win, long_only=long_only)


def _score(kind: str, p: Params, series_by_year: dict[str, dict[int, list[float]]],
           years: list[int], spreads: dict[str, float]) -> float:
    """Median per-(pair,year) return, net of costs, over the given years."""
    fn = STRATEGIES[kind]
    rets = []
    for sym, by_year in series_by_year.items():
        hs = spreads.get(sym, DEFAULT_HALF_SPREAD)
        for y in years:
            closes = by_year.get(y)
            if closes and len(closes) >= 100:
                r, _ = backtest(closes, fn, p, hs)
                rets.append(r)
    return statistics.median(rets) if rets else 0.0


def evaluate(series_by_year, spreads, long_only: bool):
    all_years = sorted({y for by in series_by_year.values() for y in by})
    ins = [y for y in all_years if y < SPLIT_YEAR]
    oos = [y for y in all_years if y >= SPLIT_YEAR]
    print(f"in-sample years: {ins or '(none)'}")
    print(f"out-of-sample  : {oos or '(none)'}\n")

    rows = []
    ensemble_p = None
    for kind in ("trend", "meanrev", "regime-switch", "ensemble"):
        if kind == "regime-switch":
            # choose params on IN-SAMPLE only, then lock for OOS (walk-forward)
            best_p, best_s = None, None
            for p in _param_grid(long_only):
                s = _score(kind, p, series_by_year, ins, spreads)
                if best_s is None or s > best_s:
                    best_s, best_p = s, p
            p = best_p or Params(long_only=long_only)
            note = f"(locked ER_win={p.er_win} ER_thr={p.er_thr} SMA={p.sma_win})"
        elif kind == "ensemble":
            # Fixed default params (NOT grid-searched) -> nothing fit to OOS.
            p = Params(long_only=long_only)
            ensemble_p = p
            note = "(regime + meanrev, agreement-weighted)"
        else:
            p = Params(long_only=long_only)
            note = ""
        in_med = _score(kind, p, series_by_year, ins, spreads)
        oos_med = _score(kind, p, series_by_year, oos, spreads)
        rows.append((kind, in_med, oos_med, note))

    print(f"{'strategy':<16}{'in-sample':>12}{'OUT-OF-SAMPLE':>16}   notes")
    for kind, in_med, oos_med, note in rows:
        print(f"{kind:<16}{in_med*100:>11.2f}%{oos_med*100:>15.2f}%   {note}")

    if ensemble_p is not None and oos:
        _print_portfolio_curve("ensemble", ensemble_p, series_by_year, oos, spreads)
    return rows


def _print_portfolio_curve(kind, p, series_by_year, years, spreads) -> None:
    """The honest screen: the ensemble traded as ONE equal-weight portfolio
    across the whole basket, on real prices, net of spread, in years it was
    never fit to. Shows each year's portfolio return and what $2,000 becomes —
    a rough shape (equal-weight yearly, no intra-year rebalance), not a promise.
    """
    fn = STRATEGIES[kind]
    insts = list(series_by_year)
    print(f"\n{kind} PORTFOLIO — equal-weight across {len(insts)} instruments "
          f"({', '.join(insts)}),")
    print("real out-of-sample, net of spread:")
    acct = 2000.0
    for y in years:
        rets = []
        for sym, by_year in series_by_year.items():
            closes = by_year.get(y)
            if closes and len(closes) >= 100:
                r, _ = backtest(closes, fn, p, spreads.get(sym, DEFAULT_HALF_SPREAD))
                rets.append(r)
        if not rets:
            continue
        port = sum(rets) / len(rets)          # equal-weight allocation
        acct *= (1.0 + port)
        bar = ("+" if port >= 0 else "-") * min(40, int(abs(port) * 1000))
        print(f"  {y}  {port*100:+6.2f}%   ${acct:8.2f}   {bar}")
    total = acct / 2000.0 - 1.0
    print(f"  $2,000 -> ${acct:.2f}  ({total*100:+.1f}% over {len(years)} yrs, "
          f"rough: equal-weight yearly, no intra-year rebalance/compounding)")


# ---------------------------------------------------------------------------
# data sources
# ---------------------------------------------------------------------------
def load_real() -> dict[str, dict[int, list[float]]]:
    data_dir = Path(__file__).resolve().parent.parent / "data"
    files = sorted(data_dir.glob("*.csv"))
    out = {}
    for f in files:
        sym, candles = load_csv(f)
        if candles:
            out[sym] = _closes_by_year(candles)
    return out


def make_noise(n_series: int = 8, years=range(2010, 2024), per_year: int = 252,
               seed: int = 7) -> dict[str, dict[int, list[float]]]:
    """Driftless random walks — there is NO edge to find here by construction."""
    rng = random.Random(seed)
    out = {}
    for k in range(n_series):
        by_year = {}
        price = 100.0
        for y in years:
            closes = []
            for _ in range(per_year):
                price *= (1.0 + rng.gauss(0, 0.008))
                closes.append(price)
            by_year[y] = closes
        out[f"NOISE{k}"] = by_year
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--noise", action="store_true",
                    help="sanity check on random walks (must show no edge)")
    ap.add_argument("--long-only", action="store_true",
                    help="never short (for stocks/gold; FX can short)")
    ap.add_argument("--all-instruments", action="store_true", dest="all_instruments",
                    help="use every data/*.csv instead of the focused 5 FX + gold basket")
    args = ap.parse_args()

    if args.noise:
        print("=== NOISE CONTROL: identical engine on driftless random walks ===")
        print("A trustworthy engine finds NO out-of-sample edge here (only costs).\n")
        rows = evaluate(make_noise(), {}, args.long_only)
        rs = next((o for k, _, o, _ in rows if k == "regime-switch"), 0.0)
        verdict = ("PASS: no false edge on noise." if rs <= 0.05 else
                   "FAIL: engine invented an edge on noise -> bug/overfit, do not trust.")
        print(f"\n{verdict}")
        return 0

    series = load_real()
    if not series:
        print("No data/*.csv found. Run: python3 scripts/fetch_history.py")
        print("(That needs open internet — it will NOT work in the sandbox, "
              "only on your Mac.)")
        return 1
    # Focus on the owner's basket (5 FX majors + gold) unless --all-instruments.
    if not args.all_instruments:
        focused = {s: series[s] for s in FOCUS_BASKET if s in series}
        if focused:
            missing = [s for s in FOCUS_BASKET if s not in series]
            series = focused
            if missing:
                print(f"(note: {', '.join(missing)} not in data/ — skipped)")
    print(f"Loaded {len(series)} instruments: {', '.join(series)}\n")
    evaluate(series, HALF_SPREAD, args.long_only)
    print("\nHow to read this (no marketing, per MISSION.md):")
    print("  * ONLY the OUT-OF-SAMPLE column can mean anything.")
    print("  * regime-switch had its threshold chosen on in-sample years and")
    print("    LOCKED before out-of-sample — so a good OOS number is real, not fit.")
    print("  * Positive OOS median across pairs -> earns a DEMO, nothing more.")
    print("  * <= 0 -> no edge survives costs; capital stays untouched. That is")
    print("    the common, honest answer for retail FX, not a failure of effort.")
    print("  * First run `--noise`: if that shows an 'edge', distrust everything.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
