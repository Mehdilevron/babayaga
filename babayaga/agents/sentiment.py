"""Sentiment / order-flow agent.

Real-world sentiment comes from news, economic calendars, positioning data or an
LLM reading headlines. None of that exists on the simulated feed, so this agent
is built around a **pluggable ``SentimentSource``**. The default source derives a
proxy sentiment from recent price flow (return skew and volume-weighted drift) —
clearly a stand-in, not real news. Swap in a real source (e.g. an LLM that scores
headlines, or a broker's positioning feed) without changing the agent.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from babayaga.agents.base import SpecialistAgent
from babayaga.kernel.events import Candle, Side, Signal


class SentimentSource(ABC):
    """Returns a sentiment score in [-1, +1] with a short rationale."""

    @abstractmethod
    def score(self, symbol: str, history: Sequence[Candle]) -> tuple[float, str]:
        raise NotImplementedError


class FlowProxySentiment(SentimentSource):
    """Proxy sentiment from recent price/volume flow (a placeholder for news).

    Positive when recent bars close near their highs on rising volume; negative
    when they close near their lows. This is a microstructure heuristic, not a
    fundamental view — replace it with a real source for production use.
    """

    def __init__(self, lookback: int = 20) -> None:
        self.lookback = lookback

    def score(self, symbol: str, history: Sequence[Candle]) -> tuple[float, str]:
        window = list(history)[-self.lookback :]
        if len(window) < 5:
            return 0.0, "insufficient flow data"
        closeness = []
        for c in window:
            rng = c.high - c.low
            if rng <= 0:
                closeness.append(0.0)
            else:
                # -1 (closed at low) .. +1 (closed at high)
                closeness.append((c.close - (c.high + c.low) / 2) / (rng / 2))
        vols = [c.volume for c in window] or [1.0]
        avg_vol = sum(vols) / len(vols)
        weighted = sum(cl * (v / avg_vol) for cl, v in zip(closeness, vols)) / len(window)
        score = max(-1.0, min(1.0, weighted))
        tone = "risk-on" if score > 0 else "risk-off"
        return score, f"flow proxy {tone} ({score:+.2f})"


class NeutralSentiment(SentimentSource):
    """Always neutral — use when no real sentiment source is wired up."""

    def score(self, symbol: str, history: Sequence[Candle]) -> tuple[float, str]:
        return 0.0, "no sentiment source configured"


class SentimentAgent(SpecialistAgent):
    name = "sentiment"

    def __init__(self, source: SentimentSource | None = None, weight: float = 0.7) -> None:
        self.source = source or FlowProxySentiment()
        self.weight = weight

    def evaluate(self, symbol: str, history: Sequence[Candle]) -> Signal | None:
        if len(history) < 5:
            return None
        score, rationale = self.source.score(symbol, history)
        side = Side.BUY if score > 0.05 else Side.SELL if score < -0.05 else Side.FLAT
        return Signal(
            agent=self.name,
            symbol=symbol,
            side=side,
            confidence=min(1.0, abs(score)),
            rationale=rationale,
            features={"sentiment": round(score, 4)},
        )
