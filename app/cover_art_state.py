from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .config import DATA_DIR
from .db import connect

STATE_PATH = DATA_DIR / "cover_state.json"


def _read_state_file() -> dict[str, Any]:
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def write_cover_state(**values: Any) -> None:
    payload = _read_state_file()
    payload.update(values)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def read_cover_state() -> dict[str, Any]:
    return _read_state_file()


def cover_dashboard_state() -> dict[str, Any]:
    """Return catch-up progress; hide it once the continuous watcher is caught up."""
    state = _read_state_file()
    with connect() as con:
        counts = con.execute(
            """
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN cover_url IS NOT NULL THEN 1 ELSE 0 END) AS found,
              SUM(CASE WHEN cover_checked_at IS NOT NULL THEN 1 ELSE 0 END) AS checked,
              SUM(
                CASE
                  WHEN cover_url IS NULL
                   AND (cover_checked_at IS NULL OR cover_checked_at < datetime('now','-14 days'))
                  THEN 1 ELSE 0
                END
              ) AS queue_remaining
            FROM tracks
            """
        ).fetchone()

    total = int(counts["total"] or 0) if counts else 0
    found = int(counts["found"] or 0) if counts else 0
    checked = int(counts["checked"] or 0) if counts else 0
    remaining = int(counts["queue_remaining"] or 0) if counts else 0
    checked = max(found, checked)
    percent = round(checked / total * 100, 1) if total else 100.0
    phase = str(state.get("phase") or "unknown")
    actively_catching_up = phase in {
        "starting",
        "processing",
        "waiting_for_source",
        "backoff",
        "error",
    }

    return {
        "visible": bool(remaining > 0 or actively_catching_up),
        "running": bool(state.get("running")),
        "phase": phase,
        "found": found,
        "checked": checked,
        "total": total,
        "remaining": remaining,
        "percent": percent,
        "current_artist": state.get("current_artist"),
        "current_title": state.get("current_title"),
        "found_this_run": int(state.get("found_total") or 0),
        "processed_this_run": int(state.get("processed_total") or 0),
        "per_minute": state.get("per_minute"),
        "last_cover": state.get("last_cover"),
        "last_cover_at": state.get("last_cover_at"),
        "last_error": state.get("last_error"),
        "updated_at": state.get("updated_at"),
    }
