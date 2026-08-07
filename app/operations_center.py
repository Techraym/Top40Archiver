from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DATA_DIR, DB_PATH
from .service_watchdog import service_monitor


def _as_int(value: object, default: int = 0) -> int:
    try:
        text = str(value or "").strip()
        if not text or text.casefold() in {"[not set]", "n/a", "none", "unknown", "infinity"}:
            return default
        return int(text)
    except (TypeError, ValueError, OverflowError):
        return default


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone() is not None
    except sqlite3.Error:
        return False


def _count(conn: sqlite3.Connection, table: str, where: str = "1=1") -> int:
    if not _table_exists(conn, table):
        return 0
    try:
        return _as_int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0])
    except (sqlite3.Error, TypeError, IndexError):
        return 0


def database_dashboard() -> dict[str, Any]:
    data: dict[str, Any] = {
        "path": str(DB_PATH), "exists": DB_PATH.exists(), "tracks": 0,
        "covers": 0, "duplicates": 0, "empty_artist": 0, "empty_title": 0,
        "health": "missing", "fragmentation_percent": 0.0,
        "vacuum_advice": False, "error": None,
    }
    if not DB_PATH.exists():
        return data
    try:
        with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5) as conn:
            check = conn.execute("PRAGMA quick_check").fetchone()
            data["health"] = str(check[0] if check else "unknown")
            tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            track_table = "tracks" if "tracks" in tables else "chart_entries" if "chart_entries" in tables else None
            if track_table:
                data["tracks"] = _count(conn, track_table)
                data["empty_artist"] = _count(conn, track_table, "artist IS NULL OR trim(artist)='' ")
                data["empty_title"] = _count(conn, track_table, "title IS NULL OR trim(title)='' ")
                try:
                    data["duplicates"] = _as_int(conn.execute(
                        f"SELECT COALESCE(SUM(c-1),0) FROM (SELECT COUNT(*) c FROM {track_table} GROUP BY lower(trim(artist)),lower(trim(title)) HAVING c>1)"
                    ).fetchone()[0])
                except sqlite3.Error:
                    pass
            data["covers"] = _count(conn, "covers") or _count(conn, "cover_art")
            pages = _as_int(conn.execute("PRAGMA page_count").fetchone()[0])
            free = _as_int(conn.execute("PRAGMA freelist_count").fetchone()[0])
            data["fragmentation_percent"] = round((free / pages * 100) if pages else 0, 1)
            data["vacuum_advice"] = data["fragmentation_percent"] >= 15
    except (sqlite3.Error, OSError) as exc:
        data["health"] = "error"
        data["error"] = str(exc)[-500:]
    return data


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def download_dashboard() -> dict[str, Any]:
    state = _load_json(DATA_DIR / "download_state.json")
    queue = _load_json(DATA_DIR / "download_queue.json")
    if not isinstance(state, dict):
        state = {}
    if isinstance(queue, list):
        queue_count = len(queue)
    elif isinstance(queue, dict):
        queue_count = _as_int(queue.get("count"))
    else:
        queue_count = 0
    return {
        "workers": _as_int(state.get("workers", os.getenv("TOP40_DOWNLOAD_WORKERS", "1")), 1),
        "queue": _as_int(state.get("queue"), queue_count),
        "running": _as_int(state.get("running")),
        "retry": _as_int(state.get("retry")),
        "youtube_errors": _as_int(state.get("youtube_errors")),
        "average_speed": state.get("average_speed", 0),
        "eta_seconds": state.get("eta_seconds"),
    }


def cover_dashboard() -> dict[str, Any]:
    db = database_dashboard()
    payload = _load_json(DATA_DIR / "cover_state.json")
    if not isinstance(payload, dict):
        payload = {}
    total = _as_int(db.get("tracks"))
    covers = _as_int(db.get("covers"))
    return {
        "total": total,
        "without_cover": max(0, total - covers),
        "per_minute": payload.get("per_minute", 0),
        "last_cover": payload.get("last_cover"),
        "retry": _as_int(payload.get("retry")),
        "api_errors": _as_int(payload.get("api_errors")),
    }


def health_score() -> dict[str, Any]:
    services = service_monitor()
    db = database_dashboard()
    downloads = download_dashboard()
    reasons: list[str] = []
    penalties = 0

    critical = [item for item in services if item.get("health") == "critical"]
    attention = [item for item in services if item.get("health") == "attention"]
    if critical:
        penalties += min(40, len(critical) * 10)
        reasons.append(f"{len(critical)} vereiste services/timers vragen herstel")
    if attention:
        penalties += min(12, len(attention) * 3)
        reasons.append(f"{len(attention)} services zijn aan het starten of vragen aandacht")
    if db.get("health") not in {"ok", "missing"}:
        penalties += 25
        reasons.append("databasecontrole niet OK")
    if _as_int(downloads.get("youtube_errors")) > 10:
        penalties += 10
        reasons.append("veel YouTube-fouten")

    try:
        disk = shutil.disk_usage(DATA_DIR if DATA_DIR.exists() else "/")
        free_pct = (disk.free / disk.total * 100) if disk.total else 0.0
        if free_pct < 10:
            penalties += 20
            reasons.append("weinig schijfruimte")
    except OSError as exc:
        free_pct = 0.0
        penalties += 5
        reasons.append(f"schijfmeting niet beschikbaar: {exc}")

    score = max(0, 100 - penalties)
    return {
        "score": score,
        "label": "Gezond" if score >= 90 else "Aandacht" if score >= 70 else "Kritiek",
        "reasons": reasons,
        "service_critical": len(critical),
        "service_attention": len(attention),
        "disk_free_percent": round(free_pct, 1),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
