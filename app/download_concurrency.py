from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3
from typing import Any

from .db import connect

DEFAULT_DOWNLOAD_WORKERS = 2
MAX_DOWNLOAD_WORKERS = 6
AI_DECISION_TTL_MINUTES = 35

BASE_SETTING = "download_workers"
AI_SETTING = "ai_download_workers"
AI_UNTIL_SETTING = "ai_download_workers_until"
AI_REASON_SETTING = "ai_download_workers_reason"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _bounded_workers(value: object, default: int = DEFAULT_DOWNLOAD_WORKERS) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    return max(DEFAULT_DOWNLOAD_WORKERS, min(MAX_DOWNLOAD_WORKERS, parsed))


def worker_state() -> dict[str, Any]:
    """Return the fixed two-worker baseline and a currently valid AI target.

    ``download_workers`` remains readable for legacy UI/config compatibility, but
    the new Multi Source coordinator deliberately starts at exactly two workers.
    Only a fresh bounded Ollama decision may scale global jobs above two, and that
    decision expires automatically back to the fixed baseline.
    """
    rows: dict[str, str] = {}
    try:
        with connect() as con:
            rows = {
                str(row["key"]): str(row["value"])
                for row in con.execute(
                    "SELECT key,value FROM settings WHERE key IN (?,?,?,?)",
                    (BASE_SETTING, AI_SETTING, AI_UNTIL_SETTING, AI_REASON_SETTING),
                ).fetchall()
            }
    except sqlite3.Error:
        rows = {}

    configured_base = _bounded_workers(rows.get(BASE_SETTING), DEFAULT_DOWNLOAD_WORKERS)
    base = DEFAULT_DOWNLOAD_WORKERS
    ai_target = _bounded_workers(rows.get(AI_SETTING), base) if rows.get(AI_SETTING) else None
    ai_until = _parse_time(rows.get(AI_UNTIL_SETTING))
    ai_active = bool(ai_target is not None and ai_until is not None and ai_until > _utcnow())
    effective = int(ai_target) if ai_active and ai_target is not None else base
    effective = _bounded_workers(effective, base)

    return {
        "base": base,
        "configured_legacy_base": configured_base,
        "effective": effective,
        "maximum": MAX_DOWNLOAD_WORKERS,
        "ai_target": ai_target,
        "ai_active": ai_active,
        "ai_until": ai_until.isoformat() if ai_until else None,
        "ai_reason": rows.get(AI_REASON_SETTING) or None,
    }


def current_download_workers() -> int:
    return int(worker_state()["effective"])


def set_ai_download_workers(
    workers: int,
    reason: str,
    *,
    ttl_minutes: int = AI_DECISION_TTL_MINUTES,
) -> dict[str, Any]:
    target = _bounded_workers(workers)
    until = _utcnow() + timedelta(minutes=max(5, min(60, int(ttl_minutes))))
    values = {
        AI_SETTING: str(target),
        AI_UNTIL_SETTING: until.isoformat(),
        AI_REASON_SETTING: str(reason or "Qwen download-workeradvies")[:1000],
    }
    with connect() as con:
        for key, value in values.items():
            con.execute(
                """
                INSERT INTO settings(key,value) VALUES(?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )
    return worker_state()


def evidence_worker_ceiling(snapshot: dict[str, Any]) -> int:
    """Hard deterministic ceiling above Qwen's requested worker count.

    Scaling is earned by real completed downloads in the last 24 hours. This
    deliberately uses successful end-to-end downloads rather than search hits,
    so resolver/provider noise can never convince the model to jump directly to
    six workers. A sizeable queue is also required before extra workers help.
    """
    jobs = snapshot.get("jobs") or {}
    backlog = int(jobs.get("queued") or 0) + int(jobs.get("waiting_retry") or 0)
    successes = int(snapshot.get("downloads_24h") or 0)

    if backlog < 4 or successes < 4:
        return 2
    if successes < 12:
        return 3
    if successes < 30:
        return 4
    if successes < 60:
        return 5
    return 6
