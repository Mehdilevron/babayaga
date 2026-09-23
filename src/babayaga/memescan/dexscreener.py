"""DexScreener public API client (free, no key). Rate limits are roughly
60 req/min on the profile/boost endpoints and 300 req/min on pair lookups."""

from __future__ import annotations

import logging
from typing import Iterable, List

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.dexscreener.com"
DISCOVERY_ENDPOINTS = ("/token-profiles/latest/v1", "/token-boosts/latest/v1", "/token-boosts/top/v1")
MAX_ADDRESSES_PER_LOOKUP = 30


class DexScreenerClient:
    def __init__(self, timeout_s: float = 10.0, session: requests.Session | None = None):
        self.timeout_s = timeout_s
        self.session = session or requests.Session()

    def _get(self, path: str):
        resp = self.session.get(BASE_URL + path, timeout=self.timeout_s)
        resp.raise_for_status()
        return resp.json()

    def discover_tokens(self, chains: Iterable[str]) -> dict:
        """Map chain -> set of token addresses from the latest profiles and boosts."""
        wanted = set(chains)
        found = {c: set() for c in wanted}
        for path in DISCOVERY_ENDPOINTS:
            try:
                items = self._get(path)
            except (requests.RequestException, ValueError) as exc:
                logger.warning("dexscreener %s failed: %s", path, exc)
                continue
            for item in items if isinstance(items, list) else []:
                chain, addr = item.get("chainId"), item.get("tokenAddress")
                if chain in wanted and addr:
                    found[chain].add(addr)
        return found

    def pairs_for_tokens(self, chain: str, addresses: Iterable[str]) -> List[dict]:
        addrs = sorted(addresses)
        pairs: List[dict] = []
        for i in range(0, len(addrs), MAX_ADDRESSES_PER_LOOKUP):
            batch = ",".join(addrs[i : i + MAX_ADDRESSES_PER_LOOKUP])
            try:
                data = self._get(f"/tokens/v1/{chain}/{batch}")
            except (requests.RequestException, ValueError) as exc:
                logger.warning("dexscreener pair lookup on %s failed: %s", chain, exc)
                continue
            pairs.extend(data if isinstance(data, list) else data.get("pairs") or [])
        return pairs
