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


def test_multi_pair_feeds_interleave_not_sequential():
    # Regression: with interval=0 feeds used to run to completion one after
    # another, so "multi-pair" backtests were secretly sequential.
    from babayaga.kernel.events import Topic

    os_ = TradingOS(Config(symbols=("EUR/USD", "GBP/USD"), sim_steps=50, sim_seed=1))
    order: list[str] = []
    os_.on(Topic.TICK, lambda c: order.append(c.symbol))
    os_.run_backtest()
    first_half = order[: len(order) // 2]
    # Both symbols must appear early — not one symbol's full history first.
    assert "EUR/USD" in first_half and "GBP/USD" in first_half
    switches = sum(1 for a, b in zip(order, order[1:]) if a != b)
    assert switches > 10  # round-robin, not two solid blocks (1 switch)


def test_protective_exits_reach_bus_and_memory():
    # Regression: broker-side stop-loss fills were invisible to bus/memory.
    import asyncio as aio

    from babayaga.integration.market_data import ReplayFeed
    from babayaga.kernel.events import Topic

    # A rise (open long via manual order) then a crash through the stop.
    rows = []
    price = 1.10
    for i in range(80):
        price += 0.001
        rows.append((float(i), price, price + 0.0005, price - 0.0005, price, 0.0))
    for i in range(80, 90):  # crash
        price -= 0.01
        rows.append((float(i), price, price + 0.0005, price - 0.0005, price, 0.0))

    os_ = TradingOS(Config(symbols=("EUR/USD",), sim_steps=0))
    os_.attach_feed("EUR/USD", ReplayFeed.from_rows("EUR/USD", rows))
    seen: list = []
    os_.on(Topic.FILL, lambda f: seen.append(f))
    aio.run(os_.run())
    protective = [f for f in seen if f.order_reason in ("stop_loss", "take_profit")]
    # The trend strategy opens long on the rise; the crash must produce a
    # VISIBLE stop-loss fill on the bus and in memory.
    assert protective, "no protective fill reached the bus"
    mem_reasons = [f["reason"] for f in os_.memory.fills()]
    assert any(r in ("stop_loss", "take_profit") for r in mem_reasons)
    os_.shutdown()


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
