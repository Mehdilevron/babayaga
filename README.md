# BabaYaga OS

**An AI "operating system" for algorithmic forex trading.**

BabaYaga is a small, self-contained trading OS built around a multi-agent
workflow, a persistent memory layer, a live coordination bus, and a pluggable
integration layer. It boots, trades a simulated EUR/USD market, and passes its
test suite using **nothing but the Python standard library** — no `pip install`
required to run the core.

> ⚠️ **Paper trading only.** Every order goes to an in-memory paper broker. No
> code path reaches a real venue. Real broker/data adapters ship as documented
> *stubs* that deliberately refuse to trade until you implement and vet them
> yourself. There is a hard `allow_live_trading` safety guard that stays off.

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
| **Integration** | `babayaga.integration` | Pluggable `MarketDataFeed`s (`SimulatedFeed`, `ReplayFeed`, `OandaFeed` stub) and `Broker`s (`PaperBroker`, `OandaBroker` stub). |
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

---

## Extending it

Everything is an interface, so you plug in new behaviour without touching the
kernel:

- **New analyst** → subclass `SpecialistAgent`, implement `evaluate(...)`, add it
  to the `Coordinator`. See `examples/custom_agent.py`.
- **Real sentiment / news / LLM** → implement `SentimentSource.score(...)` (e.g.
  an LLM scoring headlines) and pass it to `SentimentAgent`.
- **Real market data** → implement `MarketDataFeed.stream()` (the `OandaFeed`
  stub shows where).
- **Real broker** → implement the `Broker` interface (the `OandaBroker` stub
  shows where). *This is the only place real money becomes possible; treat it
  with care.*
- **Observe the stream** → `os_.on(Topic.FILL, handler)` to feed a dashboard,
  logger, or alert.

---

## Testing

```bash
pip install pytest      # only needed to run the tests
pytest
```

29 tests cover indicators, the paper broker (P&L, spread, stops/targets),
memory, each agent, and full OS integration (determinism, event-bus delivery,
replay feeds).

---

## Going live (what would be required)

This repo intentionally stops short of live trading. To take it there you would
need to: implement a real `Broker` + `MarketDataFeed` against a broker API,
supply credentials via environment/secrets, add reconciliation and idempotent
order handling, and complete your own compliance/risk review. `allow_live_trading`
gates the run loop and defaults to `False` for a reason.

## License

MIT
