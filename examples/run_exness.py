"""Run BabaYaga OS against an Exness account via MetaTrader 5 (Windows/VPS).

This wires the Exness MT5 feed + broker into the trading OS and serves the live
dashboard. It is meant to run on a Windows machine or VPS with the MetaTrader 5
terminal installed and logged into your Exness account, plus:

    pip install MetaTrader5

Configure via environment variables:

    EXNESS_LOGIN      your MT5 account number (e.g. 12345678)
    EXNESS_PASSWORD   the account password
    EXNESS_SERVER     the MT5 server name (e.g. "Exness-MT5Trial9" or your live server)
    MT5_PATH          (optional) full path to terminal64.exe
    EXNESS_SYMBOL     one instrument or a comma-separated basket the bot scans,
                      default "EUR/USD,GBP/USD,USD/JPY,AUD/USD,USD/CAD"
    EXNESS_SUFFIX     (optional) symbol suffix your account uses, e.g. "m" -> XAUUSDm
    MAX_LOT           (optional, recommended) hard cap on lots per order, e.g. 0.01
    DAILY_MAX_LOSS    (optional) stop opening trades after this much loss in a
                      single day (auto-resets next day), e.g. 100
    MAX_TOTAL_LOSS    (optional, recommended) LATCHING hard stop: at this much
                      total loss the bot flattens all positions and stops for
                      good, staying stopped across restarts until you delete the
                      HALTED.lock file. e.g. 200
    HALT_LOCK         (optional) path of the hard-stop lock file (default HALTED.lock)
    CONFIRM_LIVE      must be exactly "I_UNDERSTAND" to allow a REAL account to trade

SAFETY: On a REAL (live) account the broker refuses to place orders unless
CONFIRM_LIVE=I_UNDERSTAND. Leave it unset to run safely on a demo account. Run
demo for a good while before you even consider anything else.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from babayaga import Config, TradingOS
from babayaga.dashboard import Dashboard
from babayaga.integration.exness import ExnessMT5Broker, ExnessMT5Feed, connect, load_mt5


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise SystemExit(f"Missing required environment variable: {name}")
    return val


def main() -> int:
    # EXNESS_SYMBOL may be a single instrument or a comma-separated basket the
    # bot scans together, e.g. "EUR/USD,GBP/USD,USD/JPY,AUD/USD,USD/CAD".
    raw = os.environ.get("EXNESS_SYMBOL", "EUR/USD,GBP/USD,USD/JPY,AUD/USD,USD/CAD")
    symbols = tuple(s.strip() for s in raw.split(",") if s.strip())
    suffix = os.environ.get("EXNESS_SUFFIX", "")
    confirm_live = os.environ.get("CONFIRM_LIVE", "") == "I_UNDERSTAND"

    mt5 = load_mt5()
    connect(
        mt5,
        login=int(_require("EXNESS_LOGIN")),
        password=_require("EXNESS_PASSWORD"),
        server=_require("EXNESS_SERVER"),
        terminal_path=os.environ.get("MT5_PATH") or None,
    )

    max_lot = os.environ.get("MAX_LOT")
    daily_max_loss = os.environ.get("DAILY_MAX_LOSS")
    max_total_loss = os.environ.get("MAX_TOTAL_LOSS")

    # Persistent hard-stop lock. If a previous session tripped the total-loss
    # kill-switch, this file is on disk and the bot refuses to trade until you
    # clear it (your explicit command to resume).
    lock_path = Path(os.environ.get("HALT_LOCK", "HALTED.lock")).resolve()

    def _write_halt_lock(reason: str) -> None:
        lock_path.write_text(reason)
        print(f"[risk] HARD STOP engaged. Lock written to {lock_path}\n"
              f"       To resume trading later, delete that file and restart:\n"
              f"           rm \"{lock_path}\"")

    broker = ExnessMT5Broker(
        mt5,
        symbol_suffix=suffix,
        confirm_live=confirm_live,
        max_lot=float(max_lot) if max_lot else None,
        daily_max_loss=float(daily_max_loss) if daily_max_loss else None,
        max_total_loss=float(max_total_loss) if max_total_loss else None,
        on_halt=_write_halt_lock,
    )
    if lock_path.exists():
        broker.force_halt("existing HALTED.lock")
        print(f"[risk] Found {lock_path} — the hard stop is still engaged from a "
              f"previous session. Trading is disabled.\n"
              f"       Delete the file to resume:  rm \"{lock_path}\"")

    mode = "LIVE (real money)" if broker.is_live else "DEMO (virtual money)"
    if broker.is_live and not confirm_live:
        print("REAL account detected and CONFIRM_LIVE is not set — the bot will "
              "NOT place orders. Set CONFIRM_LIVE=I_UNDERSTAND to enable (your call).")
    basket = ", ".join(symbols) + (f"  (suffix {suffix})" if suffix else "")
    print(f"Exness account: {mode}  |  pairs: {basket}")
    print(f"Balance: {broker.cash:.2f}   Equity: {broker.equity:.2f}")

    # sim_steps=0 => no simulated feed; we attach a real Exness feed per pair.
    os_ = TradingOS(Config(symbols=symbols, sim_steps=0))
    os_.broker = broker
    os_.execution.broker = broker
    for sym in symbols:
        os_.attach_feed(sym, ExnessMT5Feed(mt5, sym, timeframe="M1", suffix=suffix))

    dash = Dashboard(os_, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8765")))
    dash.serve_forever_in_thread()
    print(f"Dashboard: http://{dash.host}:{dash.port}")

    try:
        asyncio.run(os_.run())
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        dash.shutdown()
        os_.shutdown()
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
