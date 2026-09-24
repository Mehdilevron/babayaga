# BabaYaga — The Plan (honest recap + path forward)

This is the whole journey in one page, and the real plan from here. Read
alongside `MISSION.md`. No hype, no fantasy — only what's true.

## What BabaYaga is

A multi-agent forex trading OS (pure-Python core) built for the owner to trade
a **live Exness account** with **$2,000**, protected by a **$150 latching hard
stop**. Instruments: 5 FX majors + gold.

## The journey — what we went through

1. Built the OS: event bus, memory journal, agents (technical, sentiment,
   mean-reversion, regime, risk, execution), paper broker, live dashboard.
2. It kept **losing on the dashboard**. We learned why: the default dashboard
   is a **synthetic (fake) market**, rigged toward trend — it is *not* proof of
   anything.
3. We built honest research on **real 17-year data** (`deep_search.py`):
   walk-forward, net of costs, noise-controlled. First real signal:
   **regime-switch +0.42% out-of-sample**, meanrev +0.35%, trend loses.
4. We built the winners into the bot: **regime-switch**, then the **ensemble**
   (regime + mean-reversion, trade only where they agree).
5. We added `--replay` (real prices on the dashboard) and found the real bug:
   tight ATR stops/targets fought the strategy. **Fixed → −17% became +25.5%**
   on real data ($2,000 → ~$2,509 over 17 years).
6. Added safety/quality: **news blackout guard**, **trailing-to-breakeven**,
   **profit-lock**, and a **trade-review tool** to learn from every trade.
7. Tested the "$500/day" dream directly: **500 martingale accounts → 500 went
   to $0.** Proven, on screen. That path is ruin, always.

## What is TRUE

- The bot makes a **small, real, positive** return on real data: **~+1.4%/year**
  ($2,000 → ~$2,509 over 17 years), net of costs, out-of-sample.
- This is **modest but genuine** — rarer than it sounds; most retail bots lose.
- It is a **backtest**, not yet proven in real time.

## What is NOT true (settled, do not revisit)

- **$500/day from $2,000 does not exist** — that's +25%/day. No bot, AI, or
  human does it. The bots that claim it are martingale (blow up) or scams.
- More speed, bigger targets, or "opposing the market" do **not** create profit.
- No guaranteed win exists. The edge is small and must be protected, not inflated.

## Honest expectations by capital (IF the demo confirms ~1.4%/yr)

| Capital | ~per year | Reality |
|---|---|---|
| $2,000 | ~$28 | tiny — proves the mechanism, not a wage |
| $10,000 | ~$140 | real but modest |
| $70,000 | ~$1,000 | meaningful, slowly |

Bigger daily numbers come from **capital + time**, never from a setting.

## The plan from here (the only real path)

1. **DEMO.** Run the exact config on an Exness **demo** account (real live
   prices, virtual money) on the Windows VPS. Leave it 24/7 for **weeks**.
   Same code as live — what it does on demo is what it does live.
2. **TRACK.** Use `scripts/review.py` on the saved journal to see, per pair and
   per exit, what actually makes/loses money. Confirm out-of-sample before any
   change (no tuning to noise).
3. **DECIDE.** If demo tracks the backtest (small, steady, positive) → scale
   capital and, when the owner types `CONFIRM_LIVE`, go live. If not → the edge
   wasn't real; the $2,000 stayed safe while we found out.
4. **GROW.** Add capital as trust is earned. The daily number grows with the
   account — safely — not with leverage that zeroes it.

## Commands

```bash
# Watch the real backtest on the dashboard (real prices):
python3 -m babayaga.dashboard --replay --max-loss 0 --cash 2000 --realistic \
  --strategy ensemble \
  --symbol "EUR/USD,GBP/USD,USD/JPY,AUD/USD,USD/CAD,XAU/USD" --steps 0

# The real strength test (year by year):
python3 -m babayaga.backtest data/*.csv --cash 2000

# Review saved trades:
python3 -m babayaga.dashboard --replay --memory journal.sqlite ...   # then:
python3 scripts/review.py journal.sqlite
```

Demo setup: `docs/exness-vps.md`. The honest win is a bot that **survives and
compounds**, not one that promises $500/day and goes to zero.
