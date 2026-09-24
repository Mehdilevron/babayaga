"""Trade review — turn the saved trade journal into 'where do we make/lose money'.

    python3 -m babayaga.dashboard --memory babayaga.sqlite ...   # run, saving trades
    python3 scripts/review.py babayaga.sqlite                    # then review them

This is the honest version of "every time the bot trades, learn from it": it
reads the fills the OS already journals, reconstructs each closed round-trip
trade and its P&L, and reports — per instrument and per exit reason — the win
rate, average win vs average loss, and expectancy (expected $ per trade).

It does NOT auto-tune the strategy on these results. Fitting parameters to your
own recent trades is overfitting — the exact mistake that makes bots look great
and then fail live (MISSION.md iron rule #4). This tool informs a HUMAN review:
you see what's working, form a hypothesis, and validate it out-of-sample with
scripts/deep_search.py before changing anything. That's how it gets better for
real instead of getting fit to noise.
"""

from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict


def _closed_trades(fills: list[sqlite3.Row]) -> list[dict]:
    """Reconstruct closed round-trip trades (avg-cost) per symbol from fills."""
    by_symbol: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for f in fills:
        by_symbol[f["symbol"]].append(f)

    trades: list[dict] = []
    for symbol, rows in by_symbol.items():
        pos = 0.0
        avg = 0.0
        for f in rows:
            signed = f["size"] * (1.0 if f["side"] == "buy" else -1.0)
            # Realise P&L on the portion being reduced/closed.
            if pos != 0 and (pos > 0) != (signed > 0):
                closing = min(abs(signed), abs(pos))
                direction = 1.0 if pos > 0 else -1.0
                pnl = (f["price"] - avg) * closing * direction
                trades.append({
                    "symbol": symbol,
                    "pnl": pnl,
                    "reason": f["reason"] or "close",
                    "ts": f["ts"],
                })
            new_pos = pos + signed
            if new_pos == 0:
                avg = 0.0
            elif pos == 0 or (pos > 0) == (signed > 0):
                avg = (avg * abs(pos) + f["price"] * abs(signed)) / abs(new_pos)
            pos = new_pos
    return trades


def _stats(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0}
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    n = len(pnls)
    return {
        "n": n,
        "total": sum(pnls),
        "win_rate": len(wins) / n * 100.0,
        "avg_win": (sum(wins) / len(wins)) if wins else 0.0,
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "expectancy": sum(pnls) / n,   # expected P&L per trade (price units)
    }


def _print_block(title: str, groups: dict[str, list[dict]]) -> None:
    print(f"\n{title}")
    print(f"  {'group':<14}{'trades':>7}{'win%':>7}{'avg win':>10}"
          f"{'avg loss':>10}{'expect/trade':>14}{'total':>12}")
    # Sort by total P&L so the best and worst stand out.
    for name in sorted(groups, key=lambda k: _stats(groups[k]).get("total", 0), reverse=True):
        s = _stats(groups[name])
        if s["n"] == 0:
            continue
        print(f"  {name:<14}{s['n']:>7}{s['win_rate']:>6.0f}%{s['avg_win']:>10.4f}"
              f"{s['avg_loss']:>10.4f}{s['expectancy']:>14.4f}{s['total']:>12.4f}")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: python3 scripts/review.py <journal.sqlite>")
        print("  (run the bot with --memory <journal.sqlite> first so trades are saved)")
        return 0 if argv else 1
    path = argv[0]
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    fills = conn.execute("SELECT * FROM fills ORDER BY ts").fetchall()
    conn.close()

    trades = _closed_trades(fills)
    if not trades:
        print(f"No closed trades found in {path}. "
              f"Run the bot with --memory {path} first (and let it trade).")
        return 1

    overall = _stats(trades)
    print(f"TRADE REVIEW — {path}")
    print(f"  closed trades : {overall['n']}")
    print(f"  total P&L     : {overall['total']:+.4f} (price units)")
    print(f"  win rate      : {overall['win_rate']:.0f}%")
    print(f"  avg win/loss  : {overall['avg_win']:+.4f} / {overall['avg_loss']:+.4f}")
    print(f"  expectancy    : {overall['expectancy']:+.4f} per trade  "
          f"({'positive edge' if overall['expectancy'] > 0 else 'no edge — do not fund'})")

    by_symbol: dict[str, list[dict]] = defaultdict(list)
    by_reason: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        by_symbol[t["symbol"]].append(t)
        by_reason[t["reason"]].append(t)
    _print_block("By instrument (which pairs carry their weight):", by_symbol)
    _print_block("By exit reason (what closes winners vs losers):", by_reason)

    print("\nHow to use this (NOT auto-tuning):")
    print("  * A pair with negative expectancy over MANY trades is a review")
    print("    candidate — but confirm it's negative OUT-OF-SAMPLE in")
    print("    scripts/deep_search.py before removing it (one bad run != bad pair).")
    print("  * Do not tweak settings until this looks good — that fits noise and")
    print("    breaks live behaviour. Form a hypothesis, validate, THEN change.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
