from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DATA_DIR, DB_PATH
from .download_db import provider_dashboard
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


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    if not _table_exists(conn, table):
        return False
    try:
        return any(str(row[1]) == column for row in conn.execute(f"PRAGMA table_info({table})"))
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
        "path": str(DB_PATH),
        "exists": DB_PATH.exists(),
        "tracks": 0,
        "covers": 0,
        "duplicates": 0,
        "empty_artist": 0,
        "empty_title": 0,
        "health": "missing",
        "fragmentation_percent": 0.0,
        "vacuum_advice": False,
        "error": None,
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
                    data["duplicates"] = _as_int(
                        conn.execute(
                            f"SELECT COALESCE(SUM(c-1),0) FROM (SELECT COUNT(*) c FROM {track_table} GROUP BY lower(trim(artist)),lower(trim(title)) HAVING c>1)"
                        ).fetchone()[0]
                    )
                except sqlite3.Error:
                    pass

            if track_table == "tracks" and _column_exists(conn, "tracks", "cover_url"):
                data["covers"] = _count(conn, "tracks", "cover_url IS NOT NULL AND trim(cover_url)<>''")
            else:
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

    try:
        provider_data = provider_dashboard()
    except Exception as exc:
        provider_data = {
            "ok": False,
            "providers": [],
            "jobs": {},
            "youtube_dependency_percent": state.get("youtube_dependency_percent", 0),
            "target_youtube_dependency_percent": 10.0,
            "error": str(exc)[-500:],
        }
    jobs = provider_data.get("jobs") or {}
    queue_from_jobs = sum(_as_int(jobs.get(key)) for key in ("queued", "searching"))
    running_from_jobs = sum(_as_int(jobs.get(key)) for key in ("searching", "downloading", "validating", "processing"))
    return {
        "engine": "multi-source",
        "manager_service": "top40-download-manager.service",
        "workers": _as_int(state.get("workers", os.getenv("TOP40_DOWNLOAD_WORKERS", "4")), 4),
        "queue": _as_int(state.get("queue"), queue_from_jobs or queue_count),
        "running": _as_int(state.get("running"), running_from_jobs),
        "retry": _as_int(state.get("retry"), jobs.get("waiting_retry", 0)),
        "youtube_errors": _as_int(state.get("youtube_errors")),
        "average_speed": state.get("average_speed", 0),
        "eta_seconds": state.get("eta_seconds"),
        "downloads_24h": provider_data.get("downloads_24h", 0),
        "without_youtube_24h": provider_data.get("without_youtube_24h", 0),
        "youtube_family_24h": provider_data.get("youtube_family_24h", 0),
        "youtube_dependency_percent": provider_data.get("youtube_dependency_percent", 0),
        "youtube_dependency_target_percent": provider_data.get("target_youtube_dependency_percent", 10.0),
        "youtube_dependency_target_met": provider_data.get("target_met"),
        "providers": provider_data.get("providers", []),
        "provider_jobs": jobs,
        "provider_error": provider_data.get("error"),
    }


def _cover_counts() -> tuple[int, int, int]:
    if not DB_PATH.exists():
        return 0, 0, 0
    try:
        with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5) as conn:
            total = _as_int(conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0])
            without_cover = _as_int(
                conn.execute("SELECT COUNT(*) FROM tracks WHERE cover_url IS NULL OR trim(cover_url)='' ").fetchone()[0]
            )
            eligible = _as_int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM tracks
                    WHERE (cover_url IS NULL OR trim(cover_url)='')
                      AND (cover_checked_at IS NULL OR cover_checked_at < datetime('now','-14 days'))
                    """
                ).fetchone()[0]
            )
            return total, without_cover, eligible
    except sqlite3.Error:
        db = database_dashboard()
        total = _as_int(db.get("tracks"))
        covers = _as_int(db.get("covers"))
        return total, max(0, total - covers), 0


def cover_dashboard() -> dict[str, Any]:
    payload = _load_json(DATA_DIR / "cover_state.json")
    if not isinstance(payload, dict):
        payload = {}
    total, without_cover, eligible = _cover_counts()
    return {
        "total": total,
        "with_cover": max(0, total - without_cover),
        "without_cover": without_cover,
        "eligible_queue": eligible,
        "processed_without_match": max(0, without_cover - eligible),
        "running": bool(payload.get("running", False)),
        "phase": payload.get("phase", "unknown"),
        "current_artist": payload.get("current_artist"),
        "current_title": payload.get("current_title"),
        "processed_total": _as_int(payload.get("processed_total")),
        "found_total": _as_int(payload.get("found_total")),
        "missing_total": _as_int(payload.get("missing_total")),
        "transient_total": _as_int(payload.get("transient_total")),
        "queue_remaining": _as_int(payload.get("queue_remaining"), eligible),
        "per_minute": payload.get("per_minute", 0),
        "last_cover": payload.get("last_cover"),
        "last_cover_at": payload.get("last_cover_at"),
        "last_error": payload.get("last_error"),
        "updated_at": payload.get("updated_at"),
        "started_at": payload.get("started_at"),
        "finished_at": payload.get("finished_at"),
    }


def health_score() -> dict[str, Any]:
    services = service_monitor()
    db = database_dashboard()
    downloads = download_dashboard()
    covers = cover_dashboard()
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
        reasons.append("veel YouTube-family fouten")
    total_24h = _as_int(downloads.get("downloads_24h"))
    dependency = float(downloads.get("youtube_dependency_percent") or 0)
    if total_24h >= 10 and dependency >= 10:
        penalties += 5
        reasons.append(f"YouTube-afhankelijkheid {dependency:.1f}% ligt boven doel <10%")
    if _as_int(covers.get("eligible_queue")) > 0 and not covers.get("running"):
        penalties += 5
        reasons.append(f"{covers['eligible_queue']} covers wachten nog op verwerking")

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
        "cover_queue": _as_int(covers.get("eligible_queue")),
        "youtube_dependency_percent": dependency,
        "youtube_dependency_target_percent": 10.0,
        "disk_free_percent": round(free_pct, 1),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
