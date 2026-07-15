"""Download REAL daily forex history (free, from stooq.com) for backtesting.

Run this on your own machine (it needs open internet):

    python3 scripts/fetch_history.py

It writes one CSV per instrument into ./data/ (Date,Open,High,Low,Close[,Volume]).
Then run the honest edge test:

    python3 -m babayaga.backtest data/*.csv
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

PAIRS = {
    "eurusd": "EUR/USD",
    "gbpusd": "GBP/USD",
    "usdjpy": "USD/JPY",
    "audusd": "AUD/USD",
    "usdcad": "USD/CAD",
    "xauusd": "XAU/USD",
}

OUT = Path(__file__).resolve().parent.parent / "data"


def fetch(code: str) -> str:
    url = f"https://stooq.com/q/d/l/?s={code}&i=d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        return resp.read().decode("utf-8", errors="replace")


def main() -> int:
    OUT.mkdir(exist_ok=True)
    ok = 0
    for code, name in PAIRS.items():
        try:
            body = fetch(code)
        except Exception as exc:  # noqa: BLE001
            print(f"  {name:8} FAILED: {exc}")
            continue
        lines = body.strip().splitlines()
        if len(lines) < 100 or not lines[0].lower().startswith("date"):
            print(f"  {name:8} FAILED: unexpected response ({lines[:1]})")
            continue
        path = OUT / f"{code}_d.csv"
        path.write_text(body)
        print(f"  {name:8} {len(lines) - 1:6} daily bars -> {path.relative_to(OUT.parent)}")
        ok += 1
    if ok == 0:
        print("\nNo data downloaded. If stooq is unreachable, export daily OHLC CSVs")
        print("(Date,Open,High,Low,Close) from any source into ./data/ instead.")
        return 1
    print(f"\nDone ({ok}/{len(PAIRS)}). Now run:  python3 -m babayaga.backtest data/*.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
