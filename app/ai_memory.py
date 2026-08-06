from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .config import DATA_DIR

AI_MEMORY_PATH = DATA_DIR / "ai_memory.sqlite"

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS incident (
 id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, service TEXT NOT NULL,
 severity TEXT NOT NULL, title TEXT NOT NULL, detail TEXT NOT NULL,
 confidence REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'open',
 first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, occurrences INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS solution (
 id INTEGER PRIMARY KEY, incident_fingerprint TEXT NOT NULL, action TEXT NOT NULL,
 explanation TEXT NOT NULL, success_rate REAL NOT NULL DEFAULT 0,
 uses INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history (
 id INTEGER PRIMARY KEY, event_type TEXT NOT NULL, service TEXT,
 message TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS metrics (
 id INTEGER PRIMARY KEY, metric TEXT NOT NULL, value REAL NOT NULL,
 labels_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learning (
 id INTEGER PRIMARY KEY, pattern TEXT UNIQUE NOT NULL, recommendation TEXT NOT NULL,
 confidence REAL NOT NULL DEFAULT 0, evidence_count INTEGER NOT NULL DEFAULT 1,
 updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_created ON history(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_metrics_name_created ON metrics(metric, created_at DESC);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    AI_MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(AI_MEMORY_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def remember_event(event_type: str, message: str, service: str | None = None, metadata: dict | None = None) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO history(event_type,service,message,metadata_json,created_at) VALUES(?,?,?,?,?)",
            (event_type, service, message, json.dumps(metadata or {}, ensure_ascii=False), _now()),
        )


def timeline(limit: int = 100) -> list[dict[str, object]]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM history ORDER BY id DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()
    return [dict(row) | {"metadata": json.loads(row["metadata_json"])} for row in rows]


def store_metric(metric: str, value: float, labels: dict | None = None) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO metrics(metric,value,labels_json,created_at) VALUES(?,?,?,?)",
            (metric, float(value), json.dumps(labels or {}, ensure_ascii=False), _now()),
        )


def learn(pattern: str, recommendation: str, confidence: float) -> None:
    with connect() as conn:
        conn.execute("""
        INSERT INTO learning(pattern,recommendation,confidence,evidence_count,updated_at)
        VALUES(?,?,?,?,?)
        ON CONFLICT(pattern) DO UPDATE SET
          recommendation=excluded.recommendation,
          confidence=max(learning.confidence, excluded.confidence),
          evidence_count=learning.evidence_count+1,
          updated_at=excluded.updated_at
        """, (pattern, recommendation, max(0, min(float(confidence), 1)), 1, _now()))


def best_learning(pattern: str) -> dict[str, object] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM learning WHERE pattern=? OR pattern LIKE ? ORDER BY confidence DESC,evidence_count DESC LIMIT 1",
            (pattern, f"%{pattern}%"),
        ).fetchone()
    return dict(row) if row else None
