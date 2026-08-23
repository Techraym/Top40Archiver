from __future__ import annotations

from datetime import date
import os
import re
from pathlib import Path
import shutil
import threading
import time

HISTORY_STATUS_LABELS = {
    "idle": "Nog niet gestart",
    "running": "Actief",
    "paused": "Gepauzeerd",
    "completed": "Actueel",
    "error": "Fout",
}

STORAGE_SCAN_TTL_SECONDS = 30.0
_storage_scan_cache: dict[str, tuple[float, int, int]] = {}
_storage_scan_lock = threading.Lock()


def as_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def percent(value: int, total: int) -> float:
    return round((value / total) * 100, 1) if total else 0.0


def iso_monday(year: int, week: int) -> date:
    try:
        return date.fromisocalendar(year, week, 1)
    except ValueError:
        return date.fromisocalendar(year, 1, 1)


def _format_bytes(value: int) -> str:
    size = max(0, int(value))
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(size)
    for unit in units:
        if amount < 1024.0 or unit == units[-1]:
            decimals = 0 if unit == "B" else 1
            return f"{amount:.{decimals}f} {unit}"
        amount /= 1024.0
    return "0 B"


def _scan_mp3_tree(root: Path) -> tuple[int, int]:
    """Return actual MP3 count and total MP3 bytes without following symlinks."""
    if not root.exists() or not root.is_dir():
        return 0, 0

    count = 0
    total_bytes = 0
    stack = [root]

    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif (
                            entry.is_file(follow_symlinks=False)
                            and entry.name.casefold().endswith(".mp3")
                        ):
                            count += 1
                            total_bytes += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue

    return count, total_bytes


def _cached_mp3_stats(root: Path) -> tuple[int, int]:
    """Cache the recursive filesystem scan so the one-second SSE loop stays light."""
    key = str(root)
    now = time.monotonic()

    with _storage_scan_lock:
        cached = _storage_scan_cache.get(key)
        if cached and now - cached[0] < STORAGE_SCAN_TTL_SECONDS:
            return cached[1], cached[2]

        count, total_bytes = _scan_mp3_tree(root)
        _storage_scan_cache[key] = (now, count, total_bytes)
        return count, total_bytes


def storage_status(download_dir: str) -> dict[str, object]:
    requested = Path(download_dir).expanduser()
    probe = requested
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent

    mp3_count, music_bytes = _cached_mp3_stats(requested)
    result: dict[str, object] = {
        "path": str(requested),
        "exists": requested.exists(),
        "writable": requested.exists() and os.access(requested, os.W_OK),
        "free_gb": 0.0,
        "used_gb": 0.0,
        "total_gb": 0.0,
        "used_percent": 0.0,
        "used_percent_label": "0.000",
        "mp3_count": mp3_count,
        "music_bytes": music_bytes,
        "music_size_label": _format_bytes(music_bytes),
    }
    try:
        usage = shutil.disk_usage(probe)
        used_percent = (usage.used / usage.total) * 100 if usage.total else 0.0
        result.update(
            {
                "free_gb": round(usage.free / (1024**3), 1),
                "used_gb": round(usage.used / (1024**3), 2),
                "total_gb": round(usage.total / (1024**3), 1),
                "used_percent": round(used_percent, 3),
                "used_percent_label": f"{used_percent:.3f}",
            }
        )
    except OSError:
        pass
    return result



def queue_summary(
    status_counts: dict[str, int],
    active_jobs: int,
) -> dict[str, int]:
    total = max(
        0,
        as_int(status_counts.get("pending"))
        + as_int(status_counts.get("downloading")),
    )
    active = max(0, min(total, as_int(active_jobs)))
    return {
        "total": total,
        "waiting": max(0, total - active),
        "active": active,
    }


def download_chart(status_counts: dict[str, int]) -> dict[str, object]:
    total = sum(status_counts.values())
    downloaded = status_counts.get("downloaded", 0)
    pending = status_counts.get("pending", 0)
    downloading = status_counts.get("downloading", 0)
    failed = status_counts.get("failed", 0)

    d1 = percent(downloaded, total)
    d2 = d1 + percent(pending, total)
    d3 = d2 + percent(downloading, total)
    gradient = (
        "#e2e8f0"
        if total == 0
        else (
            "conic-gradient("
            f"#22c55e 0 {d1}%,"
            f"#f59e0b {d1}% {d2}%,"
            f"#3b82f6 {d2}% {d3}%,"
            f"#ef4444 {d3}% 100%"
            ")"
        )
    )
    return {
        "total": total,
        "downloaded_percent": percent(downloaded, total),
        "gradient": gradient,
        "items": [
            {"key": "downloaded", "label": "Gedownload", "count": downloaded},
            {"key": "pending", "label": "In wachtrij", "count": pending},
            {"key": "downloading", "label": "Bezig", "count": downloading},
            {"key": "failed", "label": "Mislukt", "count": failed},
        ],
    }


def _single_history_progress(
    settings: dict[str, str],
    *,
    prefix: str,
    current_setting: str,
    default_start_year: int,
    default_start_week: int,
) -> dict[str, object]:
    start_year_key = f"{prefix}_start_year" if prefix else "history_start_year"
    start_week_key = f"{prefix}_start_week" if prefix else "history_start_week"
    next_year_key = f"{prefix}_next_year" if prefix else "history_next_year"
    next_week_key = f"{prefix}_next_week" if prefix else "history_next_week"
    status_key = f"{prefix}_status" if prefix else "history_status"
    last_key = f"{prefix}_last_edition" if prefix else "history_last_edition"

    start_year = as_int(settings.get(start_year_key), default_start_year)
    start_week = as_int(settings.get(start_week_key), default_start_week)
    next_year = as_int(settings.get(next_year_key), start_year)
    next_week = as_int(settings.get(next_week_key), start_week)
    start = iso_monday(start_year, start_week)

    known_current = str(settings.get(current_setting) or "")
    match = re.fullmatch(r"(\d{4})-W(\d{1,2})", known_current)
    if match:
        current = iso_monday(int(match.group(1)), int(match.group(2)))
    else:
        current_iso = date.today().isocalendar()
        current = date.fromisocalendar(current_iso.year, current_iso.week, 1)

    next_date = iso_monday(next_year, next_week)
    total_weeks = max(1, ((current - start).days // 7) + 1)
    cursor_done = max(0, min(total_weeks, (next_date - start).days // 7))
    status = settings.get(status_key, "idle")
    completed = total_weeks if status == "completed" else cursor_done
    return {
        "start": f"{start_year}-W{start_week:02d}",
        "next": f"{next_year}-W{next_week:02d}",
        "last": settings.get(last_key, ""),
        "status": status,
        "completed": completed,
        "total": total_weeks,
        "remaining": max(0, total_weeks - completed),
        "percent": 100.0 if status == "completed" else percent(completed, total_weeks),
    }


def history_progress(settings: dict[str, str], completed_editions: int = 0) -> dict[str, object]:
    top40 = _single_history_progress(
        settings,
        prefix="",
        current_setting="last_edition",
        default_start_year=1965,
        default_start_week=1,
    )
    tipparade = _single_history_progress(
        settings,
        prefix="tip_history",
        current_setting="last_tipparade_edition",
        default_start_year=1967,
        default_start_week=28,
    )

    total = int(top40["total"]) + int(tipparade["total"])
    completed = int(top40["completed"]) + int(tipparade["completed"])
    top_status = str(top40["status"])
    tip_status = str(tipparade["status"])
    is_current = top_status == "completed" and tip_status == "completed"
    if is_current:
        status = "completed"
    elif "error" in {top_status, tip_status}:
        status = "error"
    elif settings.get("history_enabled") == "1":
        status = "running"
    elif "paused" in {top_status, tip_status}:
        status = "paused"
    else:
        status = "idle"

    schedule = f"{settings.get('weekly_day', 'Fri')} {settings.get('weekly_time', '15:00')}"
    return {
        "completed": completed,
        "total": total,
        "remaining": max(0, total - completed),
        "percent": 100.0 if is_current else percent(completed, total),
        "next_label": schedule if is_current else f"Top 40 {top40['next']} · Tip {tipparade['next']}",
        "status": status,
        "status_label": HISTORY_STATUS_LABELS.get(status, status),
        "is_current": is_current,
        "title": "Archief is actueel" if is_current else "Historisch archief opbouwen",
        "subtitle": (
            "Top 40 en Tipparade zijn volledig bijgewerkt; de weekcontrole neemt het over."
            if is_current
            else "Top 40 vanaf 1965 en Tipparade vanaf 1967 worden naast elkaar opgebouwd."
        ),
        "next_caption": "Volgende weekcontrole" if is_current else "Volgende historische edities",
        "completed_at": settings.get("history_completed_at", "") if is_current else "",
        "top40": top40,
        "tipparade": tipparade,
    }


def bar_rows(rows: list[dict[str, object]], value_key: str) -> list[dict[str, object]]:
    maximum = max((as_int(row.get(value_key)) for row in rows), default=0)
    output = []
    for row in rows:
        item = dict(row)
        value = as_int(item.get(value_key))
        item["bar_percent"] = round((value / maximum) * 100, 1) if maximum else 0
        output.append(item)
    return output
