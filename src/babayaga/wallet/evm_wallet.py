"""Loads a local hot wallet from a private key for unattended signing.

This is what makes sub-second automated execution possible - there is no
human-in-the-loop approval step like WalletConnect/MetaMask would require.
Fund this wallet only with what you are willing to lose, keep it separate
from any wallet holding the bulk of your assets, and never commit the key.
"""

from __future__ import annotations

from eth_account import Account
from eth_account.signers.local import LocalAccount

_PLACEHOLDER_VALUES = {"", "0xyour_private_key_here"}


class EvmWallet:
    def __init__(self, private_key: str):
        if not private_key or private_key.strip() in _PLACEHOLDER_VALUES:
            raise ValueError(
                "EVM_PRIVATE_KEY is not set to a real key - refusing to construct a wallet."
            )
        self._account: LocalAccount = Account.from_key(private_key)

    @property
    def address(self) -> str:
        return self._account.address

    @property
    def account(self) -> LocalAccount:
        return self._account
