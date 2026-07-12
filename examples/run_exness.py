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
    EXNESS_SYMBOL     instrument, default "XAU/USD" (gold)
    EXNESS_SUFFIX     (optional) symbol suffix your account uses, e.g. "m" -> XAUUSDm
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
    symbol = os.environ.get("EXNESS_SYMBOL", "XAU/USD")
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

    broker = ExnessMT5Broker(mt5, symbol_suffix=suffix, confirm_live=confirm_live)
    mode = "LIVE (real money)" if broker.is_live else "DEMO (virtual money)"
    if broker.is_live and not confirm_live:
        print("REAL account detected and CONFIRM_LIVE is not set — the bot will "
              "NOT place orders. Set CONFIRM_LIVE=I_UNDERSTAND to enable (your call).")
    print(f"Exness account: {mode}  |  symbol {symbol}{(' suffix ' + suffix) if suffix else ''}")
    print(f"Balance: {broker.cash:.2f}   Equity: {broker.equity:.2f}")

    # sim_steps=0 => no simulated feed; we attach the real Exness feed instead.
    os_ = TradingOS(Config(symbols=(symbol,), sim_steps=0))
    os_.broker = broker
    os_.execution.broker = broker
    os_.attach_feed(symbol, ExnessMT5Feed(mt5, symbol, timeframe="M1", suffix=suffix))

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
