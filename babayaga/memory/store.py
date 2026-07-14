"""Persistent memory for the trading OS, backed by SQLite (stdlib).

The memory layer is the OS's long-term recall. Every meaningful event — ticks,
agent signals, coordinator decisions, fills — is journaled so that:

* agents can look back over recent history to compute features and detect
  regimes across runs, and
* a session can be audited or replayed after the fact.

It also stores a small key/value "knowledge base" that agents use to persist
learned state (e.g. a rolling estimate of an instrument's volatility regime)
between runs of the OS.

``:memory:`` is accepted as a path for ephemeral / test use.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from babayaga.kernel.events import Candle, Decision, Fill, Signal

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ticks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    ts REAL NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL
);
CREATE INDEX IF NOT EXISTS idx_ticks_symbol_ts ON ticks(symbol, ts);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    confidence REAL NOT NULL,
    rationale TEXT,
    features TEXT,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_symbol_ts ON signals(symbol, ts);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    size REAL NOT NULL,
    confidence REAL NOT NULL,
    rationale TEXT,
    stop_loss REAL,
    take_profit REAL,
    ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    size REAL NOT NULL,
    price REAL NOT NULL,
    reason TEXT,
    ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);
"""


class MemoryStore:
    def __init__(
        self,
        path: str | Path = ":memory:",
        max_ticks: int | None = None,
        max_signals: int | None = None,
        max_decisions: int | None = None,
        prune_every: int = 1000,
    ) -> None:
        """Persistent event/knowledge store.

        ``max_ticks`` / ``max_signals`` bound the two high-volume tables so an
        ultra-fast, nonstop run stays memory-safe. When set, only the most
        recent N rows are kept in each. The **trade ledger** (``fills``) and
        ``decisions`` are NEVER pruned — every trade is remembered forever.
        ``None`` means unbounded (the default, unchanged behaviour).
        """
        self.path = str(path)
        self.max_ticks = max_ticks
        self.max_signals = max_signals
        self.max_decisions = max_decisions
        self.prune_every = max(1, prune_every)
        self._since_tick_prune = 0
        self._since_signal_prune = 0
        self._since_decision_prune = 0
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False + a lock lets async tasks share one connection.
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _prune(self, table: str, keep: int) -> None:
        """Delete all but the newest ``keep`` rows of a high-volume table."""
        self._conn.execute(
            f"DELETE FROM {table} WHERE id <= "  # noqa: S608 — fixed identifiers
            f"(SELECT MAX(id) FROM {table}) - ?",
            (keep,),
        )

    # -- writes -----------------------------------------------------------
    def record_tick(self, c: Candle) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO ticks(symbol, ts, open, high, low, close, volume)"
                " VALUES(?,?,?,?,?,?,?)",
                (c.symbol, c.timestamp, c.open, c.high, c.low, c.close, c.volume),
            )
            if self.max_ticks is not None:
                self._since_tick_prune += 1
                if self._since_tick_prune >= self.prune_every:
                    self._since_tick_prune = 0
                    self._prune("ticks", self.max_ticks)
            self._conn.commit()

    def record_signal(self, s: Signal) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO signals(agent, symbol, side, confidence, rationale, features, ts)"
                " VALUES(?,?,?,?,?,?,?)",
                (
                    s.agent,
                    s.symbol,
                    s.side.value,
                    s.confidence,
                    s.rationale,
                    json.dumps(s.features),
                    s.timestamp,
                ),
            )
            if self.max_signals is not None:
                self._since_signal_prune += 1
                if self._since_signal_prune >= self.prune_every:
                    self._since_signal_prune = 0
                    self._prune("signals", self.max_signals)
            self._conn.commit()

    def record_decision(self, d: Decision) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO decisions(symbol, side, size, confidence, rationale,"
                " stop_loss, take_profit, ts) VALUES(?,?,?,?,?,?,?,?)",
                (
                    d.symbol,
                    d.side.value,
                    d.size,
                    d.confidence,
                    d.rationale,
                    d.stop_loss,
                    d.take_profit,
                    d.timestamp,
                ),
            )
            if self.max_decisions is not None:
                self._since_decision_prune += 1
                if self._since_decision_prune >= self.prune_every:
                    self._since_decision_prune = 0
                    self._prune("decisions", self.max_decisions)
            self._conn.commit()

    def record_fill(self, f: Fill) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO fills(symbol, side, size, price, reason, ts)"
                " VALUES(?,?,?,?,?,?)",
                (f.symbol, f.side.value, f.size, f.price, f.order_reason, f.timestamp),
            )
            self._conn.commit()

    # -- knowledge base ---------------------------------------------------
    def remember(self, key: str, value: Any) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO knowledge(key, value, updated_at) VALUES(?,?,?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value,"
                " updated_at=excluded.updated_at",
                (key, json.dumps(value), time.time()),
            )
            self._conn.commit()

    def recall(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM knowledge WHERE key=?", (key,)
            ).fetchone()
        return json.loads(row["value"]) if row else default

    # -- reads ------------------------------------------------------------
    def recent_closes(self, symbol: str, limit: int = 200) -> list[float]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT close FROM ticks WHERE symbol=? ORDER BY ts DESC LIMIT ?",
                (symbol, limit),
            ).fetchall()
        return [r["close"] for r in reversed(rows)]

    def recent_signals(self, symbol: str, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM signals WHERE symbol=? ORDER BY ts DESC LIMIT ?",
                (symbol, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def fills(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM fills ORDER BY ts").fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        with self._lock:
            for table in ("ticks", "signals", "decisions", "fills"):
                out[table] = self._conn.execute(
                    f"SELECT COUNT(*) AS n FROM {table}"  # noqa: S608 — fixed identifiers
                ).fetchone()["n"]
        return out

    def bulk_record_ticks(self, candles: Iterable[Candle]) -> None:
        with self._lock:
            self._conn.executemany(
                "INSERT INTO ticks(symbol, ts, open, high, low, close, volume)"
                " VALUES(?,?,?,?,?,?,?)",
                [
                    (c.symbol, c.timestamp, c.open, c.high, c.low, c.close, c.volume)
                    for c in candles
                ],
            )
            self._conn.commit()
