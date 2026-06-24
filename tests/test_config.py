"""Settings loading: dry_run resolution precedence and the live-mode
fail-fast secret/RPC validation."""

from __future__ import annotations

import textwrap

import pytest

from babayaga.config import load_settings

MINIMAL_YAML = textwrap.dedent(
    """
    dry_run: true
    risk:
      min_profit_bps: 25
      max_position_usd: 250.0
      max_daily_loss_usd: 200.0
      max_open_positions: 3
      slippage_bps: 50
    chains:
      ethereum:
        rpc_env: ETHEREUM_RPC_URL
        chain_id: 1
    venues:
      uniswap_v2_eth:
        kind: evm_v2_router
        chain: ethereum
        router_address: "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"
        fee_bps: 30
    pairs:
      - name: TEST_PAIR
        base: WETH
        quote: USDC
        legs:
          - venue: uniswap_v2_eth
    tokens:
      ethereum:
        WETH: "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
        USDC: "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
    """
)


_ENV_KEYS = [
    "DRY_RUN",
    "EVM_PRIVATE_KEY",
    "SOLANA_PRIVATE_KEY",
    "ETHEREUM_RPC_URL",
    "POLYGON_RPC_URL",
    "ARBITRUM_RPC_URL",
    "SOLANA_RPC_URL",
    "MT5_LOGIN",
    "MT5_PASSWORD",
    "MT5_SERVER",
    "MT5_TERMINAL_PATH",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    # load_dotenv() never overrides a variable that's already set in the
    # process environment, so leftover values from an earlier test (or the
    # shell babayaga itself is run from) would otherwise leak in here.
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(MINIMAL_YAML)
    return path


def _write_env(tmp_path, contents: str):
    path = tmp_path / ".env"
    path.write_text(contents)
    return path


def test_dry_run_defaults_to_yaml_value(tmp_path, config_path):
    env_path = _write_env(tmp_path, "")
    settings = load_settings(config_path, env_path)
    assert settings.dry_run is True


def test_env_dry_run_false_requires_secrets(tmp_path, config_path):
    env_path = _write_env(tmp_path, "DRY_RUN=false\n")
    with pytest.raises(RuntimeError, match="EVM_PRIVATE_KEY"):
        load_settings(config_path, env_path)


def test_env_dry_run_false_succeeds_with_secrets_present(tmp_path, config_path):
    env_path = _write_env(
        tmp_path,
        "DRY_RUN=false\nEVM_PRIVATE_KEY=0xabc\nETHEREUM_RPC_URL=http://localhost:1\n",
    )
    settings = load_settings(config_path, env_path)
    assert settings.dry_run is False
    assert settings.evm_private_key == "0xabc"


def test_force_dry_run_param_overrides_env(tmp_path, config_path):
    env_path = _write_env(tmp_path, "DRY_RUN=false\nEVM_PRIVATE_KEY=0xabc\nETHEREUM_RPC_URL=http://localhost:1\n")
    settings = load_settings(config_path, env_path, force_dry_run=True)
    assert settings.dry_run is True


def test_force_live_without_secrets_raises(tmp_path, config_path):
    env_path = _write_env(tmp_path, "")
    with pytest.raises(RuntimeError):
        load_settings(config_path, env_path, force_dry_run=False)


def test_missing_rpc_url_listed_when_going_live(tmp_path, config_path):
    env_path = _write_env(tmp_path, "DRY_RUN=false\nEVM_PRIVATE_KEY=0xabc\n")
    with pytest.raises(RuntimeError, match="ETHEREUM_RPC_URL"):
        load_settings(config_path, env_path)


def test_extra_unknown_fields_are_rejected(tmp_path):
    bad_yaml = MINIMAL_YAML + "\nnot_a_real_field: 123\n"
    path = tmp_path / "config.yaml"
    path.write_text(bad_yaml)
    env_path = _write_env(tmp_path, "")
    with pytest.raises(Exception):
        load_settings(path, env_path)
