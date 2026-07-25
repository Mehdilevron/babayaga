"""Economic-calendar / news blackout guard.

High-impact economic news — NFP, FOMC, CPI, rate decisions — spikes price
through stops and blows the spread wide open for a few minutes. Professionals
do not hold or open positions into it; they stand aside and let the storm pass.
This module lets BabaYaga do the same: given an economic calendar, it blocks
NEW entries in a window around any high-impact event that touches the traded
instrument's currencies. Existing positions keep their protective stops.

It is deliberately data-source-agnostic. Provide events however you like:

* a CSV the owner maintains or exports (ForexFactory, Myfxbook, investing.com):
  ``date,impact,currency`` with an ISO timestamp, e.g.
  ``2026-02-06T13:30:00,high,USD``  (times in UTC);
* or build ``NewsEvent`` objects from any feed and pass them in directly.

No network is required by the core; a live fetcher can be layered on top.
"""

from __future__ import annotations

import csv
import datetime as dt
from dataclasses import dataclass
from pathlib import Path

_IMPACT_RANK = {"low": 1, "medium": 2, "high": 3}


def currencies_of(symbol: str) -> set[str]:
    """``EUR/USD`` -> {'EUR', 'USD'}; ``XAU/USD`` -> {'XAU', 'USD'}."""
    return {p.strip().upper() for p in symbol.split("/") if p.strip()}


@dataclass(frozen=True)
class NewsEvent:
    timestamp: float          # unix seconds, UTC
    impact: str               # "low" | "medium" | "high"
    currency: str             # "USD", "EUR", ... or "*"/"ALL" for market-wide

    def affects(self, symbol_currencies: set[str]) -> bool:
        cur = self.currency.strip().upper()
        return cur in ("*", "ALL", "ANY") or cur in symbol_currencies


class EconomicCalendar:
    """A sorted list of economic events, queryable by time window + impact."""

    def __init__(self, events: list[NewsEvent] | None = None) -> None:
        self.events = sorted(events or [], key=lambda e: e.timestamp)

    @classmethod
    def from_csv(cls, path: str | Path) -> "EconomicCalendar":
        """Load ``date,impact,currency`` rows (ISO date, UTC). Bad rows skipped."""
        events: list[NewsEvent] = []
        p = Path(path)
        if not p.exists():
            return cls(events)
        with open(p, newline="") as f:
            for row in csv.DictReader(f):
                r = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
                try:
                    when = dt.datetime.fromisoformat(r["date"])
                    if when.tzinfo is None:
                        when = when.replace(tzinfo=dt.timezone.utc)
                    ts = when.timestamp()
                    impact = r.get("impact", "high").lower()
                    currency = r.get("currency", "*")
                except (KeyError, ValueError):
                    continue
                if impact in _IMPACT_RANK:
                    events.append(NewsEvent(ts, impact, currency))
        return cls(events)


class NewsGuard:
    """Blocks NEW entries around high-impact events for the affected currencies.

    ``blocked(symbol, now_ts)`` returns ``(True, reason)`` if any qualifying
    event falls within ``[now - after, now + before]`` — i.e. it stands aside
    both just BEFORE a scheduled event (you can't know the outcome) and for a
    cool-off AFTER it (the spike + spread widening). Off by default: an empty
    calendar never blocks anything.
    """

    def __init__(
        self,
        calendar: EconomicCalendar,
        minutes_before: float = 30.0,
        minutes_after: float = 15.0,
        min_impact: str = "high",
    ) -> None:
        self.calendar = calendar
        self.before_s = minutes_before * 60.0
        self.after_s = minutes_after * 60.0
        self.min_rank = _IMPACT_RANK.get(min_impact.lower(), 3)

    def blocked(self, symbol: str, now_ts: float) -> tuple[bool, str]:
        if not self.calendar.events:
            return (False, "")
        curs = currencies_of(symbol)
        for e in self.calendar.events:
            if _IMPACT_RANK.get(e.impact, 0) < self.min_rank:
                continue
            if not e.affects(curs):
                continue
            # event is "near now" if now is within [event - before, event + after]
            if e.timestamp - self.before_s <= now_ts <= e.timestamp + self.after_s:
                when = dt.datetime.fromtimestamp(
                    e.timestamp, tz=dt.timezone.utc
                ).strftime("%Y-%m-%d %H:%M UTC")
                return (True, f"news blackout: {e.impact} {e.currency} event at {when}")
        return (False, "")
