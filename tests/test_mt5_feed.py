"""Mt5Feed tests: trade_mode-disabled and stale-tick rejection, and the happy
path - using a fake MetaTrader5 module injected via sys.modules, since the
real package is a Windows-only optional dependency not installed here."""

from __future__ import annotations

import sys
import time
import types

import pytest

from babayaga.feeds.mt5_feed import Mt5Feed, Mt5Session


def _fake_mt5(*, trade_mode=1, disabled_mode=0, tick_time=None, bid=100.0, ask=100.5):
    """Builds a fake MetaTrader5 module with just enough surface for get_quote."""
    module = types.ModuleType("MetaTrader5")
    module.SYMBOL_TRADE_MODE_DISABLED = disabled_mode

    symbol_info = types.SimpleNamespace(trade_mode=trade_mode)
    tick = types.SimpleNamespace(bid=bid, ask=ask, time=tick_time if tick_time is not None else time.time())

    module.symbol_select = lambda symbol, enable: True
    module.symbol_info = lambda symbol: symbol_info
    module.symbol_info_tick = lambda symbol: tick
    module.last_error = lambda: (0, "no error")
    return module


def _connected_session() -> Mt5Session:
    session = Mt5Session(login=1, password="pw", server="srv")
    session._connected = True  # skip connect()/initialize() - not under test here
    return session


@pytest.fixture(autouse=True)
def _clean_mt5_module(monkeypatch):
    monkeypatch.delitem(sys.modules, "MetaTrader5", raising=False)
    yield
    monkeypatch.delitem(sys.modules, "MetaTrader5", raising=False)


@pytest.mark.asyncio
async def test_trade_mode_disabled_raises(monkeypatch):
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5(trade_mode=0, disabled_mode=0))
    feed = Mt5Feed("mt5_hedge", fee_bps=2.0, session=_connected_session())

    with pytest.raises(RuntimeError, match="trading disabled"):
        await feed.get_quote("PAXG", "USDC", 1.0, "XAUUSD")


@pytest.mark.asyncio
async def test_stale_tick_raises(monkeypatch):
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5(tick_time=time.time() - 999))
    feed = Mt5Feed("mt5_hedge", fee_bps=2.0, session=_connected_session(), stale_after_s=120.0)

    with pytest.raises(RuntimeError, match="stale"):
        await feed.get_quote("PAXG", "USDC", 1.0, "XAUUSD")


@pytest.mark.asyncio
async def test_fresh_tick_returns_quote(monkeypatch):
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5(bid=2400.1, ask=2400.6))
    feed = Mt5Feed("mt5_hedge", fee_bps=2.0, session=_connected_session())

    quote = await feed.get_quote("PAXG", "USDC", 1.0, "XAUUSD")

    assert quote.venue == "mt5_hedge"
    assert quote.base == "PAXG"
    assert quote.quote == "USDC"
    assert quote.bid == 2400.1
    assert quote.ask == 2400.6
    assert quote.fee_bps == 2.0


@pytest.mark.asyncio
async def test_symbol_select_failure_raises(monkeypatch):
    fake = _fake_mt5()
    fake.symbol_select = lambda symbol, enable: False
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    feed = Mt5Feed("mt5_hedge", fee_bps=2.0, session=_connected_session())

    with pytest.raises(RuntimeError, match="symbol_select"):
        await feed.get_quote("PAXG", "USDC", 1.0, "XAUUSD")
