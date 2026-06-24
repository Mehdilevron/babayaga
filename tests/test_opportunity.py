"""Pure economics tests for find_best_opportunity - no I/O, no mocks needed."""

from __future__ import annotations

from babayaga.core.models import Quote
from babayaga.core.opportunity import find_best_opportunity


def _quote(venue: str, bid: float, ask: float, fee_bps: float = 0.0) -> Quote:
    return Quote(venue=venue, base="WETH", quote="USDC", bid=bid, ask=ask, fee_bps=fee_bps)


def test_returns_none_with_fewer_than_two_venues():
    assert find_best_opportunity("PAIR", [_quote("a", 100, 101)], size_base=1.0) is None


def test_returns_none_with_no_quotes():
    assert find_best_opportunity("PAIR", [], size_base=1.0) is None


def test_returns_none_with_non_positive_size():
    quotes = [_quote("cheap", 100, 100), _quote("rich", 110, 110)]
    assert find_best_opportunity("PAIR", quotes, size_base=0.0) is None
    assert find_best_opportunity("PAIR", quotes, size_base=-1.0) is None


def test_finds_profitable_spread_with_zero_costs():
    quotes = [_quote("cheap", bid=99, ask=100), _quote("rich", bid=110, ask=111)]
    opp = find_best_opportunity("PAIR", quotes, size_base=1.0)

    assert opp is not None
    assert opp.buy_quote.venue == "cheap"
    assert opp.sell_quote.venue == "rich"
    assert opp.gross_spread_bps == (110 - 100) / 100 * 10_000
    assert opp.est_cost_bps == 0.0
    assert opp.net_profit_bps == opp.gross_spread_bps
    assert opp.is_profitable
    assert opp.est_net_profit_usd == opp.net_profit_bps / 10_000 * 1.0 * 100


def test_fees_reduce_net_profit():
    quotes = [_quote("cheap", bid=99, ask=100, fee_bps=30), _quote("rich", bid=110, ask=111, fee_bps=30)]
    opp = find_best_opportunity("PAIR", quotes, size_base=1.0)

    assert opp is not None
    assert opp.est_cost_bps == 60.0
    assert opp.net_profit_bps == opp.gross_spread_bps - 60.0


def test_gas_cost_converted_to_bps_of_notional():
    quotes = [_quote("cheap", bid=99, ask=100), _quote("rich", bid=110, ask=111)]
    opp = find_best_opportunity("PAIR", quotes, size_base=2.0, gas_cost_usd=20.0)

    notional = 2.0 * 100  # size_base * buy ask
    expected_gas_bps = 20.0 / notional * 10_000
    assert opp is not None
    assert opp.est_cost_bps == expected_gas_bps
    assert opp.net_profit_bps == opp.gross_spread_bps - expected_gas_bps


def test_slippage_bps_added_to_cost():
    quotes = [_quote("cheap", bid=99, ask=100), _quote("rich", bid=110, ask=111)]
    opp = find_best_opportunity("PAIR", quotes, size_base=1.0, slippage_bps=50.0)

    assert opp is not None
    assert opp.est_cost_bps == 50.0


def test_negative_net_profit_still_returned_when_costs_exceed_spread():
    quotes = [_quote("cheap", bid=99, ask=100, fee_bps=500), _quote("rich", bid=100.5, ask=101, fee_bps=500)]
    opp = find_best_opportunity("PAIR", quotes, size_base=1.0)

    assert opp is not None
    assert opp.net_profit_bps < 0
    assert not opp.is_profitable


def test_picks_the_best_combination_among_three_venues():
    quotes = [
        _quote("a", bid=99, ask=100),
        _quote("b", bid=105, ask=106),
        _quote("c", bid=120, ask=121),  # best sell leg
    ]
    opp = find_best_opportunity("PAIR", quotes, size_base=1.0)

    assert opp is not None
    assert opp.buy_quote.venue == "a"
    assert opp.sell_quote.venue == "c"


def test_skips_quotes_with_non_positive_ask_or_bid():
    # A quote with ask <= 0 can never be the buy leg - with both quotes
    # unusable as a buy leg, no permutation survives and None comes back.
    quotes = [_quote("a", bid=10, ask=0.0), _quote("b", bid=20, ask=0.0)]
    assert find_best_opportunity("PAIR", quotes, size_base=1.0) is None


def test_never_pairs_a_venue_with_itself():
    # A single repeated venue object still can't arb against itself.
    q = _quote("solo", bid=100, ask=100)
    assert find_best_opportunity("PAIR", [q, q], size_base=1.0) is None


def test_is_hedge_flag_propagates():
    quotes = [_quote("cheap", bid=99, ask=100), _quote("rich", bid=110, ask=111)]
    opp = find_best_opportunity("PAIR", quotes, size_base=1.0, is_hedge=True)
    assert opp is not None
    assert opp.is_hedge is True
