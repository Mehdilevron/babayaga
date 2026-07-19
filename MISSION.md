# BabaYaga OS — Mission & Standing Orders

This file is the project's permanent memory. It records what this bot is for,
the owner's standing configuration, what has been *proven* versus *assumed*,
and the rules that protect the owner's capital. Read it before changing
anything.

## Purpose

Built for **live forex trading on Exness (MetaTrader 5)** by its owner, with
real capital. Every design decision serves one goal: **trade live without
being destroyed**, and only risk money on behaviour that real data supports.

## Owner's standing configuration

| Setting | Value |
|---|---|
| Capital | **$2,000** |
| Maximum total loss | **$150** — latching hard stop |
| On hard stop | Flatten every position, halt, stay halted across restarts until the owner deletes `HALTED.lock` |
| Strategy preset | `regime-switch` best out-of-sample (+0.42%); `meanrev` close (+0.35%); `trend` loses — demo-gated, see below |
| Timeframe | D1 (the only validated timeframe) |
| Mode order | real-data research → weeks of demo → only then live |

Live launcher config (VPS): `MAX_TOTAL_LOSS=150`, `EQUITY_FLOOR=1850`,
`MAX_LOT=0.01`, `STRATEGY=regime` (best OOS; `meanrev` a close alt),
`TIMEFRAME=D1`, watchdog
`scripts\run_exness_forever.bat`. `CONFIRM_LIVE=I_UNDERSTAND` is typed only by
the owner, never by an assistant.

## What is PROVEN (by test or measurement)

- Safety machinery works end-to-end: latching hard stop (flattens + freezes,
  survives restarts), equity floor, min-lot veto, daily loss guard, position
  reconciliation, drawdown breaker, halt visible on the dashboard.
- Two engine bugs were found by loss forensics and fixed with regression
  tests: protective exits were invisible to the bus/dashboard; multi-pair
  backtests ran feeds sequentially instead of concurrently.
- On real trending stock data, **mean-reversion loses badly** (expected: it
  fades trends).
- **First honest out-of-sample signal (2026-07-20).** `scripts/deep_search.py`
  on 17 years of real prices across 10 instruments, net of spread,
  walk-forward (params locked on 2009–2018 before scoring 2019–2026), median
  per pair-year:

  | strategy | in-sample | OUT-OF-SAMPLE |
  |---|---:|---:|
  | trend | −1.47% | **−1.74%** (no edge, confirmed) |
  | meanrev | +0.84% | **+0.35%** |
  | regime-switch | +1.08% | **+0.42%** |

  The same engine scores **−1.98% on pure random walks** (`--noise`), so the
  positive real-data numbers are a genuine signal, not fitting. This is the
  first time anything survived out-of-sample. **regime-switch** (Kaufman
  Efficiency-Ratio regime detector: trend-follow when trending, fade when
  ranging) is the best.

## What is NOT proven

- **That the out-of-sample signal is big enough to trade for real.** +0.35%
  to +0.42% median per pair-year is *thin*. The backtest does NOT model swap
  fees, news-spread widening, or slippage past the modelled half-spread — any
  of which can eat a thin edge. Positive out-of-sample earns a DEMO, nothing
  more, until weeks of demo tracking agree with the table.
- **The demo agreeing with the backtest.** Not yet run.
- Gold and Nasdaq-100 as *individually* tradeable instruments (they are in the
  10-instrument pool above but per-instrument stability is not broken out).

## Iron rules (do not relax these)

1. **No guaranteed win exists.** Losses are not "bugs" that can all be fixed;
   markets require a counterparty. Regulators require brokers to disclose that
   70–80% of retail accounts lose. Anyone promising a mathematically certain
   win is lying. This project never claims one.
2. **Retail arbitrage is not viable.** True arbitrage needs colocated
   infrastructure and multi-venue access; MT5 brokers ban latency arbitrage.
   Do not build or promise it.
3. **The simulator is a machine test, never a strategy verdict.** Its price
   generator has synthetic drift; strategies are judged ONLY by out-of-sample
   results on real data (`scripts/research.py`) and then demo tracking.
4. **Never tune a strategy until the simulator turns green.** That is
   overfitting to fake data and destroys real-world behaviour.
5. **Guards stay on** in every mode — sim, demo, live.
6. **Sequence is sacred:** real-data edge → weeks of demo agreement → small
   live test. Skipping a step is how the $2,000 dies.

## Current gate

Re-run on the owner's machine and judge the table:

```bash
cd ~/babayaga-live && git pull && python3 scripts/fetch_history.py && python3 scripts/research.py
```

Positive out-of-sample median across years → configure the Exness demo around
it. Zero/negative → no strategy has earned real money yet; keep researching
with the harness, keep capital untouched.
