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
| Strategy preset | `ensemble` (regime-switch + meanrev, trades only where they agree) is the standing default; `regime-switch` best single OOS (+0.42%), `meanrev` (+0.35%), `trend` loses — all demo-gated, see below |
| Instrument basket | 5 FX majors + gold: EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CAD, XAU/USD (no single stocks) |
| Timeframe | D1 (the only validated timeframe) |
| Mode order | real-data research → weeks of demo → only then live |

Live launcher config (VPS): `MAX_TOTAL_LOSS=150`, `EQUITY_FLOOR=1850`,
`MAX_LOT=0.01`, `STRATEGY=ensemble` (default; `regime`/`meanrev` alts),
`EXNESS_SYMBOL=EUR/USD,GBP/USD,USD/JPY,AUD/USD,USD/CAD,XAU/USD`,
`TIMEFRAME=D1`, watchdog
`scripts\run_exness_forever.bat`. `CONFIRM_LIVE=I_UNDERSTAND` is typed only by
the owner, never by an assistant.

## The configuration that first turned a real-data profit (2026-07-20)

This is the exact, reproducible setup behind the first positive real-data run
($2,000 → $2,509, +25.5% over the full ~17-year replay ≈ +1.4%/yr). **Save
every parameter — this is the reference config.** Honest scope: it is a
backtest of the live execution over real prices, not yet a demo or live result,
and the year-by-year robustness table is still to be confirmed.

| Parameter | Value | Why |
|---|---|---|
| Strategy | `ensemble` = RegimeSwitchAgent + MeanReversionAgent, coordinator confidence-vote | trades only where both agree, flat when they conflict |
| Basket | EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CAD, XAU/USD | 5 FX majors + gold; no single stocks |
| Timeframe | D1 (daily bars) | the only validated timeframe |
| **Exit policy** | **signal-driven: `atr_target_mult=0` (no take-profit), `atr_stop_mult=6.0` (wide catastrophic stop only)** | THE fix — a tight stop/target fought the reversion thesis and turned winners into losses (−17% → +25.5%) |
| Risk per trade | `risk_per_trade=0.01` (1% of equity, ATR-sized) | wider stop ⇒ smaller size for same $ risk |
| Min confidence | `0.15` (ensemble) | require agreement before trading |
| Flip cooldown | `3` bars (realistic mode) | stop paying spread on bar-to-bar churn |
| Regime detector | Kaufman ER: `er_win=30`, `er_thr=0.35`, `sma_win=20` | trend-follow when ER≥0.35, fade when below |
| Mean-reversion | Bollinger `period=20`, `entry_z=1.5` | fade stretched z-scores |
| Costs | realistic per-pair spread + slippage | net-of-cost, not optimistic |
| Starting cash | $2,000 | owner capital |

Reproduce the profitable real-data view (live brake off so the whole history
plays; the $150 hard stop is a LIVE guard, not a backtest setting):

```bash
git pull
python3 -m babayaga.dashboard --replay --max-loss 0 --cash 2000 --realistic \
  --strategy ensemble \
  --symbol "EUR/USD,GBP/USD,USD/JPY,AUD/USD,USD/CAD,XAU/USD" --steps 0
# and the year-by-year table (the strength test):
python3 -m babayaga.backtest data/*.csv --cash 2000
```

Iron-rule reminder: **+1.4%/yr is real and modest, NOT a $500/day target.**
$500/day on $2,000 is +25%/day — impossible without account-destroying
leverage. Small and steady is what survives; do not re-tune this to chase a
bigger number (that is overfitting, iron rule #4). Next gate is the demo.

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

- **Execution edge-leak found and fixed (2026-07-20).** Same signal, same real
  prices: the live OS lost ~−17% while deep_search's model made +0.42%, because
  every trade carried a tight 2×ATR stop + 3×ATR take-profit that fought a
  reversion strategy. Switching meanrev/regime/ensemble to signal-driven exits
  (no take-profit, wide 6×ATR catastrophic stop only) turned a full real-data
  replay of the ensemble from **−17.2% to +25.5%** ($2,000 → $2,509 over ~17
  years ≈ **+1.4%/yr**). Real, positive, and modest — NOT a daily target.

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
