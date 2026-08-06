from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import DATA_DIR
from .db import connect, now_iso

LOG_FILE = DATA_DIR / "download-rejections.jsonl"


def classify_rejection(reason: str) -> str:
    text = " ".join(str(reason or "").casefold().split())
    rules = (
        ("youtube_bot_check", ("sign in to confirm you're not a bot", "not a bot")),
        ("youtube_private", ("private video", "video is private")),
        ("youtube_removed", ("removed by the uploader", "video unavailable", "this video is unavailable")),
        ("youtube_geo_block", ("not available in your country", "geo-restricted")),
        ("youtube_copyright", ("copyright claim", "copyright")),
        ("no_search_results", ("geen youtube-resultaten gevonden",)),
        ("low_match_score", ("geen betrouwbaar youtube-resultaat", "beste score")),
        ("invalid_source_url", ("geen bruikbare url",)),
        ("rate_limit", ("http error 429", "too many requests")),
        ("forbidden", ("http error 403", "forbidden")),
        ("timeout", ("timeout", "timed out")),
        ("network", ("connection", "network", "temporary failure", "name resolution")),
        ("storage", ("no space left", "read-only file system", "permission denied")),
        ("database", ("database is locked", "sqlite")),
    )
    for category, markers in rules:
        if any(marker in text for marker in markers):
            return category
    return "other"


def _ensure_table() -> None:
    with connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS download_rejection_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              track_id INTEGER,
              artist TEXT NOT NULL,
              title TEXT NOT NULL,
              status TEXT NOT NULL,
              category TEXT NOT NULL,
              reason TEXT NOT NULL,
              attempts INTEGER NOT NULL DEFAULT 0,
              search_query TEXT,
              source_url TEXT,
              created_at TEXT NOT NULL
            )
            """
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_rejection_created_at ON download_rejection_log(created_at)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_rejection_category ON download_rejection_log(category)"
        )


def log_rejection(
    *,
    track_id: int,
    artist: str,
    title: str,
    status: str,
    reason: str,
    attempts: int,
    search_query: str | None = None,
    source_url: str | None = None,
) -> None:
    """Schrijf een afwijzing naar SQLite en JSONL zonder de downloader te blokkeren."""
    try:
        _ensure_table()
        category = classify_rejection(reason)
        created_at = now_iso()
        payload: dict[str, Any] = {
            "track_id": int(track_id),
            "artist": str(artist or ""),
            "title": str(title or ""),
            "status": str(status or "failed"),
            "category": category,
            "reason": str(reason or "")[-3000:],
            "attempts": int(attempts or 0),
            "search_query": str(search_query or "") or None,
            "source_url": str(source_url or "") or None,
            "created_at": created_at,
        }
        with connect() as con:
            con.execute(
                """
                INSERT INTO download_rejection_log(
                  track_id,artist,title,status,category,reason,attempts,
                  search_query,source_url,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    payload["track_id"], payload["artist"], payload["title"],
                    payload["status"], payload["category"], payload["reason"],
                    payload["attempts"], payload["search_query"],
                    payload["source_url"], payload["created_at"],
                ),
            )
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        # Logging mag een download nooit laten mislukken.
        return
