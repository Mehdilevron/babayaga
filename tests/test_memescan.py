"""Pure tests for the memecoin scanner's parsing, filters, ranking, and alert plumbing."""

from __future__ import annotations

from babayaga.memescan.scoring import ScanThresholds, parse_pair, rank, rejection_reason
from babayaga.memescan.telegram import AlertCooldown, format_alert

NOW_MS = 1_800_000_000_000


def _raw(addr="TOKEN1", liq=100_000, vol_h1=150_000, vol_m5=30_000, buys=300, sells=150,
         age_min=180, fdv=2_000_000, ch_h1=20.0, symbol="MEME"):
    return {
        "chainId": "solana",
        "url": f"https://dexscreener.com/solana/{addr}",
        "baseToken": {"address": addr, "symbol": symbol, "name": symbol},
        "priceUsd": "0.00123",
        "liquidity": {"usd": liq},
        "fdv": fdv,
        "pairCreatedAt": NOW_MS - age_min * 60_000,
        "volume": {"m5": vol_m5, "h1": vol_h1},
        "txns": {"h1": {"buys": buys, "sells": sells}},
        "priceChange": {"m5": 2.0, "h1": ch_h1, "h24": 50.0},
    }


def test_parse_pair_reads_fields():
    p = parse_pair(_raw(), NOW_MS)
    assert p.symbol == "MEME" and p.liquidity_usd == 100_000
    assert p.age_minutes == 180
    assert p.txns_h1 == 450 and abs(p.buy_ratio_h1 - 300 / 450) < 1e-9


def test_parse_pair_skips_incomplete_data():
    raw = _raw()
    raw["liquidity"] = {}
    assert parse_pair(raw, NOW_MS) is None
    raw = _raw()
    raw.pop("pairCreatedAt")
    assert parse_pair(raw, NOW_MS) is None


def test_filters_reject_rug_shapes():
    t = ScanThresholds()
    assert rejection_reason(parse_pair(_raw(), NOW_MS), t) is None
    assert "liquidity" in rejection_reason(parse_pair(_raw(liq=5_000), NOW_MS), t)
    assert "too new" in rejection_reason(parse_pair(_raw(age_min=2), NOW_MS), t)
    assert "too old" in rejection_reason(parse_pair(_raw(age_min=100 * 60), NOW_MS), t)
    assert "FDV" in rejection_reason(parse_pair(_raw(fdv=100_000_000), NOW_MS), t)
    assert "sell pressure" in rejection_reason(parse_pair(_raw(buys=100, sells=300), NOW_MS), t)


def test_rank_orders_by_score_and_dedupes_by_token():
    hot = _raw(addr="HOT", vol_h1=250_000, vol_m5=60_000, buys=400, sells=100)
    calm = _raw(addr="CALM", vol_h1=20_000, vol_m5=1_000, buys=160, sells=120, ch_h1=1.0)
    shallow_dup = _raw(addr="HOT", liq=30_000)
    ranked = rank([parse_pair(r, NOW_MS) for r in (calm, hot, shallow_dup)], ScanThresholds())
    assert [s.pair.token_address for s in ranked] == ["HOT", "CALM"]
    assert ranked[0].pair.liquidity_usd == 100_000
    assert 0 <= ranked[1].score < ranked[0].score <= 100


def test_cooldown_suppresses_repeat_alerts():
    t = [0.0]
    cd = AlertCooldown(60, clock=lambda: t[0])
    assert cd.should_alert("a")
    assert not cd.should_alert("a")
    assert cd.should_alert("b")
    t[0] = 61
    assert cd.should_alert("a")


def test_format_alert_escapes_symbol_and_carries_disclaimer():
    ranked = rank([parse_pair(_raw(symbol="<PEPE>"), NOW_MS)], ScanThresholds())
    msg = format_alert(ranked[0])
    assert "&lt;PEPE&gt;" in msg and "not a buy call" in msg
