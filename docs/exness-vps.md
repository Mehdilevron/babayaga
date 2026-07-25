# Running BabaYaga on Exness (MetaTrader 5) via a VPS

Exness has **no REST trading API** — it is driven through the **MetaTrader 5**
terminal, and the only way to automate MT5 from Python (the `MetaTrader5`
package) **runs on Windows only**. Your Mac cannot do this natively, so the
standard setup is a **Windows VPS**.

This guide gets BabaYaga trading **gold (XAU/USD)** on Exness. Start on a **demo**
account. The broker refuses to trade a **live** account unless you explicitly opt
in — see [Going live](#going-live).

---

## 0. What you'll need

- An Exness account (start with a **demo** one — free, virtual money).
- A **Windows VPS** (~$8–15/mo: Contabo, Vultr, Kamatera, or Exness's own VPS
  offer). Windows Server 2019/2022 is fine.
- ~30 minutes.

## 1. Create an Exness demo account + get MT5 credentials

1. In your Exness area, create a **demo** MT5 account.
2. Note three things: **login** (account number), **password**, and **server**
   (e.g. `Exness-MT5Trial9`). You'll need all three.

## 2. Set up the Windows VPS

1. Remote-desktop into your VPS (from your Mac: **Microsoft Remote Desktop** in
   the App Store).
2. Install **MetaTrader 5** — download from Exness (their MT5 build) and log in
   with the demo login / password / server from step 1. Confirm you can see
   **XAUUSD** quotes (add it from Market Watch if not visible).
3. Install **Python 3** (python.org, 64-bit — match MT5's 64-bit). During
   install tick **"Add Python to PATH"**.

## 3. Install BabaYaga + the MT5 bridge

Open **Command Prompt** on the VPS:

```bat
git clone https://github.com/Mehdilevron/babayaga.git
cd babayaga
git checkout claude/quantum-ai-forex-trading-cuepld
pip install MetaTrader5
```

## 4. Configure and run (demo)

Still in Command Prompt, set your account details and launch. **Leave
`CONFIRM_LIVE` unset** — on demo it isn't needed anyway:

```bat
set EXNESS_LOGIN=12345678
set EXNESS_PASSWORD=your-demo-password
set EXNESS_SERVER=Exness-MT5Trial9
rem One pair or a comma-separated basket the bot scans (default is 5 FX majors):
set EXNESS_SYMBOL=EUR/USD,GBP/USD,USD/JPY,AUD/USD,USD/CAD
rem If your account adds a suffix (e.g. EURUSDm), set it once for all pairs:
rem set EXNESS_SUFFIX=m
rem Recommended risk guardrails (work on demo and live):
set MAX_LOT=0.01
set DAILY_MAX_LOSS=10
python examples\run_exness.py
```

> On a small account, prefer FX majors over gold — gold's minimum lot is too
> large to size sensibly. The default basket above sizes fine on a demo balance.

**Guardrails** (optional but strongly recommended, especially before live):

- `MAX_LOT` — hard cap on lots per order. `0.01` keeps every trade at the gold
  minimum regardless of what the sizing model asks for.
- `DAILY_MAX_LOSS` — once your equity is down this much (account currency) from
  the day's open, the bot stops opening new trades until the next day. Open
  positions keep their attached stop-loss.

You should see:

```
Exness account: DEMO (virtual money)  |  symbol XAU/USD
Balance: 10000.00   Equity: 10000.00
Dashboard: http://127.0.0.1:8765
```

Open `http://127.0.0.1:8765` in the VPS browser to watch it trade gold live on
your demo account. Every fill you see is a real MT5 order on the demo book.

> **Symbol suffix:** many Exness account types name gold `XAUUSDm` (or similar).
> If orders fail with "symbol not found", set `EXNESS_SUFFIX` to the trailing
> letters shown in MT5's Market Watch.

## 5. Keep it running

Close the Remote Desktop window (don't sign out) and the bot keeps running on the
VPS. To stop it, RDP back in and press **Ctrl+C** in the Command Prompt.

---

## The owner's standing LIVE structure ($2,000 account)

This is the complete, current configuration (see MISSION.md) — the winning
ensemble, the 5-FX-+-gold basket, signal-driven exits, the $150 latching hard
stop, plus the optional news guard and trailing-to-breakeven. **The demo and
live commands are byte-for-byte identical except the login and the one
`CONFIRM_LIVE` line** — that is the whole point: what you prove on demo is
exactly what runs live.

### Step 1 — run it on DEMO first (same config, virtual money)

```bat
set EXNESS_LOGIN=your-DEMO-number
set EXNESS_PASSWORD=your-demo-password
set EXNESS_SERVER=your-demo-server
set EXNESS_SYMBOL=EUR/USD,GBP/USD,USD/JPY,AUD/USD,USD/CAD,XAU/USD
set STRATEGY=ensemble
set MAX_LOT=0.01
set MAX_TOTAL_LOSS=150
set EQUITY_FLOOR=1850
set FLIP_COOLDOWN=3
rem Optional: stand aside around high-impact news (export a calendar CSV first)
set NEWS_CALENDAR=data\calendar.csv
rem Optional: trailing-to-breakeven (test with vs without before trusting)
rem set TRAIL_ACTIVATE=1.5
rem set TRAIL_DISTANCE=3
set ALERT_WEBHOOK=https://hooks.slack.com/services/...   (optional halt alert)
scripts\run_exness_forever.bat
```

Leave `CONFIRM_LIVE` **unset** — on a demo account it isn't needed, and the
broker will trade the demo book freely. Let it run for **weeks**, until you've
seen enough trades (aim for ~30+) across different market conditions, and the
demo's realized P&L broadly tracks the backtest. This is the proof.

### Step 2 — go live (only after the demo agrees)

Identical, with the **live** login and the one deliberate line **you** type:

```bat
set EXNESS_LOGIN=your-LIVE-number
set EXNESS_PASSWORD=your-live-password
set EXNESS_SERVER=your-live-server
set EXNESS_SYMBOL=EUR/USD,GBP/USD,USD/JPY,AUD/USD,USD/CAD,XAU/USD
set STRATEGY=ensemble
set MAX_LOT=0.01
set MAX_TOTAL_LOSS=150
set EQUITY_FLOOR=1850
set FLIP_COOLDOWN=3
set CONFIRM_LIVE=I_UNDERSTAND
scripts\run_exness_forever.bat
```

Notes on the guards:

- `EQUITY_FLOOR=1850` is the most robust stop: an absolute equity level that
  survives crashes, restarts and reboots with zero bookkeeping.
- `MAX_TOTAL_LOSS=150` measures from your **first** session's equity — the
  anchor is persisted in `babayaga_state.json`, so a crash/restart does *not*
  grant a fresh $200 budget.
- `FLIP_COOLDOWN=3` stops bar-to-bar direction churn (every reversal pays the
  spread twice).
- `scripts\run_exness_forever.bat` is a watchdog: it relaunches the bot if it
  crashes. The `HALTED.lock` is respected on every relaunch, so a hard stop
  stays stopped.
- `ALERT_WEBHOOK` (optional) receives a JSON POST the moment a hard stop trips.

- **`MAX_TOTAL_LOSS=150`** — the latching hard stop. The moment total loss hits
  $150, the bot **closes every open position and stops trading**. It writes a
  `HALTED.lock` file and **stays stopped even if it restarts or the VPS reboots**.
- **To resume** after a hard stop (your command to start again): delete the lock
  and relaunch.
  ```bat
  del HALTED.lock
  python examples\run_exness.py
  ```
- `MAX_LOT=0.01` keeps every position at the minimum size.
- `CONFIRM_LIVE=I_UNDERSTAND` is the only thing that lets it touch a real
  account — you set it, deliberately.

> Reality check on "ultra fast": real forex prints ~1 bar per minute, so faster
> polling does not create more trades, and more trades just pay more spread. The
> hard stop above is what actually protects the $2,000 — keep it on.

## Going live

**Read this honestly.** BabaYaga's strategy has **not** been validated on real
market data — its results so far come from a synthetic simulator. Running it on a
live account is trading real money with an unproven algorithm on leverage. That
is a fast way to lose money. Run **demo for weeks**, judge the results yourself,
and understand you are choosing this.

The broker **auto-detects a real account and blocks all orders** unless you set:

```bat
set CONFIRM_LIVE=I_UNDERSTAND
```

Even then, protect yourself:

- **Fund tiny.** Gold's minimum lot is usually `0.01` = 1 oz ≈ a few thousand
  dollars of notional. On a small balance that is large leverage — a normal gold
  swing can wipe a small account. Understand the margin math before funding.
- Confirm the account's **trade mode** printed at startup says what you expect.
- Watch the first live sessions closely; use MT5's own stop-out and your broker
  risk settings as a backstop.

Nobody should treat this bot as a proven money-maker. The demo exists so you can
find out whether it's worth anything **before** it can cost you.

## Known remaining gaps between the simulator and a live account

Cost realism was added to the paper broker (per-pair spreads, slippage, gaps,
fat tails), but be aware of what is still **not** modelled — real accounts have
all of these:

- **Swap/rollover fees** for positions held overnight, and widened spreads
  around news and the daily rollover.
- **Cross-currency P&L conversion** (e.g. USD/JPY profits are realised in yen);
  the paper broker books price-unit P&L directly in account currency.
- **Margin, stop-out and leverage rules** of your specific Exness account type.
- **Requotes/partial fills under fast markets** beyond the simple IOC model.
- Above all: **the simulator's price generator has built-in regime drift the
  strategy can ride.** Profits on it are a property of the toy market, not
  evidence of real-world edge. Only the demo (real prices) can tell you that.
