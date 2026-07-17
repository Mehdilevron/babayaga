"""Download REAL daily forex history for backtesting — no API key, no deps.

Run this on your own machine (needs open internet):

    python3 scripts/fetch_history.py

Data source: the Frankfurter API (https://frankfurter.dev), which serves the
European Central Bank's official daily reference rates — real forex history back
to 1999, as clean JSON with no bot-challenge wall (unlike stooq/Yahoo, which now
block scripted downloads). One reference "close" per business day per pair.

It writes one CSV per pair into ./data/ (Date,Open,High,Low,Close). ECB gives a
single daily rate, so Open=High=Low=Close — fine for this close-based strategy.
Then run the edge test:

    python3 -m babayaga.backtest data/*.csv

Note: gold (XAU) is not an ECB fiat rate, so it isn't available here — the FX
majors below are what matters for the strategy anyway.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.request
from pathlib import Path

BASE = "https://api.frankfurter.dev/v1"
START_YEAR = 2010

# symbol -> (base currency, quote currency)
PAIRS = {
    "eurusd": ("EUR", "USD"),
    "gbpusd": ("GBP", "USD"),
    "usdjpy": ("USD", "JPY"),
    "audusd": ("AUD", "USD"),
    "usdcad": ("USD", "CAD"),
    "usdchf": ("USD", "CHF"),
    "nzdusd": ("NZD", "USD"),
}

OUT = Path(__file__).resolve().parent.parent / "data"


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        return json.loads(resp.read().decode())


def fetch_series(frm: str, to: str) -> dict[str, float]:
    """Fetch the full daily rate history for one pair, year by year."""
    rates: dict[str, float] = {}
    today = dt.date.today()
    for year in range(START_YEAR, today.year + 1):
        start = f"{year}-01-01"
        end = f"{year}-12-31" if year < today.year else today.isoformat()
        data = _get(f"{BASE}/{start}..{end}?base={frm}&symbols={to}")
        for date, d in data.get("rates", {}).items():
            if to in d and d[to]:
                rates[date] = float(d[to])
    return dict(sorted(rates.items()))


def main() -> int:
    OUT.mkdir(exist_ok=True)
    ok = 0
    for code, (frm, to) in PAIRS.items():
        try:
            series = fetch_series(frm, to)
        except Exception as exc:  # noqa: BLE001
            print(f"  {frm}/{to:4} FAILED: {exc}")
            continue
        if len(series) < 200:
            print(f"  {frm}/{to:4} FAILED: only {len(series)} points returned")
            continue
        path = OUT / f"{code}_d.csv"
        lines = ["Date,Open,High,Low,Close"]
        for date, rate in series.items():
            lines.append(f"{date},{rate:.6f},{rate:.6f},{rate:.6f},{rate:.6f}")
        path.write_text("\n".join(lines))
        dates = list(series)
        print(f"  {frm}/{to:4} {len(series):5} daily bars ({dates[0]} → {dates[-1]}) "
              f"-> {path.relative_to(OUT.parent)}")
        ok += 1

    if ok == 0:
        print("\nNo data downloaded. Check your internet connection, or export daily")
        print("OHLC CSVs (Date,Open,High,Low,Close) from any source into ./data/.")
        return 1
    print(f"\nDone ({ok}/{len(PAIRS)} pairs). Now run:\n"
          f"    python3 -m babayaga.backtest data/*.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
