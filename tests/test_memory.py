from babayaga.kernel.events import Candle, Decision, Fill, Side, Signal
from babayaga.memory.store import MemoryStore


def _candle(sym="EUR/USD", ts=1.0, close=1.10):
    return Candle(sym, ts, close, close + 0.001, close - 0.001, close, 1000)


def test_tick_roundtrip_and_recent_closes():
    m = MemoryStore(":memory:")
    for i in range(5):
        m.record_tick(_candle(ts=float(i), close=1.10 + i * 0.001))
    closes = m.recent_closes("EUR/USD", limit=3)
    assert closes == [1.102, 1.103, 1.104]  # chronological order, last 3
    m.close()


def test_knowledge_base_persists_and_updates():
    m = MemoryStore(":memory:")
    assert m.recall("regime", default="unknown") == "unknown"
    m.remember("regime", {"state": "trending", "vol": 0.12})
    assert m.recall("regime")["state"] == "trending"
    m.remember("regime", {"state": "ranging"})
    assert m.recall("regime")["state"] == "ranging"
    m.close()


def test_signal_and_fill_counts():
    m = MemoryStore(":memory:")
    m.record_signal(Signal("technical", "EUR/USD", Side.BUY, 0.6, "trend up"))
    m.record_decision(Decision("EUR/USD", Side.BUY, 1000, 0.6, "go long"))
    m.record_fill(Fill("EUR/USD", Side.BUY, 1000, 1.10))
    counts = m.counts()
    assert counts["signals"] == 1
    assert counts["decisions"] == 1
    assert counts["fills"] == 1
    m.close()


def test_confidence_is_clamped():
    s = Signal("x", "EUR/USD", Side.BUY, 5.0, "over")
    assert s.confidence == 1.0
    s2 = Signal("x", "EUR/USD", Side.SELL, -1.0, "under")
    assert s2.confidence == 0.0
