"""Pure arbitrage economics: given quotes for the same logical pair across
two or more venues, find the most profitable buy/sell combination and its
net economics after venue fees, an estimated gas cost, and a slippage buffer.

No I/O and no side effects here on purpose - this is the part of the bot that
must be trivially unit-testable without a live RPC, wallet, or MT5 terminal.
"""

from __future__ import annotations

from itertools import permutations
from typing import Iterable, List, Optional

from babayaga.core.models import ArbOpportunity, Quote

BPS = 10_000.0


def find_best_opportunity(
    pair_name: str,
    quotes: Iterable[Quote],
    size_base: float,
    *,
    gas_cost_usd: float = 0.0,
    slippage_bps: float = 0.0,
    is_hedge: bool = False,
) -> Optional[ArbOpportunity]:
    """Return the best buy/sell venue combination among `quotes` by net profit,
    or None if fewer than two distinct venues quoted or size_base <= 0.

    The caller (engine + risk manager) decides whether the returned
    opportunity clears the profit floor - this function always returns the
    best one found, even if its net_profit_bps is negative.
    """
    quote_list: List[Quote] = list(quotes)
    if size_base <= 0 or len(quote_list) < 2:
        return None

    best: Optional[ArbOpportunity] = None
    for buy_quote, sell_quote in permutations(quote_list, 2):
        if buy_quote.venue == sell_quote.venue:
            continue
        if buy_quote.ask <= 0 or sell_quote.bid <= 0:
            continue

        gross_spread_bps = (sell_quote.bid - buy_quote.ask) / buy_quote.ask * BPS
        notional_usd = size_base * buy_quote.ask
        gas_bps = (gas_cost_usd / notional_usd * BPS) if notional_usd > 0 else 0.0
        est_cost_bps = buy_quote.fee_bps + sell_quote.fee_bps + slippage_bps + gas_bps
        net_profit_bps = gross_spread_bps - est_cost_bps
        est_net_profit_usd = net_profit_bps / BPS * notional_usd

        candidate = ArbOpportunity(
            pair_name=pair_name,
            buy_quote=buy_quote,
            sell_quote=sell_quote,
            size_base=size_base,
            gross_spread_bps=gross_spread_bps,
            est_cost_bps=est_cost_bps,
            net_profit_bps=net_profit_bps,
            est_net_profit_usd=est_net_profit_usd,
            is_hedge=is_hedge,
        )
        if best is None or candidate.net_profit_bps > best.net_profit_bps:
            best = candidate

    return best
