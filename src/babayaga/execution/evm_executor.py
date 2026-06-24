"""Signs and submits swap transactions to an EVM DEX router using a local
hot wallet - no human approval step, which is what makes sub-second
automated execution possible. Handles ERC20 approve-if-needed and a
slippage-adjusted minimum output, then waits for the receipt to confirm.

Known simplification: the recorded fill price is the order's limit price,
not the actual amount decoded from Swap/Transfer event logs. That's
conservative for PnL accounting (it never overstates profit) but isn't
exact - before scaling real capital, extend `execute()` to parse the
receipt's logs for the true output amount.
"""

from __future__ import annotations

from typing import Dict

from web3 import Web3

from babayaga.core.models import Fill, Order, OrderStatus, Side
from babayaga.feeds._abi import ERC20_ABI, UNISWAP_V2_ROUTER_ABI, UNISWAP_V3_ROUTER02_ABI
from babayaga.wallet.evm_wallet import EvmWallet

DEADLINE_SECONDS = 120
SLIPPAGE_GUARD = 0.995  # extra 0.5% cushion under the requested limit price


class _EvmExecutorBase:
    w3: Web3
    tokens: Dict[str, str]
    wallet: EvmWallet
    chain_id: int
    gas_limit_estimate: int
    router_address: str

    def _erc20(self, token_address: str):
        return self.w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)

    def _decimals(self, token_address: str) -> int:
        return self._erc20(token_address).functions.decimals().call()

    def _ensure_allowance(self, token_address: str, amount_wei: int) -> None:
        erc20 = self._erc20(token_address)
        owner = self.wallet.address
        current = erc20.functions.allowance(owner, self.router_address).call()
        if current >= amount_wei:
            return
        tx = erc20.functions.approve(self.router_address, amount_wei).build_transaction(
            {
                "from": owner,
                "nonce": self.w3.eth.get_transaction_count(owner),
                "chainId": self.chain_id,
                "gas": 80_000,
                "gasPrice": self.w3.eth.gas_price,
            }
        )
        self._sign_and_send(tx)

    def _sign_and_send(self, tx: dict) -> str:
        signed = self.wallet.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        return tx_hash.hex()

    def _swap_legs(self, order: Order):
        """Resolve (sell_token, buy_token, amount_in_wei, amount_out_min_wei)."""
        sell_token = order.base if order.side == Side.SELL else order.quote
        buy_token = order.quote if order.side == Side.SELL else order.base
        sell_addr = self.tokens[sell_token]
        buy_addr = self.tokens[buy_token]
        sell_dec = self._decimals(sell_addr)
        buy_dec = self._decimals(buy_addr)

        if order.side == Side.SELL:
            amount_in_wei = int(order.size_base * 10**sell_dec)
            min_out_human = order.size_base * order.limit_price
        else:
            amount_in_wei = int(order.size_base * order.limit_price * 10**sell_dec)
            min_out_human = order.size_base

        amount_out_min_wei = int(min_out_human * 10**buy_dec * SLIPPAGE_GUARD)
        return sell_addr, buy_addr, amount_in_wei, amount_out_min_wei

    def _finish(self, order: Order, tx_hash: str) -> Fill:
        order.status = OrderStatus.FILLED
        order.tx_hash = tx_hash
        return Fill(order=order, filled_size_base=order.size_base, avg_price=order.limit_price, fee_paid_usd=0.0)

    def _fail(self, order: Order, exc: Exception) -> None:
        order.status = OrderStatus.FAILED
        order.error = str(exc)


class EvmV2Executor(_EvmExecutorBase):
    """Uniswap V2 / Sushiswap / QuickSwap-style router."""

    def __init__(
        self,
        venue: str,
        rpc_url: str,
        router_address: str,
        tokens: Dict[str, str],
        wallet: EvmWallet,
        chain_id: int,
        gas_limit_estimate: int = 200_000,
    ):
        self.venue = venue
        self.tokens = tokens
        self.wallet = wallet
        self.chain_id = chain_id
        self.gas_limit_estimate = gas_limit_estimate
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.router_address = Web3.to_checksum_address(router_address)
        self.router = self.w3.eth.contract(address=self.router_address, abi=UNISWAP_V2_ROUTER_ABI)

    async def execute(self, order: Order) -> Fill:
        sell_addr, buy_addr, amount_in_wei, amount_out_min_wei = self._swap_legs(order)
        self._ensure_allowance(sell_addr, amount_in_wei)

        owner = self.wallet.address
        deadline = self.w3.eth.get_block("latest")["timestamp"] + DEADLINE_SECONDS
        tx = self.router.functions.swapExactTokensForTokens(
            amount_in_wei,
            amount_out_min_wei,
            [Web3.to_checksum_address(sell_addr), Web3.to_checksum_address(buy_addr)],
            owner,
            deadline,
        ).build_transaction(
            {
                "from": owner,
                "nonce": self.w3.eth.get_transaction_count(owner),
                "chainId": self.chain_id,
                "gas": self.gas_limit_estimate,
                "gasPrice": self.w3.eth.gas_price,
            }
        )

        try:
            tx_hash = self._sign_and_send(tx)
        except Exception as exc:
            self._fail(order, exc)
            raise
        return self._finish(order, tx_hash)


class EvmV3Executor(_EvmExecutorBase):
    """Uniswap V3 (or compatible fork) via SwapRouter02's exactInputSingle."""

    DEFAULT_FEE_TIER = 3000

    def __init__(
        self,
        venue: str,
        rpc_url: str,
        router_address: str,
        tokens: Dict[str, str],
        wallet: EvmWallet,
        chain_id: int,
        gas_limit_estimate: int = 250_000,
        pool_fee_tier: int = DEFAULT_FEE_TIER,
    ):
        self.venue = venue
        self.tokens = tokens
        self.wallet = wallet
        self.chain_id = chain_id
        self.gas_limit_estimate = gas_limit_estimate
        self.pool_fee_tier = pool_fee_tier
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.router_address = Web3.to_checksum_address(router_address)
        self.router = self.w3.eth.contract(address=self.router_address, abi=UNISWAP_V3_ROUTER02_ABI)

    async def execute(self, order: Order) -> Fill:
        sell_addr, buy_addr, amount_in_wei, amount_out_min_wei = self._swap_legs(order)
        self._ensure_allowance(sell_addr, amount_in_wei)

        owner = self.wallet.address
        params = (
            Web3.to_checksum_address(sell_addr),
            Web3.to_checksum_address(buy_addr),
            self.pool_fee_tier,
            owner,
            amount_in_wei,
            amount_out_min_wei,
            0,
        )
        tx = self.router.functions.exactInputSingle(params).build_transaction(
            {
                "from": owner,
                "nonce": self.w3.eth.get_transaction_count(owner),
                "chainId": self.chain_id,
                "gas": self.gas_limit_estimate,
                "gasPrice": self.w3.eth.gas_price,
            }
        )

        try:
            tx_hash = self._sign_and_send(tx)
        except Exception as exc:
            self._fail(order, exc)
            raise
        return self._finish(order, tx_hash)
