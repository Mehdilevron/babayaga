"""Command-line entry point for BabaYaga OS.

    python -m babayaga            # run the default simulated session
    python -m babayaga --steps 800 --symbol EUR/USD --seed 3 --verbose

The CLI boots the OS, subscribes a console logger to the event bus so you can
watch the agents coordinate in real time, runs a paper-trading session on the
simulated feed, and prints a performance summary.
"""

from __future__ import annotations

import argparse
import logging

from babayaga.config import Config
from babayaga.kernel.events import AccountSnapshot, Decision, Fill, Side, Topic
from babayaga.os import TradingOS


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="babayaga", description="BabaYaga forex trading OS (paper only)")
    p.add_argument("--symbol", default="EUR/USD", help="instrument to trade")
    p.add_argument("--steps", type=int, default=500, help="number of simulated bars")
    p.add_argument("--seed", type=int, default=7, help="simulation RNG seed")
    p.add_argument("--cash", type=float, default=100_000.0, help="starting cash")
    p.add_argument("--risk", type=float, default=0.01, help="fraction of equity risked per trade")
    p.add_argument("--memory", default=":memory:", help="SQLite path for persistent memory")
    p.add_argument("--verbose", action="store_true", help="log every fill and decision")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    cfg = Config(
        symbols=(args.symbol,),
        starting_cash=args.cash,
        sim_steps=args.steps,
        sim_seed=args.seed,
        memory_path=args.memory,
    )
    cfg.risk.risk_per_trade = args.risk

    os_ = TradingOS(cfg)

    fills: list[Fill] = []
    os_.on(Topic.FILL, lambda f: fills.append(f))

    if args.verbose:
        def log_fill(f: Fill) -> None:
            print(f"  FILL  {f.side.value.upper():4} {f.size:>10,.0f} {f.symbol} @ {f.price:.5f}  ({f.order_reason})")

        def log_decision(d: Decision) -> None:
            if d.side is not Side.FLAT:
                print(f"DECIDE {d.side.value.upper():4} {d.symbol}: {d.rationale}")

        os_.on(Topic.FILL, log_fill)
        os_.on(Topic.DECISION, log_decision)

    print(f"BabaYaga OS — paper trading {args.symbol}  ({args.steps} bars, seed {args.seed})")
    print("-" * 72)

    perf = os_.run_backtest()

    print("-" * 72)
    counts = os_.memory.counts()
    print(f"ticks={counts['ticks']}  signals={counts['signals']}  "
          f"decisions={counts['decisions']}  fills={len(fills)}")
    summary = perf.as_dict()
    print(f"Start equity : {summary['start_equity']:>12,.2f}")
    print(f"End equity   : {summary['end_equity']:>12,.2f}")
    print(f"Total return : {summary['total_return_pct']:>11.2f}%")
    print(f"Max drawdown : {summary['max_drawdown_pct']:>11.2f}%")
    print(f"Sharpe       : {summary['sharpe']:>12.2f}")
    print(f"Trades closed: {summary['num_trades']:>12}")
    print(f"Win rate     : {summary['win_rate_pct']:>11.2f}%")
    print("-" * 72)
    print("NOTE: simulated market, paper broker. No real orders were placed.")

    os_.shutdown()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
