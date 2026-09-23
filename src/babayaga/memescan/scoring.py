"""Pure filtering and ranking of DexScreener pair snapshots - no I/O."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class ScanThresholds:
    min_liquidity_usd: float = 20_000.0
    min_volume_h1_usd: float = 10_000.0
    min_age_minutes: float = 10.0  # younger than this is mostly launch-sniper noise
    max_age_hours: float = 72.0
    min_txns_h1: int = 50
    max_fdv_to_liquidity: float = 50.0  # huge FDV on thin liquidity = can't actually exit
    min_buy_ratio_h1: float = 0.55  # share of h1 txns that were buys


@dataclass
class PairSnapshot:
    chain: str
    symbol: str
    name: str
    token_address: str
    pair_url: str
    price_usd: float
    liquidity_usd: float
    fdv: float
    age_minutes: float
    volume_m5: float
    volume_h1: float
    buys_h1: int
    sells_h1: int
    change_m5: float
    change_h1: float
    change_h24: float

    @property
    def txns_h1(self) -> int:
        return self.buys_h1 + self.sells_h1

    @property
    def buy_ratio_h1(self) -> float:
        return self.buys_h1 / self.txns_h1 if self.txns_h1 else 0.0


@dataclass
class ScoredPair:
    pair: PairSnapshot
    score: float
    reasons: List[str] = field(default_factory=list)


def _num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_pair(raw: dict, now_ms: float) -> Optional[PairSnapshot]:
    """Build a snapshot from one DexScreener pair object; None if it lacks price/liquidity data."""
    base = raw.get("baseToken") or {}
    liquidity = _num((raw.get("liquidity") or {}).get("usd"))
    price = _num(raw.get("priceUsd"))
    created = raw.get("pairCreatedAt")
    if not base.get("address") or liquidity <= 0 or price <= 0 or not created:
        return None
    txns_h1 = (raw.get("txns") or {}).get("h1") or {}
    volume = raw.get("volume") or {}
    change = raw.get("priceChange") or {}
    return PairSnapshot(
        chain=raw.get("chainId", "?"),
        symbol=base.get("symbol", "?"),
        name=base.get("name", "?"),
        token_address=base["address"],
        pair_url=raw.get("url", ""),
        price_usd=price,
        liquidity_usd=liquidity,
        fdv=_num(raw.get("fdv") or raw.get("marketCap")),
        age_minutes=max(0.0, (now_ms - _num(created)) / 60_000),
        volume_m5=_num(volume.get("m5")),
        volume_h1=_num(volume.get("h1")),
        buys_h1=int(_num(txns_h1.get("buys"))),
        sells_h1=int(_num(txns_h1.get("sells"))),
        change_m5=_num(change.get("m5")),
        change_h1=_num(change.get("h1")),
        change_h24=_num(change.get("h24")),
    )


def rejection_reason(p: PairSnapshot, t: ScanThresholds) -> Optional[str]:
    if p.liquidity_usd < t.min_liquidity_usd:
        return f"liquidity ${p.liquidity_usd:,.0f} < ${t.min_liquidity_usd:,.0f}"
    if p.age_minutes < t.min_age_minutes:
        return f"too new ({p.age_minutes:.0f}m)"
    if p.age_minutes > t.max_age_hours * 60:
        return f"too old ({p.age_minutes / 60:.0f}h)"
    if p.volume_h1 < t.min_volume_h1_usd:
        return f"h1 volume ${p.volume_h1:,.0f} too low"
    if p.txns_h1 < t.min_txns_h1:
        return f"only {p.txns_h1} txns in h1"
    if p.fdv and p.fdv / p.liquidity_usd > t.max_fdv_to_liquidity:
        return f"FDV is {p.fdv / p.liquidity_usd:.0f}x liquidity"
    if p.buy_ratio_h1 < t.min_buy_ratio_h1:
        return f"sell pressure (buys {p.buy_ratio_h1:.0%})"
    return None


def score_pair(p: PairSnapshot) -> ScoredPair:
    """0-100 activity score. Weights are heuristics, not a backtested model."""
    reasons = []
    # Volume turnover: how much of the pool traded in the last hour.
    turnover = p.volume_h1 / p.liquidity_usd
    s_turnover = min(turnover / 2.0, 1.0) * 30
    # Acceleration: last 5m volume vs the h1 per-5m average (1.0 = steady).
    accel = p.volume_m5 / (p.volume_h1 / 12) if p.volume_h1 else 0.0
    s_accel = min(accel / 3.0, 1.0) * 25
    # Buy pressure above the 50/50 line.
    s_buys = min(max(p.buy_ratio_h1 - 0.5, 0.0) / 0.25, 1.0) * 20
    # Depth: log-scaled so $1M pools don't drown everything else.
    s_depth = min(math.log10(p.liquidity_usd / 10_000) / 2.0, 1.0) * 15 if p.liquidity_usd > 10_000 else 0.0
    # Positive but not already vertical: +5..+60% h1 scores best.
    s_trend = 10.0 if 5 <= p.change_h1 <= 60 else (5.0 if 0 < p.change_h1 < 5 else 0.0)

    if turnover >= 1.0:
        reasons.append(f"turnover {turnover:.1f}x pool/h")
    if accel >= 2.0:
        reasons.append(f"volume accelerating {accel:.1f}x")
    if p.buy_ratio_h1 >= 0.65:
        reasons.append(f"buys {p.buy_ratio_h1:.0%}")
    if p.change_h1 > 100:
        reasons.append(f"already +{p.change_h1:.0f}% h1 - late")
    return ScoredPair(pair=p, score=round(s_turnover + s_accel + s_buys + s_depth + s_trend, 1), reasons=reasons)


def rank(pairs: List[PairSnapshot], t: ScanThresholds) -> List[ScoredPair]:
    """Keep the deepest pool per token, drop rejects, sort by score descending."""
    best_by_token = {}
    for p in pairs:
        key = (p.chain, p.token_address)
        if key not in best_by_token or p.liquidity_usd > best_by_token[key].liquidity_usd:
            best_by_token[key] = p
    kept = [score_pair(p) for p in best_by_token.values() if rejection_reason(p, t) is None]
    return sorted(kept, key=lambda s: s.score, reverse=True)
