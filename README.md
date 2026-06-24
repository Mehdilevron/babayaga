# babayaga

A cross-venue arbitrage bot. It watches the same asset quoted on two or more
venues, and when the spread clears fees + gas + slippage by a configured
margin, it buys on the cheap leg and sells (or opens an offsetting hedge) on
the rich leg - faster and more consistently than a human watching charts.

Three venue types, one engine:

- **EVM DEXs** (Uniswap V2/V3, Sushiswap, QuickSwap) on Ethereum, Polygon, Arbitrum
- **Solana** via the Jupiter aggregator (Raydium, Orca)
- **MetaTrader 5** as a cross-market hedge leg - e.g. buy PAXG cheap on-chain
  and simultaneously short XAUUSD on MT5 to lock in the gap between tokenized
  gold and the spot/CFD market, instead of selling the same asset back

It signs and submits orders itself, with no manual approval step in the loop
- that's the entire point of automating this. Read the **Safety** section
below before you point it at real funds.

## How it works

Every tick, the engine does, per configured pair:

```
scan (quote every leg concurrently)
  -> detect (best profitable buy/sell combination, after fees+gas+slippage)
  -> risk-check (profit floor, position size, daily loss, open positions, kill switch)
  -> execute (buy leg, then sell/hedge leg - sequentially, never concurrently)
```

The two legs are executed **sequentially, not concurrently, on purpose**: if
the buy leg fails, nothing was opened and the bot just logs and moves on. If
the buy leg fills but the sell/hedge leg then fails, the bot is left holding
an unhedged position it cannot safely auto-unwind - so it immediately trips
the kill switch and halts all trading until a human looks at it, rather than
guessing at a recovery action with real money on the line.

See `src/babayaga/engine.py` for the implementation and `src/babayaga/factory.py`
for how each venue type (EVM/Jupiter/MT5) is wired into the same uniform
`get_quote`/`place_order` interface the engine drives.

## Safety

**This bot can lose real money with no human in the loop.** It is designed
to trade live by default once you give it credentials - that's a deliberate
tradeoff for sub-second reaction time, not an oversight. Mitigations built in:

- **`dry_run` defaults to `true`** in `config/config.yaml`. The engine still
  runs the full scan/detect/risk-check pipeline and logs what it *would* have
  done, but never calls into a wallet, RPC, or MT5 terminal to place an order.
- **Going live requires an explicit, redundant opt-in**: `dry_run: false` in
  `config.yaml` *and* `DRY_RUN=false` in `.env`. Missing private keys or RPC
  URLs for any venue you've configured will raise a `RuntimeError` and refuse
  to start, rather than failing mid-trade.
- **File-based kill switch**: `touch kill_switch.flag` (path configurable via
  `engine.kill_switch_file`) halts trading before the next tick - no restart
  needed to stop. Once tripped, it does **not** self-clear when you delete
  the file; that's deliberate, so a halt always gets a deliberate restart
  rather than silently resuming the moment the file disappears.
- **Automatic kill switch on unhedged-leg failure**: if a buy leg fills but
  its paired sell/hedge leg then fails, the bot halts itself immediately
  (`trip_reason: unhedged_leg_failure`) instead of continuing to trade around
  an open, unhedged position. Same persistence as above - only a process
  restart clears it (a daily-loss trip is the one exception: it clears
  automatically at the next day rollover).
- **Daily loss cap and position limits**: `risk.max_daily_loss_usd`,
  `risk.max_position_usd`, and `risk.max_open_positions` in `config.yaml` are
  enforced before every trade, not just monitored after the fact.
- **Placeholder-key rejection**: `EvmWallet`/`SolanaWallet` refuse to load if
  given the literal placeholder strings from `.env.example`, so you can't
  accidentally go live with no real key configured.

None of this makes live trading risk-free. Start in dry-run, watch
`trades.jsonl` for a while, and only fund a wallet with what you're prepared
to lose. The contract addresses in `config/config.yaml` are mainnet
addresses current as of this writing - verify each one against the
project's own docs/explorer before trusting it with funds; routers get
upgraded and tokens get redeployed.

## Setup

Requires Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Optional, only if you're using the corresponding venues:
pip install -e ".[solana]"   # Jupiter/Raydium/Orca
pip install -e ".[mt5]"      # MetaTrader 5 hedge leg (Windows/Wine only)

cp .env.example .env
# edit .env: fill in real RPC URLs and (only when you're ready to go live)
# your private key(s) and/or MT5 login
```

Review `config/config.yaml` - it has no secrets and is safe to version
control, but it does define which pairs/venues run, your risk limits, and
trade sizes. The shipped config trades small notional ($100-200/trade) across
three example pairs; adjust `size_base` and the `risk` block before changing
that.

## Running

```bash
# Dry run (default) - quotes, decides, logs to trades.jsonl, never signs/submits:
babayaga

# Single tick, useful for sanity-checking a config change:
babayaga --once

# Live trading - requires DRY_RUN=false in .env AND dry_run: false in
# config.yaml, plus the secrets for every venue you've configured:
babayaga --live
```

`--dry-run` forces dry-run regardless of config/env (handy for testing a
config that's otherwise set up for live). `--config`/`--env` point at
alternate files; `--log-level` controls verbosity. Run `babayaga --help` for
the full list.

Trade history is appended to `trades.jsonl` (one JSON object per completed
round-trip, including dry-run ones) for auditing and PnL review.

## Configuration reference

- **`engine.poll_interval_ms`**: how often each pair is rescanned.
- **`engine.kill_switch_file`**: path checked at the start of every tick.
- **`risk.*`**: `min_profit_bps` (net profit floor to act on), `max_position_usd`
  (per-trade notional cap, used to clamp size down - never up), `max_daily_loss_usd`,
  `max_open_positions`, `slippage_bps` (added to estimated cost as a buffer).
- **`chains`**: one entry per EVM/Solana chain, naming the `.env` variable that
  holds its RPC URL.
- **`venues`**: one entry per tradeable venue. `kind` is one of `evm_v2_router`,
  `evm_v3_quoter`, `jupiter_aggregator`, or `mt5`; the rest of the fields
  depend on `kind` (router/quoter address, fee, a static gas-cost-in-USD
  estimate used in profit math, etc).
- **`pairs`**: each pair lists 2+ `legs` (each a `venue`, plus an optional MT5
  `symbol` like `XAUUSD`). Set `hedge: true` when the second leg is an
  offsetting MT5 position rather than a sale of the same asset.
- **`tokens`**: per-chain token symbol -> contract address map used by the EVM
  feeds/executors.

## Testing

```bash
source .venv/bin/activate
python3 -m pytest tests/ -v
```

Tests run against fake venue runtimes (no real RPC, wallet, or MT5
connection) and cover the opportunity math, risk manager limits and kill
switch, wallet key validation, config load/validation precedence, the
factory's venue-wiring and fail-fast checks, and the engine's scan/detect/
execute loop including both leg-failure paths.
