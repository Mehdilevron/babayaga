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
| Strategy preset | `meanrev` (pending re-validation — see below) |
| Timeframe | D1 (the only validated timeframe) |
| Mode order | real-data research → weeks of demo → only then live |

Live launcher config (VPS): `MAX_TOTAL_LOSS=150`, `EQUITY_FLOOR=1850`,
`MAX_LOT=0.01`, `STRATEGY=meanrev`, `TIMEFRAME=D1`, watchdog
`scripts\run_exness_forever.bat`. `CONFIRM_LIVE=I_UNDERSTAND` is typed only by
the owner, never by an assistant.

## What is PROVEN (by test or measurement)

- Safety machinery works end-to-end: latching hard stop (flattens + freezes,
  survives restarts), equity floor, min-lot veto, daily loss guard, position
  reconciliation, drawdown breaker, halt visible on the dashboard.
- Two engine bugs were found by loss forensics and fixed with regression
  tests: protective exits were invisible to the bus/dashboard; multi-pair
  backtests ran feeds sequentially instead of concurrently.
- On 17 years of real daily FX (ECB), the **trend strategy has no edge**
  (out-of-sample median ≈ 0).
- On real trending stock data, **mean-reversion loses badly** (expected: it
  fades trends).

## What is NOT proven

- **Any strategy's real edge.** meanrev showed +1.31% out-of-sample median on
  real FX, but that was measured before the concurrency fix — it must be
  re-validated with `python3 scripts/fetch_history.py && python3
  scripts/research.py` and judged by its OUT-OF-SAMPLE median.
- Gold and Nasdaq-100 as tradeable instruments (data support added; verdict
  pending the same research run).

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
