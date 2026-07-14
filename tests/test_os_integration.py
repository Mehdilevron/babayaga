import asyncio

from babayaga import Config, TradingOS
from babayaga.integration.market_data import ReplayFeed
from babayaga.kernel.events import Candle, Side, Topic


def test_full_session_runs_and_reports():
    cfg = Config(sim_steps=300, sim_seed=7)
    os_ = TradingOS(cfg)
    perf = os_.run_backtest()
    counts = os_.memory.counts()
    assert counts["ticks"] == 300
    assert counts["decisions"] == 300
    assert counts["signals"] > 0
    assert perf.end_equity > 0
    os_.shutdown()


def test_deterministic_given_seed():
    a = TradingOS(Config(sim_steps=200, sim_seed=42)).run_backtest()
    b = TradingOS(Config(sim_steps=200, sim_seed=42)).run_backtest()
    assert a.end_equity == b.end_equity
    assert a.num_trades == b.num_trades


def test_event_bus_observers_receive_stream():
    os_ = TradingOS(Config(sim_steps=100, sim_seed=1))
    seen = {"tick": 0, "decision": 0, "account": 0}
    os_.on(Topic.TICK, lambda _c: seen.__setitem__("tick", seen["tick"] + 1))
    os_.on(Topic.DECISION, lambda _d: seen.__setitem__("decision", seen["decision"] + 1))
    os_.on(Topic.ACCOUNT, lambda _a: seen.__setitem__("account", seen["account"] + 1))
    os_.run_backtest()
    assert seen["tick"] == 100
    assert seen["decision"] == 100
    assert seen["account"] == 100
    os_.shutdown()


def test_simulated_feed_runs_forever_when_steps_zero():
    from babayaga.integration.market_data import SimulatedFeed

    feed = SimulatedFeed(steps=0, seed=1)  # 0 => nonstop

    async def take(n):
        out = []
        async for c in feed.stream():
            out.append(c)
            if len(out) >= n:
                break
        return out

    # It keeps producing well past any fixed bound; we stop it ourselves.
    got = asyncio.run(take(300))
    assert len(got) == 300


def test_replay_feed_drives_the_os():
    # A clean uptrend should end with the agents net long and equity intact.
    rows = []
    price = 1.10
    for i in range(120):
        o = price
        price += 0.001
        c = price
        rows.append((float(i), o, c + 0.0003, o - 0.0003, c, 1000.0))
    feed = ReplayFeed.from_rows("EUR/USD", rows)

    os_ = TradingOS(Config(sim_steps=0))
    os_.attach_feed("EUR/USD", feed)
    asyncio.run(os_.run())
    # It should have opened at least one position over a strong trend.
    assert os_.memory.counts()["fills"] > 0
    os_.shutdown()
