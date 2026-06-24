"""Builds the live feed/executor wiring for every venue actually referenced
by `settings.pairs`, and exposes it through a uniform `VenueRuntime` so the
engine never has to branch on venue kind except to detect the MT5 hedge leg.

Wallets, RPC connections, and the MT5 session are constructed eagerly here so
a bad RPC URL or a placeholder private key fails loudly at startup instead of
mid-loop. Executors (the part that needs a wallet/signing key) are only built
when `settings.dry_run` is False - in dry-run mode we only ever read quotes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Optional, Set

from babayaga.config import Settings
from babayaga.core.models import Fill, Order, Quote
from babayaga.execution.evm_executor import EvmV2Executor, EvmV3Executor
from babayaga.execution.mt5_executor import Mt5Executor
from babayaga.execution.solana_executor import JupiterExecutor
from babayaga.feeds.evm_dex import EvmV2DexFeed, EvmV3DexFeed
from babayaga.feeds.mt5_feed import Mt5Feed, Mt5Session
from babayaga.feeds.solana_dex import JupiterDexFeed
from babayaga.wallet.evm_wallet import EvmWallet
from babayaga.wallet.solana_wallet import SolanaWallet

GetQuoteFn = Callable[[str, str, float, Optional[str]], Awaitable[Quote]]
PlaceOrderFn = Callable[[Order, Optional[str]], Awaitable[Fill]]


@dataclass
class VenueRuntime:
    name: str
    kind: str
    get_quote: GetQuoteFn
    place_order: PlaceOrderFn


def _referenced_venues(settings: Settings) -> Set[str]:
    names: Set[str] = set()
    for pair in settings.pairs:
        for leg in pair.legs:
            names.add(leg.venue)
    return names


async def _no_executor(name: str, *_args, **_kwargs):
    raise RuntimeError(
        f"venue {name!r}: no executor was constructed because dry_run is True - "
        "the engine should never call place_order in dry-run mode"
    )


def _wrap(name: str, kind: str, get_quote_impl, place_order_impl) -> VenueRuntime:
    return VenueRuntime(name=name, kind=kind, get_quote=get_quote_impl, place_order=place_order_impl)


class _RuntimeFactory:
    """Internal helper that lazily creates and caches the shared wallets/
    session so every venue of the same kind reuses one wallet/connection."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._evm_wallet: Optional[EvmWallet] = None
        self._solana_wallet: Optional[SolanaWallet] = None
        self._mt5_session: Optional[Mt5Session] = None

    def evm_wallet(self) -> EvmWallet:
        if self._evm_wallet is None:
            self._evm_wallet = EvmWallet(self.settings.evm_private_key or "")
        return self._evm_wallet

    def solana_wallet(self) -> SolanaWallet:
        if self._solana_wallet is None:
            self._solana_wallet = SolanaWallet(self.settings.solana_private_key or "")
        return self._solana_wallet

    def mt5_session(self) -> Mt5Session:
        if self._mt5_session is None:
            s = self.settings
            if not (s.mt5_login and s.mt5_password and s.mt5_server):
                raise ValueError("MT5_LOGIN/MT5_PASSWORD/MT5_SERVER must all be set to use an mt5 venue")
            self._mt5_session = Mt5Session(s.mt5_login, s.mt5_password, s.mt5_server, s.mt5_terminal_path)
        return self._mt5_session

    def _rpc_url(self, chain_name: str) -> str:
        chain = self.settings.chains[chain_name]
        url = self.settings.rpc_urls.get(chain.rpc_env)
        if not url:
            raise ValueError(f"chain {chain_name!r}: {chain.rpc_env} is not set - required to quote/trade on it")
        return url

    def build(self, venue_name: str) -> VenueRuntime:
        venue = self.settings.venues[venue_name]
        dry_run = self.settings.dry_run

        if venue.kind == "evm_v2_router":
            chain = self.settings.chains[venue.chain]
            rpc_url = self._rpc_url(venue.chain)
            tokens = self.settings.tokens.get(venue.chain, {})
            if not venue.router_address:
                raise ValueError(f"venue {venue_name!r}: evm_v2_router requires router_address")
            feed = EvmV2DexFeed(venue_name, rpc_url, venue.router_address, venue.fee_bps, tokens)
            executor = None
            if not dry_run:
                executor = EvmV2Executor(
                    venue_name,
                    rpc_url,
                    venue.router_address,
                    tokens,
                    self.evm_wallet(),
                    chain.chain_id or 1,
                    chain.gas_limit_estimate or 200_000,
                )
            return self._wrap_simple(venue_name, venue.kind, feed, executor)

        if venue.kind == "evm_v3_quoter":
            chain = self.settings.chains[venue.chain]
            rpc_url = self._rpc_url(venue.chain)
            tokens = self.settings.tokens.get(venue.chain, {})
            if not venue.quoter_address:
                raise ValueError(f"venue {venue_name!r}: evm_v3_quoter requires quoter_address")
            feed = EvmV3DexFeed(venue_name, rpc_url, venue.quoter_address, venue.fee_bps, tokens)
            executor = None
            if not dry_run:
                if not venue.router_address:
                    raise ValueError(
                        f"venue {venue_name!r}: evm_v3_quoter requires router_address "
                        "(the SwapRouter02 deployment) to execute live, even though it's not needed for quoting"
                    )
                executor = EvmV3Executor(
                    venue_name,
                    rpc_url,
                    venue.router_address,
                    tokens,
                    self.evm_wallet(),
                    chain.chain_id or 1,
                    chain.gas_limit_estimate or 250_000,
                )
            return self._wrap_simple(venue_name, venue.kind, feed, executor)

        if venue.kind == "jupiter_aggregator":
            tokens = self.settings.tokens.get("solana", {})
            feed = JupiterDexFeed(
                venue_name,
                venue.fee_bps,
                tokens,
                slippage_bps=int(self.settings.risk.slippage_bps),
                dexes=venue.dexes,
            )
            executor = None
            if not dry_run:
                rpc_url = self._rpc_url("solana")
                executor = JupiterExecutor(
                    venue_name,
                    rpc_url,
                    tokens,
                    feed.decimals,
                    self.solana_wallet(),
                    slippage_bps=int(self.settings.risk.slippage_bps),
                    dexes=venue.dexes,
                )
            return self._wrap_simple(venue_name, venue.kind, feed, executor)

        if venue.kind == "mt5":
            session = self.mt5_session()
            feed = Mt5Feed(venue_name, venue.fee_bps, session)
            executor = Mt5Executor(venue_name, session) if not dry_run else None
            return self._wrap_mt5(venue_name, venue.kind, feed, executor)

        raise ValueError(f"venue {venue_name!r}: unknown kind {venue.kind!r}")

    @staticmethod
    def _wrap_simple(name: str, kind: str, feed, executor) -> VenueRuntime:
        async def get_quote(base: str, quote: str, size_base: float, _symbol: Optional[str] = None) -> Quote:
            return await feed.get_quote(base, quote, size_base)

        async def place_order(order: Order, _symbol: Optional[str] = None) -> Fill:
            if executor is None:
                await _no_executor(name)
            return await executor.execute(order)

        return _wrap(name, kind, get_quote, place_order)

    @staticmethod
    def _wrap_mt5(name: str, kind: str, feed, executor) -> VenueRuntime:
        async def get_quote(base: str, quote: str, size_base: float, symbol: Optional[str] = None) -> Quote:
            if not symbol:
                raise ValueError(f"venue {name!r}: mt5 quotes require a pair leg `symbol` (e.g. XAUUSD)")
            return await feed.get_quote(base, quote, size_base, symbol)

        async def place_order(order: Order, symbol: Optional[str] = None) -> Fill:
            if executor is None:
                await _no_executor(name)
            if not symbol:
                raise ValueError(f"venue {name!r}: mt5 orders require a pair leg `symbol` (e.g. XAUUSD)")
            return await executor.execute(order, symbol)

        return _wrap(name, kind, get_quote, place_order)


def build_runtimes(settings: Settings) -> Dict[str, VenueRuntime]:
    """Construct one VenueRuntime per venue actually used by `settings.pairs`."""
    factory = _RuntimeFactory(settings)
    return {name: factory.build(name) for name in sorted(_referenced_venues(settings))}
