"""`babayaga-memescan`: poll DexScreener, print a ranked memecoin table, alert to Telegram.

Telegram is enabled when TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set in
.env; otherwise results are only printed.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from typing import List, Optional

from dotenv import load_dotenv

from babayaga.memescan.dexscreener import DexScreenerClient
from babayaga.memescan.scoring import ScanThresholds, parse_pair, rank
from babayaga.memescan.telegram import AlertCooldown, TelegramNotifier, format_alert

logger = logging.getLogger(__name__)


def _parse_args(argv: List[str]) -> argparse.Namespace:
    d = ScanThresholds()
    p = argparse.ArgumentParser(prog="babayaga-memescan", description="Memecoin liquidity/momentum scanner")
    p.add_argument("--chains", default="solana,base,bsc", help="Comma-separated DexScreener chain ids")
    p.add_argument("--interval", type=float, default=60.0, help="Seconds between scans")
    p.add_argument("--once", action="store_true", help="Scan once and exit")
    p.add_argument("--top", type=int, default=10, help="Rows to print per scan")
    p.add_argument("--alert-score", type=float, default=60.0, help="Min score to send a Telegram alert")
    p.add_argument("--cooldown-min", type=float, default=120.0, help="Minutes before re-alerting the same token")
    p.add_argument("--min-liquidity", type=float, default=d.min_liquidity_usd)
    p.add_argument("--min-volume-h1", type=float, default=d.min_volume_h1_usd)
    p.add_argument("--max-age-hours", type=float, default=d.max_age_hours)
    p.add_argument("--env", default=None, help="Path to .env (default: .env in the working directory)")
    p.add_argument("--log-level", default="INFO")
    return p.parse_args(argv)


def scan_once(client: DexScreenerClient, chains: List[str], thresholds: ScanThresholds):
    now_ms = time.time() * 1000
    snapshots = []
    for chain, addrs in client.discover_tokens(chains).items():
        for raw in client.pairs_for_tokens(chain, addrs):
            snap = parse_pair(raw, now_ms)
            if snap:
                snapshots.append(snap)
    return rank(snapshots, thresholds), len(snapshots)


def main(argv: Optional[List[str]] = None) -> None:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv(args.env or ".env")

    thresholds = ScanThresholds(
        min_liquidity_usd=args.min_liquidity,
        min_volume_h1_usd=args.min_volume_h1,
        max_age_hours=args.max_age_hours,
    )
    chains = [c.strip() for c in args.chains.split(",") if c.strip()]
    client = DexScreenerClient()

    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    notifier = TelegramNotifier(token, chat) if token and chat else None
    if notifier is None:
        logger.info("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set - printing only, no alerts")
    cooldown = AlertCooldown(args.cooldown_min * 60)

    try:
        while True:
            ranked, seen = scan_once(client, chains, thresholds)
            print(f"\n=== {time.strftime('%H:%M:%S')}  {seen} pairs seen, {len(ranked)} passed filters ===")
            for s in ranked[: args.top]:
                p = s.pair
                print(
                    f"{s.score:5.1f}  {p.symbol[:12]:<12} {p.chain:<7} liq ${p.liquidity_usd:>11,.0f}  "
                    f"h1vol ${p.volume_h1:>11,.0f}  1h {p.change_h1:+7.1f}%  buys {p.buy_ratio_h1:4.0%}  {p.pair_url}"
                )
            if notifier:
                for s in ranked:
                    if s.score >= args.alert_score and cooldown.should_alert(f"{s.pair.chain}:{s.pair.token_address}"):
                        notifier.send(format_alert(s))
            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        logger.info("stopped")


if __name__ == "__main__":
    main()
