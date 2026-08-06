from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from typing import Any

from .db import connect

ALLOWED_ACTIONS = {
    "set_workers_one",
    "pause_downloads",
    "resume_downloads",
    "run_test_download",
    "clear_circuit_breaker",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_recovery_tables() -> None:
    with connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS recovery_actions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              action TEXT NOT NULL,
              requested_by TEXT NOT NULL,
              status TEXT NOT NULL,
              details TEXT,
              started_at TEXT NOT NULL,
              finished_at TEXT
            )
            """
        )


def _start_log(action: str, requested_by: str) -> int:
    init_recovery_tables()
    with connect() as con:
        cur = con.execute(
            "INSERT INTO recovery_actions(action,requested_by,status,details,started_at) VALUES(?,?,?,?,?)",
            (action, requested_by, "running", "{}", _now()),
        )
        return int(cur.lastrowid)


def _finish_log(action_id: int, status: str, details: dict[str, Any]) -> None:
    with connect() as con:
        con.execute(
            "UPDATE recovery_actions SET status=?,details=?,finished_at=? WHERE id=?",
            (status, json.dumps(details, ensure_ascii=False), _now(), action_id),
        )


def _systemctl(*args: str) -> dict[str, Any]:
    proc = subprocess.run(
        ["systemctl", *args], capture_output=True, text=True, timeout=30, check=False
    )
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }


def execute_action(action: str, requested_by: str = "operator") -> dict[str, Any]:
    if action not in ALLOWED_ACTIONS:
        raise ValueError("Actie niet toegestaan")

    action_id = _start_log(action, requested_by)
    try:
        if action == "set_workers_one":
            with connect() as con:
                con.execute(
                    "INSERT INTO settings(key,value) VALUES('download_workers','1') "
                    "ON CONFLICT(key) DO UPDATE SET value='1'"
                )
            result = {"download_workers": 1}
        elif action == "pause_downloads":
            result = _systemctl("stop", "top40-archiver-download.timer", "top40-archiver-download.service")
        elif action == "resume_downloads":
            result = _systemctl("start", "top40-archiver-download.timer")
        elif action == "run_test_download":
            result = _systemctl("start", "top40-archiver-download.service")
        else:
            with connect() as con:
                con.execute(
                    "INSERT INTO circuit_breaker_state(key,value,updated_at) VALUES('youtube','inactive',?) "
                    "ON CONFLICT(key) DO UPDATE SET value='inactive',updated_at=excluded.updated_at",
                    (_now(),),
                )
            result = {"circuit_breaker": "inactive"}

        status = "success" if int(result.get("returncode", 0)) == 0 else "failed"
        _finish_log(action_id, status, result)
        return {"id": action_id, "action": action, "status": status, "result": result}
    except Exception as exc:
        details = {"error": str(exc)}
        _finish_log(action_id, "failed", details)
        return {"id": action_id, "action": action, "status": "failed", "result": details}


def list_actions(limit: int = 100) -> list[dict[str, Any]]:
    init_recovery_tables()
    with connect() as con:
        rows = con.execute(
            "SELECT id,action,requested_by,status,details,started_at,finished_at "
            "FROM recovery_actions ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            item["details"] = json.loads(item.get("details") or "{}")
        except json.JSONDecodeError:
            pass
        result.append(item)
    return result
