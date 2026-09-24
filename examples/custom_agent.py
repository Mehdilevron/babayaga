"""Example: add a custom specialist agent and an LLM-style sentiment source.

Run with:  python examples/custom_agent.py

This shows the two most common extension points:
  1. A brand-new specialist agent (breakout/Donchian channel).
  2. A custom SentimentSource — here a stub standing in for an LLM that would
     read news headlines and return a score in [-1, +1].
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

# Allow running directly ("python examples/custom_agent.py") without installing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from babayaga import Config, TradingOS
from babayaga.agents.base import SpecialistAgent
from babayaga.agents.sentiment import SentimentAgent, SentimentSource
from babayaga.agents.technical import TechnicalAgent
from babayaga.kernel.events import Candle, Side, Signal, Topic


class BreakoutAgent(SpecialistAgent):
    """Buys N-bar highs, sells N-bar lows (a Donchian breakout)."""

    name = "breakout"

    def __init__(self, lookback: int = 20, weight: float = 0.8) -> None:
        self.lookback = lookback
        self.weight = weight

    def evaluate(self, symbol: str, history: Sequence[Candle]) -> Signal | None:
        if len(history) < self.lookback + 1:
            return None
        window = list(history)[-(self.lookback + 1) : -1]
        highest = max(c.high for c in window)
        lowest = min(c.low for c in window)
        price = history[-1].close
        if price > highest:
            return Signal(self.name, symbol, Side.BUY, 0.7, f"broke {self.lookback}-bar high")
        if price < lowest:
            return Signal(self.name, symbol, Side.SELL, 0.7, f"broke {self.lookback}-bar low")
        return Signal(self.name, symbol, Side.FLAT, 0.0, "inside range")


class HeadlineLLMSentiment(SentimentSource):
    """Stub for an LLM that scores news headlines.

    Replace ``score`` with a real call: fetch recent headlines for ``symbol``,
    ask an LLM to rate them from -1 (very bearish) to +1 (very bullish), and
    return ``(score, rationale)``.
    """

    def score(self, symbol: str, history: Sequence[Candle]) -> tuple[float, str]:
        # Deterministic placeholder so the example runs offline.
        return 0.2, f"[stub LLM] mildly bullish headlines for {symbol}"


def main() -> None:
    os_ = TradingOS(Config(sim_steps=400, sim_seed=11))

    # Swap in a richer committee: technical + breakout + LLM-sentiment.
    os_.coordinator.specialists = [
        TechnicalAgent(),
        BreakoutAgent(),
        SentimentAgent(source=HeadlineLLMSentiment()),
    ]

    os_.on(Topic.FILL, lambda f: print(
        f"FILL {f.side.value.upper():4} {f.size:>10,.0f} @ {f.price:.5f}  {f.order_reason[:40]}"
    ))

    perf = os_.run_backtest()
    print("\nPerformance:", perf.as_dict())
    os_.shutdown()


if __name__ == "__main__":
    main()
