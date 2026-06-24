"""Loads a local Solana hot wallet keypair for unattended signing.

Same tradeoff as the EVM wallet: no human approval step, so fund it only
with what you're willing to risk and never commit the key. Requires the
optional `solders` dependency (`pip install babayaga[solana]`).
"""

from __future__ import annotations

import json


class SolanaWallet:
    def __init__(self, secret_key: str):
        from solders.keypair import Keypair  # imported lazily so this stays an optional dependency

        if not secret_key or secret_key.strip() in {"", "your_base58_or_json_array_secret_key"}:
            raise ValueError(
                "SOLANA_PRIVATE_KEY is not set to a real key - refusing to construct a wallet."
            )

        secret_key = secret_key.strip()
        if secret_key.startswith("["):
            self.keypair = Keypair.from_bytes(bytes(json.loads(secret_key)))
        else:
            self.keypair = Keypair.from_base58_string(secret_key)

    @property
    def public_key(self):
        return self.keypair.pubkey()
