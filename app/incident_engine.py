from __future__ import annotations

import hashlib
import re
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Iterable

from .db import connect

UNITS = (
    "top40-archiver-web.service",
    "top40-archiver-download.service",
    "top40-archiver-check.service",
    "top40-archiver-cover-art.service",
    "top40-archiver-id3-cover.service",
)

PATTERNS = (
    ("youtube_rate_limit", "critical", 0.98, ("http error 429", "too many requests", "rate limit"), "Pauzeer downloads en houd één worker aan."),
    ("youtube_bot_check", "critical", 0.99, ("not a bot", "sign in to confirm", "captcha"), "Pauzeer downloads; hervat pas na een geslaagde testdownload."),
    ("youtube_forbidden", "warning", 0.90, ("http error 403", "forbidden"), "Controleer bron, cookies en yt-dlp-versie."),
    ("database_locked", "warning", 0.96, ("database is locked", "sqlite_busy"), "Wacht lopende databaseactie af en beperk paralleliteit."),
    ("storage", "critical", 0.99, ("no space left", "read-only file system", "permission denied"), "Controleer vrije ruimte, mount en schrijfrechten."),
    ("network", "warning", 0.82, ("timed out", "temporary failure", "name resolution", "connection reset"), "Stel retries uit en controleer netwerkbereikbaarheid."),
    ("ffmpeg", "warning", 0.90, ("ffmpeg", "invalid data found", "conversion failed"), "Controleer bronbestand en FFmpeg-uitvoer."),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_incident_schema() -> None:
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS ai_incidents (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          fingerprint TEXT NOT NULL UNIQUE,
          category TEXT NOT NULL,
          severity TEXT NOT NULL,
          confidence REAL NOT NULL,
          title TEXT NOT NULL,
          evidence TEXT NOT NULL,
          recommendation TEXT NOT NULL,
          occurrences INTEGER NOT NULL DEFAULT 1,
          first_seen TEXT NOT NULL,
          last_seen TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'open'
        );
        CREATE INDEX IF NOT EXISTS idx_ai_incidents_last_seen ON ai_incidents(last_seen DESC);
        CREATE INDEX IF NOT EXISTS idx_ai_incidents_status ON ai_incidents(status);
        CREATE TABLE IF NOT EXISTS ai_incident_state (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        """)


def classify_line(line: str) -> dict | None:
    text = " ".join(str(line or "").split())
    lowered = text.casefold()
    for category, severity, confidence, markers, recommendation in PATTERNS:
        if any(marker in lowered for marker in markers):
            normalized = re.sub(r"\b\d+\b", "#", lowered)[-700:]
            fingerprint = hashlib.sha256(f"{category}|{normalized}".encode()).hexdigest()[:24]
            return {
                "fingerprint": fingerprint,
                "category": category,
                "severity": severity,
                "confidence": confidence,
                "title": category.replace("_", " ").title(),
                "evidence": text[-1500:],
                "recommendation": recommendation,
            }
    return None


def read_journal(minutes: int = 20, lines: int = 500) -> list[str]:
    since = (datetime.now() - timedelta(minutes=max(1, minutes))).strftime("%Y-%m-%d %H:%M:%S")
    command = ["journalctl", "--no-pager", "--since", since, "-n", str(max(20, lines)), "-o", "short-iso"]
    for unit in UNITS:
        command.extend(["-u", unit])
    result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
    return result.stdout.splitlines()


def store_incidents(items: Iterable[dict]) -> int:
    init_incident_schema()
    count = 0
    timestamp = _now()
    with connect() as con:
        for item in items:
            con.execute("""
                INSERT INTO ai_incidents(
                  fingerprint,category,severity,confidence,title,evidence,recommendation,
                  occurrences,first_seen,last_seen,status
                ) VALUES(?,?,?,?,?,?,?,1,?,?,'open')
                ON CONFLICT(fingerprint) DO UPDATE SET
                  severity=excluded.severity,
                  confidence=MAX(ai_incidents.confidence, excluded.confidence),
                  evidence=excluded.evidence,
                  recommendation=excluded.recommendation,
                  occurrences=ai_incidents.occurrences+1,
                  last_seen=excluded.last_seen,
                  status='open'
            """, (
                item["fingerprint"], item["category"], item["severity"], item["confidence"],
                item["title"], item["evidence"], item["recommendation"], timestamp, timestamp,
            ))
            count += 1
    return count


def update_circuit_breaker() -> dict:
    init_incident_schema()
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat(timespec="seconds")
    with connect() as con:
        row = con.execute("""
            SELECT COALESCE(SUM(occurrences),0) AS total
            FROM ai_incidents
            WHERE status='open' AND severity='critical'
              AND category IN ('youtube_rate_limit','youtube_bot_check')
              AND last_seen >= ?
        """, (cutoff,)).fetchone()
        total = int(row["total"] if row else 0)
        active = total >= 3
        con.execute("""
            INSERT INTO ai_incident_state(key,value,updated_at) VALUES('download_circuit_breaker',?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at
        """, ("1" if active else "0", _now()))
    return {"active": active, "critical_occurrences_15m": total}


def scan_journal(minutes: int = 20) -> dict:
    lines = read_journal(minutes=minutes)
    matches = [item for line in lines if (item := classify_line(line))]
    stored = store_incidents(matches)
    return {"lines": len(lines), "matches": len(matches), "stored": stored, "circuit_breaker": update_circuit_breaker()}


def list_incidents(limit: int = 100, status: str = "open") -> list[dict]:
    init_incident_schema()
    with connect() as con:
        rows = con.execute("""
            SELECT * FROM ai_incidents
            WHERE (?='all' OR status=?)
            ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                     last_seen DESC
            LIMIT ?
        """, (status, status, max(1, min(limit, 500)))).fetchall()
        return [dict(row) for row in rows]


def incident_summary() -> dict:
    init_incident_schema()
    with connect() as con:
        counts = con.execute("SELECT severity,COUNT(*) AS count FROM ai_incidents WHERE status='open' GROUP BY severity").fetchall()
        state = con.execute("SELECT value,updated_at FROM ai_incident_state WHERE key='download_circuit_breaker'").fetchone()
    return {
        "counts": {row["severity"]: int(row["count"]) for row in counts},
        "circuit_breaker": {"active": bool(state and state["value"] == "1"), "updated_at": state["updated_at"] if state else None},
    }
