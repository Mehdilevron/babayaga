"""Command-line entrypoint: `babayaga [--config PATH] [--env PATH] [--live|--dry-run] [--once]`.

Loads config/.env, builds the engine, and runs the scan/detect/execute loop
until interrupted (Ctrl-C) or the kill switch trips.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import List, Optional

from babayaga.config import load_settings
from babayaga.engine import Engine

logger = logging.getLogger(__name__)


def _parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="babayaga", description="Cross-venue arbitrage bot")
    parser.add_argument("--config", default="config/config.yaml", help="Path to config.yaml")
    parser.add_argument("--env", default=None, help="Path to .env (default: .env in the working directory)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="Force live trading, overriding config/.env dry_run")
    mode.add_argument("--dry-run", action="store_true", help="Force dry-run mode, overriding config/.env dry_run")
    mode.add_argument(
        "--quotes-only",
        action="store_true",
        help="Print live quotes/spreads for every pair each tick; never evaluates risk or places orders",
    )
    parser.add_argument("--once", action="store_true", help="Run a single scan/execute tick then exit")
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING, ...)")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    force_dry_run = None
    if args.live:
        force_dry_run = False
    elif args.dry_run or args.quotes_only:
        force_dry_run = True

    try:
        settings = load_settings(args.config, args.env, force_dry_run=force_dry_run)
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc

    if not settings.dry_run and not args.quotes_only:
        logger.warning(
            "*** LIVE MODE *** real funds will be signed and submitted automatically with no "
            "human approval step. Ctrl-C or touch %s to stop before the next tick.",
            settings.engine.kill_switch_file,
        )

    try:
        engine = Engine.from_settings(settings)
    except (ValueError, RuntimeError) as exc:
        logger.error("failed to start: %s", exc)
        raise SystemExit(1) from exc

    coro = (
        engine.run_quotes_only(iterations=1 if args.once else None)
        if args.quotes_only
        else engine.run(iterations=1 if args.once else None)
    )
    try:
        asyncio.run(coro)
    except KeyboardInterrupt:
        logger.info("interrupted, shutting down")


if __name__ == "__main__":
    main()
