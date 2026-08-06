from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DATA_DIR, DB_PATH

SERVICE_GROUPS = {
    "web": ["top40-archiver-web.service"],
    "download": ["top40-archiver-download.service"],
    "cover": ["top40-archiver-cover-art.service", "top40-archiver-id3-cover.service"],
    "ai": ["top40-archiver-ai.service"],
    "ollama": ["ollama.service"],
    "database": ["top40-archiver-check.service", "top40-archiver-history.service"],
    "updater": ["top40-archiver-auto-update.service"],
    "system": ["top40-log-reader.service", "top40-archiver-incident-scan.service"],
}


def _show(unit: str) -> dict[str, str]:
    props = ["ActiveState", "SubState", "Result", "MainPID", "NRestarts", "ActiveEnterTimestamp", "MemoryCurrent", "CPUUsageNSec", "TasksCurrent"]
    proc = subprocess.run(["systemctl", "show", unit, "--property=" + ",".join(props)], capture_output=True, text=True, timeout=5, check=False)
    values = {k: v for line in proc.stdout.splitlines() if "=" in line for k, v in [line.split("=", 1)]}
    return values


def service_monitor() -> list[dict[str, Any]]:
    result = []
    for group, units in SERVICE_GROUPS.items():
        for unit in units:
            s = _show(unit)
            result.append({
                "group": group, "unit": unit, "status": s.get("ActiveState", "unknown"),
                "substatus": s.get("SubState", "unknown"), "result": s.get("Result", "unknown"),
                "pid": int(s.get("MainPID") or 0), "restarts": int(s.get("NRestarts") or 0),
                "last_restart": s.get("ActiveEnterTimestamp") or None,
                "ram_mb": round(int(s.get("MemoryCurrent") or 0) / 1048576, 1),
                "cpu_seconds": round(int(s.get("CPUUsageNSec") or 0) / 1_000_000_000, 1),
                "threads": int(s.get("TasksCurrent") or 0),
            })
    return result


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _count(conn: sqlite3.Connection, table: str, where: str = "1=1") -> int:
    if not _table_exists(conn, table):
        return 0
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0])
    except sqlite3.Error:
        return 0


def database_dashboard() -> dict[str, Any]:
    data: dict[str, Any] = {"path": str(DB_PATH), "exists": DB_PATH.exists(), "tracks": 0, "covers": 0, "duplicates": 0, "empty_artist": 0, "empty_title": 0, "health": "missing", "fragmentation_percent": 0, "vacuum_advice": False}
    if not DB_PATH.exists():
        return data
    with sqlite3.connect(DB_PATH, timeout=5) as conn:
        data["health"] = conn.execute("PRAGMA quick_check").fetchone()[0]
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        track_table = "tracks" if "tracks" in tables else "chart_entries" if "chart_entries" in tables else None
        if track_table:
            data["tracks"] = _count(conn, track_table)
            data["empty_artist"] = _count(conn, track_table, "artist IS NULL OR trim(artist)='' ")
            data["empty_title"] = _count(conn, track_table, "title IS NULL OR trim(title)='' ")
            try:
                data["duplicates"] = int(conn.execute(f"SELECT COALESCE(SUM(c-1),0) FROM (SELECT COUNT(*) c FROM {track_table} GROUP BY lower(trim(artist)),lower(trim(title)) HAVING c>1)").fetchone()[0])
            except sqlite3.Error:
                pass
        data["covers"] = _count(conn, "covers") or _count(conn, "cover_art")
        pages = int(conn.execute("PRAGMA page_count").fetchone()[0])
        free = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
        data["fragmentation_percent"] = round((free / pages * 100) if pages else 0, 1)
        data["vacuum_advice"] = data["fragmentation_percent"] >= 15
    return data


def download_dashboard() -> dict[str, Any]:
    queue_file = DATA_DIR / "download_queue.json"
    state_file = DATA_DIR / "download_state.json"
    import json
    def load(path: Path) -> dict:
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    state = load(state_file)
    queue = load(queue_file)
    return {
        "workers": int(state.get("workers", os.getenv("TOP40_DOWNLOAD_WORKERS", "1"))),
        "queue": int(state.get("queue", len(queue) if isinstance(queue, list) else queue.get("count", 0))),
        "running": int(state.get("running", 0)), "retry": int(state.get("retry", 0)),
        "youtube_errors": int(state.get("youtube_errors", 0)),
        "average_speed": state.get("average_speed", 0), "eta_seconds": state.get("eta_seconds"),
    }


def cover_dashboard() -> dict[str, Any]:
    db = database_dashboard()
    state = DATA_DIR / "cover_state.json"
    import json
    try: payload = json.loads(state.read_text())
    except Exception: payload = {}
    total = int(db.get("tracks", 0)); covers = int(db.get("covers", 0))
    return {"total": total, "without_cover": max(0, total-covers), "per_minute": payload.get("per_minute", 0), "last_cover": payload.get("last_cover"), "retry": payload.get("retry", 0), "api_errors": payload.get("api_errors", 0)}


def health_score() -> dict[str, Any]:
    services = service_monitor(); db = database_dashboard(); dl = download_dashboard()
    disk = shutil.disk_usage(DATA_DIR if DATA_DIR.exists() else "/")
    penalties = 0; reasons = []
    failed = sum(1 for s in services if s["status"] == "failed")
    inactive = sum(1 for s in services if s["status"] not in {"active", "activating"} and s["group"] in {"web", "ai", "download"})
    if failed: penalties += min(35, failed*12); reasons.append(f"{failed} services mislukt")
    if inactive: penalties += min(20, inactive*7); reasons.append(f"{inactive} kernservices niet actief")
    if db["health"] not in {"ok", "missing"}: penalties += 25; reasons.append("databasecontrole niet OK")
    if dl["youtube_errors"] > 10: penalties += 10; reasons.append("veel YouTube-fouten")
    free_pct = disk.free / disk.total * 100
    if free_pct < 10: penalties += 20; reasons.append("weinig schijfruimte")
    score = max(0, 100-penalties)
    return {"score": score, "label": "Gezond" if score >= 90 else "Aandacht" if score >= 70 else "Kritiek", "reasons": reasons, "disk_free_percent": round(free_pct, 1), "generated_at": datetime.now(timezone.utc).isoformat()}
