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


def test_per_symbol_spread_used_when_unset():
    # spread=None -> realistic per-symbol spreads: USD/JPY (~150.0) must not be
    # charged EUR/USD's 0.0001.
    b = PaperBroker(starting_cash=100_000, spread=None)
    jpy = b.submit(Order("USD/JPY", Side.BUY, 1000), mark_price=150.0)
    eur = b.submit(Order("EUR/USD", Side.BUY, 1000), mark_price=1.1000)
    assert jpy is not None and eur is not None
    assert round(jpy.price - 150.0, 6) == 0.005     # half of 0.010
    assert round(eur.price - 1.1000, 6) == 0.00004  # half of 0.00008


def test_slippage_applied_against_taker():
    b = PaperBroker(starting_cash=100_000, spread=0.0, slippage=0.0001)
    buy = b.submit(Order("EUR/USD", Side.BUY, 1000), mark_price=1.2000)
    sell = b.submit(Order("EUR/USD", Side.SELL, 1000), mark_price=1.2000)
    assert buy is not None and round(buy.price, 6) == 1.2001
    assert sell is not None and round(sell.price, 6) == 1.1999


def test_equity_floor_hard_stop_flattens_and_latches():
    b = PaperBroker(starting_cash=1000.0, spread=0.0, equity_floor=950.0)
    b.submit(Order("EUR/USD", Side.BUY, 100_000), mark_price=1.1000)
    # Price falls 10 pips -> -$100 unrealized -> equity 900 <= floor 950.
    b.mark_to_market("EUR/USD", 1.0990)
    assert b.halted_hard is True
    assert b.open_position_count() == 0  # everything was flattened
    fills = b.pop_protective_fills()
    assert any(f.order_reason == "hard_stop" for f in fills)  # visibly closed
    # Latched: no new order is accepted, even a profitable-looking one.
    assert b.submit(Order("EUR/USD", Side.BUY, 1000), mark_price=1.0990) is None
    # And it stays latched even if marks recover.
    b.mark_to_market("EUR/USD", 1.2000)
    assert b.halted_hard is True


def test_equity_floor_off_by_default():
    b = PaperBroker(starting_cash=1000.0, spread=0.0)
    b.submit(Order("EUR/USD", Side.BUY, 100_000), mark_price=1.1000)
    b.mark_to_market("EUR/USD", 1.0900)  # -$1000, but no floor configured
    assert b.halted_hard is False


def test_averaging_up_updates_avg_price():
    b = PaperBroker(starting_cash=100_000, spread=0.0)
    b.submit(Order("EUR/USD", Side.BUY, 10_000), mark_price=1.1000)
    b.submit(Order("EUR/USD", Side.BUY, 10_000), mark_price=1.1100)
    pos = b.positions["EUR/USD"]
    assert pos.size == 20_000
    assert round(pos.avg_price, 5) == 1.1050
