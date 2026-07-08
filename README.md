# BabaYaga OS

**An AI "operating system" for algorithmic forex trading.**

BabaYaga is a small, self-contained trading OS built around a multi-agent
workflow, a persistent memory layer, a live coordination bus, and a pluggable
integration layer. It boots, trades a simulated EUR/USD market, and passes its
test suite using **nothing but the Python standard library** — no `pip install`
required to run the core.

> ⚠️ **Paper by default.** Out of the box every order goes to an in-memory paper
> broker — no code path reaches a real venue. A real OANDA adapter is included
> but defaults to the **practice** (demo, virtual-money) environment; live
> real-money trading is gated behind both `practice=False` *and* an explicit
> `confirm_live=True`, and stays off unless you deliberately turn it on.

---

## Why "OS"?

The system is organised like an operating system, with four layers the user
asked for:

```
                         ┌─────────────────────────────────────────┐
                         │            TradingOS (kernel)            │
                         │   boots layers, runs coordination loop   │
                         └─────────────────────────────────────────┘
   ┌───────────────┐   TICK    ┌──────────────────────────────┐  DECISION  ┌───────────────┐
   │  INTEGRATION  │ ────────▶ │        AGENT WORKFLOW         │ ─────────▶ │  INTEGRATION  │
   │  market data  │           │  technical ┐                 │            │  paper broker │
   │  (sim/replay/ │           │  sentiment ┼▶ coordinator ▶  │  ORDER     │  fills, P&L,  │
   │   OANDA stub) │           │            │   risk  ▶ exec  │ ─────────▶ │  stops/targets│
   └───────────────┘           └──────────────────────────────┘            └───────────────┘
           │                             │        │                                │
           └───────────────┬─────────────┴────────┴────────────────┬───────────────┘
                           ▼                                        ▼
                   ┌──────────────────┐                   ┌──────────────────┐
                   │  KERNEL: EventBus │  every message    │  MEMORY: SQLite  │
                   │  pub/sub coord.   │ ────────────────▶ │  ticks/signals/  │
                   │  (live coord.)    │                   │  decisions/fills │
                   └──────────────────┘                   │  + knowledge KV  │
                                                          └──────────────────┘
```

| Layer | Package | What it does |
|-------|---------|--------------|
| **Kernel / live coordination** | `babayaga.kernel` | Async pub/sub `EventBus` + typed messages (`Candle`, `Signal`, `Decision`, `Order`, `Fill`). Agents and feeds never call each other directly. |
| **Memory** | `babayaga.memory` | SQLite journal of every tick/signal/decision/fill, plus a key/value knowledge base agents use to persist learned state across runs. |
| **Integration** | `babayaga.integration` | Pluggable `MarketDataFeed`s (`SimulatedFeed`, `ReplayFeed`, real `OandaFeed`) and `Broker`s (`PaperBroker`, real `OandaBroker` — practice/demo by default). |
| **Agents** | `babayaga.agents` | `TechnicalAgent` + `SentimentAgent` → `Coordinator` (weighted vote) → `RiskAgent` (fractional-risk sizing, ATR stops, drawdown breaker) → `ExecutionAgent`. |

---

## Quickstart

```bash
# Run a simulated paper-trading session (no dependencies needed)
python -m babayaga

# Watch the agents coordinate, tune the run
python -m babayaga --steps 800 --seed 3 --risk 0.02 --verbose

# Persist memory to disk so it survives across runs
python -m babayaga --memory ./babayaga-memory.sqlite
```

Example output:

```
BabaYaga OS — paper trading EUR/USD  (500 bars, seed 7)
------------------------------------------------------------------------
ticks=500  signals=966  decisions=500  fills=58
Start equity :   100,000.00
End equity   :   112,685.16
Total return :       12.69%
Max drawdown :        1.33%
Sharpe       :         3.41
Trades closed:           40
Win rate     :       62.50%
------------------------------------------------------------------------
NOTE: simulated market, paper broker. No real orders were placed.
```

> The simulated feed is a regime-switching random walk. Positive returns here
> reflect the demo's synthetic data — **not** a claim of real-world edge.

### Programmatic use

```python
from babayaga import Config, TradingOS

os_ = TradingOS(Config(symbols=("EUR/USD", "GBP/USD"), sim_steps=500))
perf = os_.run_backtest()
print(perf.as_dict())
os_.shutdown()
```

### Live web dashboard

A dependency-free web server that subscribes to the kernel event bus and streams
it to the browser over Server-Sent Events — watch equity, positions, agent
signals and fills update live:

```bash
python -m babayaga.dashboard --port 8765 --steps 800 --interval 0.06
# then open http://127.0.0.1:8765
```

The dashboard is just another *observer* on the bus (`os_.on(topic, handler)`) —
it never touches trading logic, which is the whole point of the coordination
layer.

### Real OANDA practice account (optional, demo money)

`babayaga.integration.oanda` is a working OANDA v3 REST adapter (stdlib
`urllib`, no extra installs). It defaults to OANDA's **practice** environment —
a free demo account with virtual money. Real funds are impossible unless you
construct it with `practice=False` *and* `confirm_live=True`.

```bash
export OANDA_API_TOKEN=...        # from your free practice account
export OANDA_ACCOUNT_ID=101-...
```

```python
import asyncio
from babayaga import Config, TradingOS
from babayaga.integration.oanda import OandaClient, OandaFeed, OandaBroker

client = OandaClient.from_env()                 # practice by default
os_ = TradingOS(Config(symbols=("EUR/USD",), sim_steps=0))
os_.broker = OandaBroker(client)                # demo broker (virtual money)
os_.execution.broker = os_.broker
os_.attach_feed("EUR/USD", OandaFeed(client, "EUR/USD", granularity="M1"))
asyncio.run(os_.run())
```

---

## Extending it

Everything is an interface, so you plug in new behaviour without touching the
kernel:

- **New analyst** → subclass `SpecialistAgent`, implement `evaluate(...)`, add it
  to the `Coordinator`. See `examples/custom_agent.py`.
- **Real sentiment / news / LLM** → implement `SentimentSource.score(...)` (e.g.
  an LLM scoring headlines) and pass it to `SentimentAgent`.
- **Real market data** → implement `MarketDataFeed.stream()` (`OandaFeed` is a
  full working example).
- **Real broker** → implement the `Broker` interface (`OandaBroker` is a full
  working example). *This is the only place real money becomes possible; it is
  gated behind `practice=True` and an explicit `confirm_live=True`.*
- **Observe the stream** → `os_.on(Topic.FILL, handler)` to feed a dashboard,
  logger, or alert.

---

## Testing

```bash
pip install pytest      # only needed to run the tests
pytest
```

38 tests cover indicators, the paper broker (P&L, spread, stops/targets),
memory, each agent, full OS integration (determinism, event-bus delivery,
replay feeds), and the OANDA adapter (offline, via a fake transport).

---

## Going live (what would be required)

This repo intentionally stops short of live trading. To take it there you would
need to: implement a real `Broker` + `MarketDataFeed` against a broker API,
supply credentials via environment/secrets, add reconciliation and idempotent
order handling, and complete your own compliance/risk review. `allow_live_trading`
gates the run loop and defaults to `False` for a reason.

## License

MIT
