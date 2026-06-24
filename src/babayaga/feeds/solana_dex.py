"""Solana DEX price feed via the Jupiter aggregator's public Quote API,
which natively routes through Raydium, Orca, and other Solana AMMs - no
direct on-chain pool math needed.

Jupiter's quote endpoint is exact-in only (no exact-out), so the "ask" side
is approximated: quote the bid first, then probe a quote->base swap sized
off that bid price and re-derive the implied ask from the actual output.
"""

from __future__ import annotations

from typing import Dict, Optional

import requests

from babayaga.core.models import Quote

JUPITER_QUOTE_URL = "https://quote-api.jup.ag/v6/quote"
DEFAULT_SLIPPAGE_BPS = 50

# Well-known Solana token decimals, used when no on-chain lookup is wired up.
DEFAULT_DECIMALS = {"SOL": 9, "USDC": 6, "USDT": 6}


class JupiterDexFeed:
    def __init__(
        self,
        venue: str,
        fee_bps: float,
        tokens: Dict[str, str],
        decimals_override: Optional[Dict[str, int]] = None,
        slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
        timeout_s: float = 5.0,
        dexes: Optional[str] = None,
    ):
        self.venue = venue
        self.fee_bps = fee_bps
        self.tokens = tokens
        self.decimals = {**DEFAULT_DECIMALS, **(decimals_override or {})}
        self.slippage_bps = slippage_bps
        self.timeout_s = timeout_s
        # Restricts routing to a specific AMM label (e.g. "Raydium" or "Orca") so two
        # JupiterDexFeed instances can stand in for two distinct venues to arb between.
        # Verify the exact label spelling against Jupiter's current quote API docs.
        self.dexes = dexes

    def _decimals(self, symbol: str) -> int:
        if symbol not in self.decimals:
            raise KeyError(
                f"No decimals known for Solana token {symbol!r} - pass it via decimals_override."
            )
        return self.decimals[symbol]

    def _quote(self, input_mint: str, output_mint: str, amount_wei: int) -> dict:
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": amount_wei,
            "slippageBps": self.slippage_bps,
        }
        if self.dexes:
            params["dexes"] = self.dexes
        resp = requests.get(JUPITER_QUOTE_URL, params=params, timeout=self.timeout_s)
        resp.raise_for_status()
        return resp.json()

    async def get_quote(self, base: str, quote: str, size_base: float) -> Quote:
        base_mint = self.tokens[base]
        quote_mint = self.tokens[quote]
        base_dec = self._decimals(base)
        quote_dec = self._decimals(quote)

        base_amount_wei = int(size_base * 10**base_dec)

        sell_quote = self._quote(base_mint, quote_mint, base_amount_wei)
        bid = (int(sell_quote["outAmount"]) / 10**quote_dec) / size_base

        probe_quote_wei = int(bid * size_base * 10**quote_dec)
        ask = bid
        if probe_quote_wei > 0:
            buy_quote = self._quote(quote_mint, base_mint, probe_quote_wei)
            base_out = int(buy_quote["outAmount"]) / 10**base_dec
            if base_out > 0:
                ask = (probe_quote_wei / 10**quote_dec) / base_out

        return Quote(venue=self.venue, base=base, quote=quote, bid=bid, ask=ask, fee_bps=self.fee_bps)
