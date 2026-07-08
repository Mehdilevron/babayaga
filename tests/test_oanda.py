"""Offline tests for the OANDA adapter using a fake HTTP transport."""

import asyncio

import pytest

from babayaga.integration.oanda import (
    OandaBroker,
    OandaClient,
    OandaError,
    OandaFeed,
    from_oanda_symbol,
    to_oanda_symbol,
    _rfc3339_to_epoch,
)
from babayaga.kernel.events import Order, Side


class FakeClient:
    """Stands in for OandaClient; returns canned responses, records calls."""

    def __init__(self, responses):
        self._responses = responses
        self.calls = []
        self.practice = True
        self.account_id = "101-000-TEST"

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        for matcher, resp in self._responses:
            if matcher in path:
                return resp(body) if callable(resp) else resp
        return {}


def test_symbol_conversion_roundtrip():
    assert to_oanda_symbol("EUR/USD") == "EUR_USD"
    assert from_oanda_symbol("EUR_USD") == "EUR/USD"


def test_rfc3339_parsing():
    epoch = _rfc3339_to_epoch("2024-01-02T03:04:05.123456789Z")
    assert epoch > 0
    assert _rfc3339_to_epoch("0") == 0.0


def test_client_requires_credentials():
    with pytest.raises(OandaError):
        OandaClient(token="", account_id="x")
    with pytest.raises(OandaError):
        OandaClient(token="x", account_id="")


def test_feed_parses_candles():
    candles = {
        "candles": [
            {"complete": True, "time": "2024-01-01T00:00:00.000000000Z",
             "volume": 100, "mid": {"o": "1.1000", "h": "1.1010", "l": "1.0990", "c": "1.1005"}},
            {"complete": True, "time": "2024-01-01T00:01:00.000000000Z",
             "volume": 120, "mid": {"o": "1.1005", "h": "1.1020", "l": "1.1000", "c": "1.1015"}},
            {"complete": False, "time": "2024-01-01T00:02:00.000000000Z",
             "volume": 5, "mid": {"o": "1.1015", "h": "1.1016", "l": "1.1014", "c": "1.1015"}},
        ]
    }
    client = FakeClient([("/candles", candles)])
    feed = OandaFeed(client, "EUR/USD", granularity="M1", max_bars=2)

    async def collect():
        out = []
        async for c in feed.stream():
            out.append(c)
        return out

    got = asyncio.run(collect())
    assert len(got) == 2  # incomplete candle skipped
    assert got[0].symbol == "EUR/USD"
    assert got[0].close == 1.1005
    assert got[1].high == 1.1020


def test_broker_refuses_live_without_confirmation():
    live = OandaClient(token="t", account_id="a", practice=False)
    # Avoid the network on construction by not calling refresh; the guard fires first.
    with pytest.raises(OandaError):
        OandaBroker(live)


def test_broker_submits_market_order_and_tracks_fill():
    summary = {"account": {"balance": "100000.0", "unrealizedPL": "0"}}
    fill_resp = {
        "orderFillTransaction": {"price": "1.10500", "units": "10000", "pl": "0"}
    }
    client = FakeClient([("/summary", summary), ("/orders", fill_resp)])
    broker = OandaBroker(client, account_id="101-000-TEST")

    fill = broker.submit(Order("EUR/USD", Side.BUY, 10000), mark_price=1.1050)
    assert fill is not None
    assert fill.side is Side.BUY
    assert fill.price == 1.10500
    assert broker.positions["EUR/USD"].size == 10000
    # The POST body must carry a signed unit count and market type.
    order_call = [c for c in client.calls if c[1].endswith("/orders")][0]
    assert order_call[2]["order"]["units"] == "10000"
    assert order_call[2]["order"]["type"] == "MARKET"


def test_broker_sell_order_signs_units_negative():
    summary = {"account": {"balance": "100000.0", "unrealizedPL": "0"}}
    fill_resp = {"orderFillTransaction": {"price": "1.10000", "units": "-5000", "pl": "0"}}
    client = FakeClient([("/summary", summary), ("/orders", fill_resp)])
    broker = OandaBroker(client, account_id="101-000-TEST")
    broker.submit(Order("EUR/USD", Side.SELL, 5000), mark_price=1.10)
    order_call = [c for c in client.calls if c[1].endswith("/orders")][0]
    assert order_call[2]["order"]["units"] == "-5000"
    assert broker.positions["EUR/USD"].size == -5000


def test_broker_unfilled_order_returns_none():
    summary = {"account": {"balance": "100000.0", "unrealizedPL": "0"}}
    cancelled = {"orderCancelTransaction": {"reason": "MARKET_HALTED"}}
    client = FakeClient([("/summary", summary), ("/orders", cancelled)])
    broker = OandaBroker(client, account_id="101-000-TEST")
    assert broker.submit(Order("EUR/USD", Side.BUY, 1000), mark_price=1.1) is None


def test_broker_attaches_protective_exits():
    summary = {"account": {"balance": "100000.0", "unrealizedPL": "0"}}
    fill_resp = {"orderFillTransaction": {"price": "1.10500", "units": "10000", "pl": "0"}}
    client = FakeClient([("/summary", summary), ("/orders", fill_resp)])
    broker = OandaBroker(client, account_id="101-000-TEST")
    broker.submit(
        Order("EUR/USD", Side.BUY, 10000, stop_loss=1.1000, take_profit=1.1200),
        mark_price=1.1050,
    )
    body = [c for c in client.calls if c[1].endswith("/orders")][0][2]
    assert "stopLossOnFill" in body["order"]
    assert "takeProfitOnFill" in body["order"]
