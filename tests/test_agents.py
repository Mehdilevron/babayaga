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


def test_sentiment_handles_zero_volume_bars():
    # Real FX daily history often has no volume column; must not divide by zero.
    from babayaga.agents.sentiment import FlowProxySentiment

    bars = [
        Candle("EUR/USD", float(i), 1.10, 1.101, 1.099, 1.1005, volume=0.0)
        for i in range(25)
    ]
    score, rationale = FlowProxySentiment().score("EUR/USD", bars)
    assert -1.0 <= score <= 1.0
    assert rationale


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


def test_regime_filter_vetoes_chop_and_counter_trend():
    risk = RiskAgent(RiskLimits(min_confidence=0.0, min_trend_strength=1.0))
    up = _uptrend()  # strong uptrend: fast EMA well above slow

    # With the trend, a BUY is allowed.
    d = risk.assess("EUR/USD", Side.BUY, 1.0, "t", up, 100_000, 0)
    assert d.side is Side.BUY and d.size > 0

    # Against the trend, a SELL is vetoed even at full confidence.
    d2 = risk.assess("EUR/USD", Side.SELL, 1.0, "t", up, 100_000, 0)
    assert d2.side is Side.FLAT
    assert "trend" in d2.rationale

    # In flat/choppy data the EMAs sit on top of each other -> no trade.
    flat = [
        Candle("EUR/USD", float(i), 1.10, 1.1005, 1.0995, 1.10, 1000)
        for i in range(80)
    ]
    d3 = risk.assess("EUR/USD", Side.BUY, 1.0, "t", flat, 100_000, 0)
    assert d3.side is Side.FLAT
    assert "chop" in d3.rationale


def test_regime_filter_off_by_default():
    # Default limits keep the filter disabled (min_trend_strength=0.0).
    risk = RiskAgent(RiskLimits(min_confidence=0.0))
    d = risk.assess("EUR/USD", Side.SELL, 1.0, "t", _uptrend(), 100_000, 0)
    assert d.side is Side.SELL  # counter-trend allowed when filter is off


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


def test_execution_flip_cooldown_blocks_rapid_reversals():
    from babayaga.agents.execution import ExecutionAgent
    from babayaga.integration.broker import PaperBroker
    from babayaga.kernel.events import Decision

    broker = PaperBroker(starting_cash=100_000, spread=0.0)
    ex = ExecutionAgent(broker, min_flip_bars=3)
    buy = Decision("EUR/USD", Side.BUY, 1000, 0.5, "t")
    sell = Decision("EUR/USD", Side.SELL, 1000, 0.5, "t")

    assert len(ex.execute(buy, 0, 1.10)) == 1        # bar 1: open long
    assert ex.execute(sell, 1000, 1.10) == []        # bar 2: reversal blocked
    assert ex.execute(sell, 1000, 1.10) == []        # bar 3: still blocked
    fills = ex.execute(sell, 1000, 1.10)             # bar 4: cooldown elapsed
    assert len(fills) == 2                            # close + open short


def test_execution_cooldown_never_blocks_closing_to_flat():
    from babayaga.agents.execution import ExecutionAgent
    from babayaga.integration.broker import PaperBroker
    from babayaga.kernel.events import Decision

    broker = PaperBroker(starting_cash=100_000, spread=0.0)
    ex = ExecutionAgent(broker, min_flip_bars=10)
    buy = Decision("EUR/USD", Side.BUY, 1000, 0.5, "t")
    flat = Decision("EUR/USD", Side.FLAT, 0.0, 0.0, "risk off")
    ex.execute(buy, 0, 1.10)
    fills = ex.execute(flat, 1000, 1.10)  # next bar: close is always allowed
    assert len(fills) == 1


def test_simulated_feed_gaps_and_determinism():
    import asyncio

    from babayaga.integration.market_data import SimulatedFeed

    async def closes(feed, n):
        out = []
        async for c in feed.stream():
            out.append((c.open, c.close))
            if len(out) >= n:
                break
        return out

    a = asyncio.run(closes(SimulatedFeed(steps=0, seed=9, gap_prob=0.05), 1500))
    b = asyncio.run(closes(SimulatedFeed(steps=0, seed=9, gap_prob=0.05), 1500))
    assert a == b  # deterministic for a given seed
    gaps = [abs(a[i][0] - a[i - 1][1]) for i in range(1, len(a))]
    assert any(g > 1e-12 for g in gaps)  # some bars open away from prior close


def test_coordinator_fuses_agreeing_specialists():
    specialists = [TechnicalAgent(), SentimentAgent()]
    coord = Coordinator(specialists, RiskAgent(RiskLimits(min_confidence=0.0)))
    decision, signals = coord.decide("EUR/USD", _uptrend(), equity=100_000, current_units=0)
    assert len(signals) >= 1
    assert decision.side is Side.BUY
