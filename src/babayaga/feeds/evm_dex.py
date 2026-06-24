"""On-chain DEX price feeds for Uniswap V2-style routers (also covers
Sushiswap/QuickSwap, which are V2 forks) and Uniswap V3 (QuoterV2).

Reads are free (eth_call against a public RPC), so these can poll as fast as
your RPC provider's rate limit allows. Both feeds quote at the actual
requested size, so the returned bid/ask already reflect AMM slippage for
that size rather than a misleading spot price.
"""

from __future__ import annotations

from typing import Dict

from web3 import Web3

from babayaga.core.models import Quote
from babayaga.feeds._abi import ERC20_ABI, UNISWAP_V2_ROUTER_ABI, UNISWAP_V3_QUOTER_V2_ABI


class _Erc20DecimalsMixin:
    w3: Web3
    _decimals_cache: Dict[str, int]

    def _decimals(self, token_address: str) -> int:
        token_address = Web3.to_checksum_address(token_address)
        if token_address not in self._decimals_cache:
            erc20 = self.w3.eth.contract(address=token_address, abi=ERC20_ABI)
            self._decimals_cache[token_address] = erc20.functions.decimals().call()
        return self._decimals_cache[token_address]


class EvmV2DexFeed(_Erc20DecimalsMixin):
    """Uniswap V2 / Sushiswap / QuickSwap-style constant-product router."""

    def __init__(self, venue: str, rpc_url: str, router_address: str, fee_bps: float, tokens: Dict[str, str]):
        self.venue = venue
        self.fee_bps = fee_bps
        self.tokens = tokens
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.router = self.w3.eth.contract(
            address=Web3.to_checksum_address(router_address), abi=UNISWAP_V2_ROUTER_ABI
        )
        self._decimals_cache: Dict[str, int] = {}

    async def get_quote(self, base: str, quote: str, size_base: float) -> Quote:
        base_addr = Web3.to_checksum_address(self.tokens[base])
        quote_addr = Web3.to_checksum_address(self.tokens[quote])
        base_dec = self._decimals(base_addr)
        quote_dec = self._decimals(quote_addr)

        base_amount_wei = int(size_base * 10**base_dec)

        # ask: quote-in needed to receive size_base of base (buying base)
        amounts_in = self.router.functions.getAmountsIn(base_amount_wei, [quote_addr, base_addr]).call()
        ask = (amounts_in[0] / 10**quote_dec) / size_base

        # bid: quote-out received for selling size_base of base
        amounts_out = self.router.functions.getAmountsOut(base_amount_wei, [base_addr, quote_addr]).call()
        bid = (amounts_out[-1] / 10**quote_dec) / size_base

        return Quote(venue=self.venue, base=base, quote=quote, bid=bid, ask=ask, fee_bps=self.fee_bps)


class EvmV3DexFeed(_Erc20DecimalsMixin):
    """Uniswap V3 (or compatible fork) using QuoterV2.

    QuoterV2's quote functions are technically state-mutating (they revert
    with the result, which gets unwound) so they must be called via eth_call -
    `.call()` already does this and never sends a real transaction.
    """

    DEFAULT_FEE_TIER = 3000  # 0.3%; override per-pool via pool_fee_tier if the pair trades on a different tier

    def __init__(
        self,
        venue: str,
        rpc_url: str,
        quoter_address: str,
        fee_bps: float,
        tokens: Dict[str, str],
        pool_fee_tier: int = DEFAULT_FEE_TIER,
    ):
        self.venue = venue
        self.fee_bps = fee_bps
        self.tokens = tokens
        self.pool_fee_tier = pool_fee_tier
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.quoter = self.w3.eth.contract(
            address=Web3.to_checksum_address(quoter_address), abi=UNISWAP_V3_QUOTER_V2_ABI
        )
        self._decimals_cache: Dict[str, int] = {}

    def _quote_exact_in(self, token_in: str, token_out: str, amount_in_wei: int) -> int:
        params = (
            Web3.to_checksum_address(token_in),
            Web3.to_checksum_address(token_out),
            amount_in_wei,
            self.pool_fee_tier,
            0,
        )
        amount_out, *_ = self.quoter.functions.quoteExactInputSingle(params).call()
        return amount_out

    def _quote_exact_out(self, token_in: str, token_out: str, amount_out_wei: int) -> int:
        params = (
            Web3.to_checksum_address(token_in),
            Web3.to_checksum_address(token_out),
            amount_out_wei,
            self.pool_fee_tier,
            0,
        )
        amount_in, *_ = self.quoter.functions.quoteExactOutputSingle(params).call()
        return amount_in

    async def get_quote(self, base: str, quote: str, size_base: float) -> Quote:
        base_addr = self.tokens[base]
        quote_addr = self.tokens[quote]
        base_dec = self._decimals(base_addr)
        quote_dec = self._decimals(quote_addr)

        base_amount_wei = int(size_base * 10**base_dec)

        quote_out_wei = self._quote_exact_in(base_addr, quote_addr, base_amount_wei)
        bid = (quote_out_wei / 10**quote_dec) / size_base

        quote_in_wei = self._quote_exact_out(quote_addr, base_addr, base_amount_wei)
        ask = (quote_in_wei / 10**quote_dec) / size_base

        return Quote(venue=self.venue, base=base, quote=quote, bid=bid, ask=ask, fee_bps=self.fee_bps)
