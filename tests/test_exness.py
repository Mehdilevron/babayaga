"""Offline tests for the Exness/MT5 adapter using a fake ``mt5`` module."""

import asyncio
import types

import pytest

from babayaga.integration.exness import (
    ExnessMT5Broker,
    ExnessMT5Feed,
    Mt5Error,
    to_mt5_symbol,
)
from babayaga.kernel.events import Order, Side

# MT5 constant values (as the real package defines them).
DEMO, CONTEST, REAL = 0, 1, 2
RETCODE_DONE = 10009


def _account(trade_mode=DEMO, balance=100.0, equity=100.0):
    return types.SimpleNamespace(
        trade_mode=trade_mode, balance=balance, equity=equity, login=123
    )


def _symbol_info():
    return types.SimpleNamespace(
        volume_min=0.01, volume_max=100.0, volume_step=0.01, trade_contract_size=100.0
    )


class FakeMT5:
    """Mimics the subset of the MetaTrader5 module the adapter uses."""

    ACCOUNT_TRADE_MODE_DEMO = DEMO
    ACCOUNT_TRADE_MODE_REAL = REAL
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    TRADE_ACTION_DEAL = 1
    TRADE_RETCODE_DONE = RETCODE_DONE
    ORDER_TIME_GTC = 0
    ORDER_FILLING_IOC = 1
    TIMEFRAME_M1 = 1

    def __init__(self, trade_mode=DEMO, rates=None, order_retcode=RETCODE_DONE,
                 balance=100.0, equity=100.0):
        self._account = _account(trade_mode, balance=balance, equity=equity)
        self._rates = rates or []
        self._order_retcode = order_retcode
        self.sent_requests = []

    def account_info(self):
        return self._account

    def last_error(self):
        return (0, "ok")

    def symbol_info(self, symbol):
        return _symbol_info()

    def symbol_select(self, symbol, enable):
        return True

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        return self._rates[-count:]

    def order_send(self, request):
        self.sent_requests.append(request)
        return types.SimpleNamespace(
            retcode=self._order_retcode,
            price=request["price"],
            volume=request["volume"],
            order=1,
            comment="ok",
        )


def _bar(t, o, h, l, c, v=100):
    return {"time": float(t), "open": o, "high": h, "low": l, "close": c, "tick_volume": v}


def test_symbol_conversion():
    assert to_mt5_symbol("XAU/USD") == "XAUUSD"
    assert to_mt5_symbol("XAU/USD", "m") == "XAUUSDm"
    assert to_mt5_symbol("EUR/USD") == "EURUSD"


def test_feed_emits_completed_bars_only():
    rates = [
        _bar(1, 2000, 2001, 1999, 2000.5),
        _bar(2, 2000.5, 2002, 2000, 2001.5),
        _bar(3, 2001.5, 2003, 2001, 2002.5),  # last row = in-progress, skipped in warmup
    ]
    feed = ExnessMT5Feed(FakeMT5(rates=rates), "XAU/USD", warmup_bars=3, max_bars=2)

    async def collect():
        out = []
        async for c in feed.stream():
            out.append(c)
        return out

    candles = asyncio.run(collect())
    assert [c.close for c in candles] == [2000.5, 2001.5]
    assert candles[0].symbol == "XAU/USD"


def test_demo_account_trades_freely():
    mt5 = FakeMT5(trade_mode=DEMO)
    broker = ExnessMT5Broker(mt5)
    assert broker.is_live is False
    assert broker.blocked is False
    fill = broker.submit(Order("XAU/USD", Side.BUY, 100), mark_price=2000.0)
    assert fill is not None
    assert fill.price == 2000.0
    # 100 units / 100 per lot = 1.0 lot, BUY type.
    req = mt5.sent_requests[0]
    assert req["volume"] == 1.0
    assert req["type"] == FakeMT5.ORDER_TYPE_BUY
    assert req["symbol"] == "XAUUSD"


def test_real_account_is_blocked_without_confirmation():
    mt5 = FakeMT5(trade_mode=REAL)
    broker = ExnessMT5Broker(mt5)  # confirm_live defaults False
    assert broker.is_live is True
    assert broker.blocked is True
    with pytest.raises(Mt5Error):
        broker.submit(Order("XAU/USD", Side.BUY, 100), mark_price=2000.0)
    # Nothing was ever sent to the terminal.
    assert mt5.sent_requests == []


def test_real_account_trades_when_confirmed():
    mt5 = FakeMT5(trade_mode=REAL)
    broker = ExnessMT5Broker(mt5, confirm_live=True)
    assert broker.blocked is False
    fill = broker.submit(Order("XAU/USD", Side.SELL, 100), mark_price=2000.0)
    assert fill is not None
    assert mt5.sent_requests[0]["type"] == FakeMT5.ORDER_TYPE_SELL


def test_lot_sizing_respects_min_volume():
    mt5 = FakeMT5(trade_mode=DEMO)
    broker = ExnessMT5Broker(mt5)
    # 1 unit / 100 per lot = 0.01 lot -> clamped up to volume_min 0.01.
    broker.submit(Order("XAU/USD", Side.BUY, 1), mark_price=2000.0)
    assert mt5.sent_requests[0]["volume"] == 0.01


def test_stop_and_target_attached_to_request():
    mt5 = FakeMT5(trade_mode=DEMO)
    broker = ExnessMT5Broker(mt5)
    broker.submit(
        Order("XAU/USD", Side.BUY, 100, stop_loss=1990.0, take_profit=2020.0),
        mark_price=2000.0,
    )
    req = mt5.sent_requests[0]
    assert req["sl"] == 1990.0
    assert req["tp"] == 2020.0


def test_rejected_order_returns_none():
    mt5 = FakeMT5(trade_mode=DEMO, order_retcode=10004)  # requote / not done
    broker = ExnessMT5Broker(mt5)
    assert broker.submit(Order("XAU/USD", Side.BUY, 100), mark_price=2000.0) is None


def test_max_lot_caps_order_size():
    mt5 = FakeMT5(trade_mode=DEMO)
    broker = ExnessMT5Broker(mt5, max_lot=0.05)
    # 100 units / 100 per lot = 1.0 lot, but capped to 0.05.
    broker.submit(Order("XAU/USD", Side.BUY, 100), mark_price=2000.0)
    assert mt5.sent_requests[0]["volume"] == 0.05


def test_daily_loss_kill_switch_blocks_new_trades():
    mt5 = FakeMT5(trade_mode=DEMO, balance=100.0, equity=100.0)
    broker = ExnessMT5Broker(mt5, daily_max_loss=10.0)
    # First trade is allowed while within the loss budget.
    assert broker.submit(Order("XAU/USD", Side.BUY, 100), mark_price=2000.0) is not None
    # Simulate the account dropping $15 (> $10 daily cap).
    mt5._account.equity = 85.0
    blocked = broker.submit(Order("XAU/USD", Side.BUY, 100), mark_price=2000.0)
    assert blocked is None
    assert broker.halted_daily is True


def test_daily_guard_inactive_when_unset():
    mt5 = FakeMT5(trade_mode=DEMO, balance=100.0, equity=100.0)
    broker = ExnessMT5Broker(mt5)  # no daily_max_loss
    mt5._account.equity = 1.0  # huge loss
    # Without a configured limit, trading continues.
    assert broker.submit(Order("XAU/USD", Side.BUY, 100), mark_price=2000.0) is not None
    assert broker.halted_daily is False
