"""BabaYaga OS — an AI operating system for algorithmic forex trading.

BabaYaga is organised like a small operating system:

* **Kernel** (``babayaga.kernel``) — an async event bus + scheduler that lets
  data feeds, agents and the broker communicate in real time. This is the
  "live coordination" layer.
* **Memory** (``babayaga.memory``) — a persistent SQLite-backed store of ticks,
  signals, decisions, trades and learned market regimes that agents read from
  and write to across runs.
* **Integration** (``babayaga.integration``) — pluggable adapters for market
  data and brokers. Ships with a runnable simulated data feed and a paper
  broker; real brokers (e.g. OANDA) are provided as documented stubs.
* **Agents** (``babayaga.agents``) — a multi-agent workflow: specialist agents
  (technical, sentiment, risk, execution) coordinated by a supervisor that
  fuses their views into a single trading decision.

Everything runs on the Python standard library — no third-party packages are
required — so the whole OS boots, trades on simulated data and passes its test
suite out of the box. It is **paper-trading only**; no order ever reaches a real
venue unless you deliberately wire up a live broker adapter and supply keys.
"""

from babayaga.config import Config
from babayaga.os import TradingOS

__all__ = ["Config", "TradingOS"]
__version__ = "0.1.0"
