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
