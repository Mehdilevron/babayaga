"""Builds, signs, and submits Solana swaps via the Jupiter aggregator's swap
API. Jupiter returns an unsigned serialized transaction already routed
through the best combination of Raydium/Orca/etc. pools; this signs it with
the local hot wallet keypair and submits it directly to an RPC node.

Requires the optional `solders` dependency (`pip install babayaga[solana]`).
"""

from __future__ import annotations

import base64
from typing import Dict, Optional

import requests

from babayaga.core.models import Fill, Order, OrderStatus, Side
from babayaga.wallet.solana_wallet import SolanaWallet

JUPITER_QUOTE_URL = "https://quote-api.jup.ag/v6/quote"
JUPITER_SWAP_URL = "https://quote-api.jup.ag/v6/swap"
DEFAULT_SLIPPAGE_BPS = 50


class JupiterExecutor:
    def __init__(
        self,
        venue: str,
        rpc_url: str,
        tokens: Dict[str, str],
        decimals: Dict[str, int],
        wallet: SolanaWallet,
        slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
        timeout_s: float = 10.0,
        dexes: Optional[str] = None,
    ):
        self.venue = venue
        self.rpc_url = rpc_url
        self.tokens = tokens
        self.decimals = decimals
        self.wallet = wallet
        self.slippage_bps = slippage_bps
        self.timeout_s = timeout_s
        self.dexes = dexes

    def _rpc_call(self, method: str, params: list) -> dict:
        resp = requests.post(
            self.rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            raise RuntimeError(f"Solana RPC error: {body['error']}")
        return body["result"]

    async def execute(self, order: Order) -> Fill:
        from solders.transaction import VersionedTransaction  # lazy: optional dependency

        sell_token = order.base if order.side == Side.SELL else order.quote
        buy_token = order.quote if order.side == Side.SELL else order.base
        sell_mint = self.tokens[sell_token]
        buy_mint = self.tokens[buy_token]
        sell_dec = self.decimals[sell_token]

        if order.side == Side.SELL:
            amount_wei = int(order.size_base * 10**sell_dec)
        else:
            amount_wei = int(order.size_base * order.limit_price * 10**sell_dec)

        try:
            quote_params = {
                "inputMint": sell_mint,
                "outputMint": buy_mint,
                "amount": amount_wei,
                "slippageBps": self.slippage_bps,
            }
            if self.dexes:
                quote_params["dexes"] = self.dexes
            quote_resp = requests.get(JUPITER_QUOTE_URL, params=quote_params, timeout=self.timeout_s)
            quote_resp.raise_for_status()
            quote_json = quote_resp.json()

            swap_resp = requests.post(
                JUPITER_SWAP_URL,
                json={
                    "quoteResponse": quote_json,
                    "userPublicKey": str(self.wallet.public_key),
                    "wrapAndUnwrapSol": True,
                },
                timeout=self.timeout_s,
            )
            swap_resp.raise_for_status()
            swap_tx_b64 = swap_resp.json()["swapTransaction"]

            raw_tx = VersionedTransaction.from_bytes(base64.b64decode(swap_tx_b64))
            signed_tx = VersionedTransaction(raw_tx.message, [self.wallet.keypair])
            signed_b64 = base64.b64encode(bytes(signed_tx)).decode("ascii")

            signature = self._rpc_call(
                "sendTransaction",
                [signed_b64, {"encoding": "base64", "skipPreflight": False, "maxRetries": 3}],
            )
        except Exception as exc:
            order.status = OrderStatus.FAILED
            order.error = str(exc)
            raise

        order.status = OrderStatus.FILLED
        order.tx_hash = signature
        return Fill(order=order, filled_size_base=order.size_base, avg_price=order.limit_price, fee_paid_usd=0.0)
