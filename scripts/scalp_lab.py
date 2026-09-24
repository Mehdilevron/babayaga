"""Scalp laboratory — test a gold straddle-scalp and find what's wrong yourself.

    python3 scripts/scalp_lab.py                 # defaults (the owner's idea)
    python3 scripts/scalp_lab.py --tp 20 --sl 40 # try asymmetric: bigger stop
    python3 scripts/scalp_lab.py --spread 0.15   # a tighter-spread broker
    python3 scripts/scalp_lab.py --sweep         # try many combos at once

This is YOUR test bench. It models the mechanics of the straddle scalp you
described — place a buy-stop above and a sell-stop below, whichever triggers,
take +TP or stop at -SL, then reopen — on a controllable gold price path, so
you can change every knob and watch the P&L react. Change the numbers and see
which part helps and which part bleeds.

Honest about what it is: the price path is a realistic random walk (gold's
minute volatility + your broker's spread), NOT a recording of real ticks — we
don't have intraday gold history here. But the COSTS are real: the spread you
pay per trade and how often scalping makes you pay it are modelled exactly.
That's the part that decides a scalp's fate, and it's why the answer rarely
changes: the spread, paid many times, is the leak. Prove it to yourself.

Not wired to live trading. It's a sandbox for figuring out the strategy.
"""

from __future__ import annotations

import argparse
import random
import statistics


def scalp_day(rng: random.Random, *, start: float, minutes: int, oz: float,
              tp_dollars: float, sl_dollars: float, straddle: float,
              spread: float, per_min_std: float) -> tuple[float, int, int]:
    """One day of straddle-scalping. Returns (pnl, trades, wins)."""
    price = start
    equity = 0.0
    pos = 0            # +1 long, -1 short, 0 flat (straddle armed)
    entry = 0.0
    trades = wins = 0
    tp_move = tp_dollars / oz     # gold-$ move that yields the target
    sl_move = sl_dollars / oz
    spread_cost = spread * oz     # account-$ paid to cross the spread per trade
    for _ in range(minutes):
        price += rng.gauss(0, per_min_std)
        if pos == 0:
            # Whichever stop price reaches first — ~a coin flip on a random path.
            if rng.random() < 0.5:
                pos, entry = 1, price + straddle
            else:
                pos, entry = -1, price - straddle
            equity -= spread_cost
            trades += 1
        else:
            move = (price - entry) * pos
            if move >= tp_move:
                equity += tp_dollars
                wins += 1
                pos = 0
            elif move <= -sl_move:
                equity -= sl_dollars
                pos = 0
    return equity, trades, wins


def run(cfg, days: int) -> dict:
    pnls, trs, wins = [], [], []
    for s in range(days):
        rng = random.Random(1000 + s)
        e, tr, w = scalp_day(rng, **cfg)
        pnls.append(e); trs.append(tr); wins.append(w)
    n_tr = sum(trs)
    return {
        "pnl_day": statistics.mean(pnls),
        "trades_day": statistics.mean(trs),
        "win_rate": (sum(wins) / n_tr * 100.0) if n_tr else 0.0,
        "spread_day": statistics.mean(trs) * (cfg["spread"] * cfg["oz"]),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tp", type=float, default=10.0, help="take-profit in account $")
    ap.add_argument("--sl", type=float, default=10.0, help="stop-loss in account $")
    ap.add_argument("--straddle", type=float, default=2.0,
                    help="gold-$ distance of the buy/sell stop from price")
    ap.add_argument("--spread", type=float, default=0.30,
                    help="gold spread in $ (Exness XAUUSD ~0.20-0.50, wider on news)")
    ap.add_argument("--oz", type=float, default=10.0, help="ounces traded (0.10 lot = 10)")
    ap.add_argument("--vol", type=float, default=0.9, help="gold per-minute volatility in $")
    ap.add_argument("--minutes", type=int, default=1440, help="minutes per day")
    ap.add_argument("--days", type=int, default=300, help="days to average over")
    ap.add_argument("--start", type=float, default=4050.0, help="gold start price")
    ap.add_argument("--sweep", action="store_true", help="try many TP/SL/straddle combos")
    args = ap.parse_args()

    base = dict(start=args.start, minutes=args.minutes, oz=args.oz,
                tp_dollars=args.tp, sl_dollars=args.sl, straddle=args.straddle,
                spread=args.spread, per_min_std=args.vol)

    if not args.sweep:
        r = run(base, args.days)
        print(f"straddle-scalp  TP ${args.tp:.0f}  SL ${args.sl:.0f}  "
              f"straddle ${args.straddle:.1f}  spread ${args.spread:.2f}/oz x "
              f"{args.oz:.0f}oz = ${args.spread*args.oz:.2f}/trade")
        print(f"  {r['trades_day']:.0f} trades/day   win-rate {r['win_rate']:.0f}%")
        print(f"  P&L: ${r['pnl_day']:+.0f}/day   (spread paid: "
              f"${r['spread_day']:+.0f}/day)")
        verdict = ("PROFITABLE in this model — worth a closer, real-tick test."
                   if r["pnl_day"] > 0 else
                   "LOSES — the spread paid per day is the leak. Try --sweep.")
        print(f"  -> {verdict}")
        return 0

    print("SWEEP — searching TP/SL/straddle for anything that beats the spread:\n")
    print(f"{'TP':>5}{'SL':>5}{'straddle':>10}{'trades/d':>10}{'win%':>7}{'P&L/day':>10}")
    best = None
    for tp in (10, 20, 40, 80):
        for sl in (10, 20, 40, 80):
            for straddle in (1.0, 2.0, 4.0):
                cfg = {**base, "tp_dollars": tp, "sl_dollars": sl, "straddle": straddle}
                r = run(cfg, 120)
                if best is None or r["pnl_day"] > best[1]["pnl_day"]:
                    best = ((tp, sl, straddle), r)
                print(f"{tp:>5}{sl:>5}{straddle:>10.1f}{r['trades_day']:>10.0f}"
                      f"{r['win_rate']:>6.0f}%{r['pnl_day']:>+10.0f}")
    (tp, sl, st), r = best
    print(f"\nBest combo: TP ${tp} SL ${sl} straddle ${st} -> ${r['pnl_day']:+.0f}/day")
    if r["pnl_day"] <= 0:
        print("Every combo loses. The lesson: no TP/SL on a straddle beats paying")
        print("the spread hundreds of times. The leak is the spread × trade count,")
        print("and scalping 'fast' only makes it worse. That's the part that's wrong.")
    else:
        print("This combo shows a model profit — before trusting it, test on REAL")
        print("gold ticks and a demo; a random-walk model can flatter a scalper.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
