from babayaga.agents.coordinator import Coordinator
from babayaga.agents.risk import RiskAgent, RiskLimits
from babayaga.agents.sentiment import NeutralSentiment, SentimentAgent
from babayaga.agents.technical import TechnicalAgent
from babayaga.kernel.events import Candle, Side


def _uptrend(n=80, start=1.10, step=0.001):
    out = []
    price = start
    for i in range(n):
        o = price
        price = price + step
        c = price
        out.append(Candle("EUR/USD", float(i), o, max(o, c) + 0.0005, min(o, c) - 0.0005, c, 1000))
    return out


def _downtrend(n=80, start=1.20, step=0.001):
    return _uptrend(n, start, -step)


def test_technical_agent_is_bullish_on_uptrend():
    sig = TechnicalAgent().evaluate("EUR/USD", _uptrend())
    assert sig is not None
    assert sig.side is Side.BUY
    assert sig.confidence > 0


def test_technical_agent_is_bearish_on_downtrend():
    sig = TechnicalAgent().evaluate("EUR/USD", _downtrend())
    assert sig is not None
    assert sig.side is Side.SELL


def test_technical_agent_needs_enough_data():
    assert TechnicalAgent().evaluate("EUR/USD", _uptrend(n=5)) is None


def test_sentiment_agent_neutral_source_is_flat():
    agent = SentimentAgent(source=NeutralSentiment())
    sig = agent.evaluate("EUR/USD", _uptrend())
    assert sig is not None
    assert sig.side is Side.FLAT


def test_risk_agent_sizes_by_fractional_risk():
    risk = RiskAgent(RiskLimits(risk_per_trade=0.01, atr_stop_mult=2.0, min_confidence=0.0))
    hist = _uptrend()
    d = risk.assess("EUR/USD", Side.BUY, confidence=1.0, rationale="t",
                    history=hist, equity=100_000, current_units=0)
    assert d.side is Side.BUY
    assert d.size > 0
    assert d.stop_loss is not None and d.stop_loss < hist[-1].close
    assert d.take_profit is not None and d.take_profit > hist[-1].close


def test_risk_agent_vetoes_low_confidence():
    risk = RiskAgent(RiskLimits(min_confidence=0.5))
    d = risk.assess("EUR/USD", Side.BUY, confidence=0.1, rationale="weak",
                    history=_uptrend(), equity=100_000, current_units=0)
    assert d.side is Side.FLAT
    assert d.size == 0


def test_risk_drawdown_breaker_halts_trading():
    risk = RiskAgent(RiskLimits(max_drawdown_pct=10.0, min_confidence=0.0))
    risk.update_equity(100_000)
    risk.update_equity(80_000)  # 20% drawdown from peak
    assert risk.halted
    d = risk.assess("EUR/USD", Side.BUY, confidence=1.0, rationale="t",
                    history=_uptrend(), equity=80_000, current_units=0)
    assert d.side is Side.FLAT
    assert "HALT" in d.rationale


def test_coordinator_fuses_agreeing_specialists():
    specialists = [TechnicalAgent(), SentimentAgent()]
    coord = Coordinator(specialists, RiskAgent(RiskLimits(min_confidence=0.0)))
    decision, signals = coord.decide("EUR/USD", _uptrend(), equity=100_000, current_units=0)
    assert len(signals) >= 1
    assert decision.side is Side.BUY
