from babayaga.integration.broker import PaperBroker
from babayaga.kernel.events import Order, Side


def test_open_and_close_realizes_pnl():
    b = PaperBroker(starting_cash=100_000, spread=0.0, commission_per_unit=0.0)
    b.submit(Order("EUR/USD", Side.BUY, 10_000), mark_price=1.1000)
    assert b.positions["EUR/USD"].size == 10_000
    assert b.positions["EUR/USD"].avg_price == 1.1000

    # Price rises 100 pips, close the long.
    b.mark_to_market("EUR/USD", 1.1100)
    b.submit(Order("EUR/USD", Side.SELL, 10_000), mark_price=1.1100)
    assert b.positions["EUR/USD"].size == 0
    # 10,000 units * 0.0100 = 100 profit.
    assert round(b.realized_pnl, 2) == 100.0
    assert round(b.equity, 2) == 100_100.0


def test_spread_costs_the_taker():
    b = PaperBroker(starting_cash=100_000, spread=0.0002)
    fill = b.submit(Order("EUR/USD", Side.BUY, 1000), mark_price=1.2000)
    assert fill is not None
    # Buyer pays half-spread above mid.
    assert fill.price == 1.2001


def test_short_position_profits_when_price_falls():
    b = PaperBroker(starting_cash=100_000, spread=0.0)
    b.submit(Order("EUR/USD", Side.SELL, 5000), mark_price=1.3000)
    b.mark_to_market("EUR/USD", 1.2900)
    assert round(b.unrealized_pnl, 2) == 50.0  # 5000 * 0.01
    b.submit(Order("EUR/USD", Side.BUY, 5000), mark_price=1.2900)
    assert round(b.realized_pnl, 2) == 50.0


def test_stop_loss_triggers_exit():
    b = PaperBroker(starting_cash=100_000, spread=0.0)
    b.submit(
        Order("EUR/USD", Side.BUY, 10_000, stop_loss=1.0950, take_profit=1.1200),
        mark_price=1.1000,
    )
    assert b.open_position_count() == 1
    # Drop through the stop; mark_to_market should auto-close.
    b.mark_to_market("EUR/USD", 1.0940)
    assert b.open_position_count() == 0
    assert b.realized_pnl < 0


def test_take_profit_triggers_exit():
    b = PaperBroker(starting_cash=100_000, spread=0.0)
    b.submit(
        Order("EUR/USD", Side.BUY, 10_000, stop_loss=1.0950, take_profit=1.1200),
        mark_price=1.1000,
    )
    b.mark_to_market("EUR/USD", 1.1250)
    assert b.open_position_count() == 0
    assert b.realized_pnl > 0


def test_averaging_up_updates_avg_price():
    b = PaperBroker(starting_cash=100_000, spread=0.0)
    b.submit(Order("EUR/USD", Side.BUY, 10_000), mark_price=1.1000)
    b.submit(Order("EUR/USD", Side.BUY, 10_000), mark_price=1.1100)
    pos = b.positions["EUR/USD"]
    assert pos.size == 20_000
    assert round(pos.avg_price, 5) == 1.1050
