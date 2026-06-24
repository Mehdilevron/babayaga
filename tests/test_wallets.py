"""Wallet construction tests - mainly the placeholder-key safety rail that
stops the bot from ever signing with the literal values from .env.example."""

from __future__ import annotations

import json

import pytest
from eth_account import Account

from babayaga.wallet.evm_wallet import EvmWallet
from babayaga.wallet.solana_wallet import SolanaWallet


def test_evm_wallet_rejects_empty_key():
    with pytest.raises(ValueError):
        EvmWallet("")


def test_evm_wallet_rejects_placeholder_key():
    with pytest.raises(ValueError):
        EvmWallet("0xyour_private_key_here")


def test_evm_wallet_accepts_a_real_key():
    real_key = Account.create().key.hex()
    wallet = EvmWallet(real_key)
    assert wallet.address.startswith("0x")
    assert len(wallet.address) == 42


def test_solana_wallet_rejects_empty_key():
    with pytest.raises(ValueError):
        SolanaWallet("")


def test_solana_wallet_rejects_placeholder_key():
    with pytest.raises(ValueError):
        SolanaWallet("your_base58_or_json_array_secret_key")


def test_solana_wallet_accepts_base58_key():
    from solders.keypair import Keypair

    kp = Keypair()
    wallet = SolanaWallet(str(kp))
    assert wallet.public_key == kp.pubkey()


def test_solana_wallet_accepts_json_array_key():
    from solders.keypair import Keypair

    kp = Keypair()
    secret_json = json.dumps(list(bytes(kp)))
    wallet = SolanaWallet(secret_json)
    assert wallet.public_key == kp.pubkey()
