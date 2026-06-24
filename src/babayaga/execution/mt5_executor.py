"""Opens the MT5 hedge leg used to lock in a cross-market arbitrage spread
(e.g. shorting XAUUSD when PAXG was just bought cheaper on a DEX).

`order.size_base` is expressed in units of the underlying (e.g. troy ounces
of gold), not MT5 lots - this converts using the symbol's live contract
size and volume step from the broker, so it works regardless of how that
particular broker defines a lot for this instrument.

Requires the optional `MetaTrader5` dependency and a running, logged-in MT5
terminal on the same machine - see feeds/mt5_feed.py for why.
"""

from __future__ import annotations

from babayaga.core.models import Fill, Order, OrderStatus, Side
from babayaga.feeds.mt5_feed import Mt5Session

DEFAULT_DEVIATION_POINTS = 20
DEFAULT_MAGIC = 234000


class Mt5Executor:
    def __init__(
        self,
        venue: str,
        session: Mt5Session,
        deviation_points: int = DEFAULT_DEVIATION_POINTS,
        magic: int = DEFAULT_MAGIC,
        comment: str = "babayaga-arb",
    ):
        self.venue = venue
        self.session = session
        self.deviation_points = deviation_points
        self.magic = magic
        self.comment = comment

    async def execute(self, order: Order, symbol: str) -> Fill:
        import MetaTrader5 as mt5

        self.session.ensure_connected()

        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            err = RuntimeError(f"MT5 symbol_info({symbol}) returned None: {mt5.last_error()}")
            order.status = OrderStatus.FAILED
            order.error = str(err)
            raise err

        contract_size = symbol_info.trade_contract_size or 1.0
        volume_step = symbol_info.volume_step or 0.01
        raw_lots = order.size_base / contract_size
        volume_lots = max(symbol_info.volume_min, round(raw_lots / volume_step) * volume_step)

        # The hedge leg mirrors the DEX leg: if we bought `base` on a DEX, we
        # open the offsetting MT5 position by selling the correlated
        # instrument (and vice versa), locking in the spread.
        order_type = mt5.ORDER_TYPE_SELL if order.side == Side.BUY else mt5.ORDER_TYPE_BUY

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            err = RuntimeError(f"MT5 symbol_info_tick({symbol}) returned None: {mt5.last_error()}")
            order.status = OrderStatus.FAILED
            order.error = str(err)
            raise err
        price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume_lots,
            "type": order_type,
            "price": price,
            "deviation": self.deviation_points,
            "magic": self.magic,
            "comment": self.comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)

        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err = RuntimeError(
                f"MT5 order_send failed: retcode={getattr(result, 'retcode', None)} {mt5.last_error()}"
            )
            order.status = OrderStatus.FAILED
            order.error = str(err)
            raise err

        order.status = OrderStatus.FILLED
        order.tx_hash = str(result.order)
        return Fill(order=order, filled_size_base=result.volume * contract_size, avg_price=result.price, fee_paid_usd=0.0)
