from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from .db import connect, now_iso
from .ops_engine import execute_repair, init_ops, list_incidents, scan_failed_tracks

LEARNING_SCHEMA = """
CREATE TABLE IF NOT EXISTS repair_policies (
  action_name TEXT PRIMARY KEY,
  risk_level TEXT NOT NULL DEFAULT 'low',
  automatic_allowed INTEGER NOT NULL DEFAULT 0,
  minimum_successes INTEGER NOT NULL DEFAULT 3,
  minimum_success_rate REAL NOT NULL DEFAULT 0.90,
  cooldown_minutes INTEGER NOT NULL DEFAULT 60,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  incident_id INTEGER,
  action_name TEXT NOT NULL,
  decision TEXT NOT NULL,
  reason TEXT NOT NULL,
  statistics_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
"""

DEFAULT_POLICIES = {
    "pause_downloads": ("low", 1, 1, 0.80, 30),
    "clear_source_and_retry": ("low", 0, 3, 0.90, 60),
    "retry_track": ("low", 0, 3, 0.90, 60),
    "retry_later": ("low", 0, 3, 0.90, 60),
    "manual_update_required": ("high", 0, 999, 1.00, 1440),
    "manual_review": ("high", 0, 999, 1.00, 1440),
}


def init_learning() -> None:
    init_ops()
    with connect() as con:
        con.executescript(LEARNING_SCHEMA)
        for action, values in DEFAULT_POLICIES.items():
            con.execute(
                """
                INSERT OR IGNORE INTO repair_policies(
                  action_name,risk_level,automatic_allowed,minimum_successes,
                  minimum_success_rate,cooldown_minutes,updated_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (action, *values, now_iso()),
            )


def action_statistics(action_name: str) -> dict[str, Any]:
    init_learning()
    with connect() as con:
        row = con.execute(
            """
            SELECT COUNT(*) total,
                   SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) successes,
                   SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) failures
            FROM repair_attempts WHERE action_name=?
            """,
            (action_name,),
        ).fetchone()
    total = int(row["total"] or 0)
    successes = int(row["successes"] or 0)
    failures = int(row["failures"] or 0)
    return {
        "total": total,
        "successes": successes,
        "failures": failures,
        "success_rate": round(successes / total, 4) if total else 0.0,
    }


def policy_snapshot() -> list[dict[str, Any]]:
    init_learning()
    with connect() as con:
        rows = con.execute("SELECT * FROM repair_policies ORDER BY risk_level,action_name").fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["statistics"] = action_statistics(item["action_name"])
        result.append(item)
    return result


def promote_proven_actions() -> list[str]:
    promoted = []
    for policy in policy_snapshot():
        stats = policy["statistics"]
        if policy["risk_level"] != "low" or policy["automatic_allowed"]:
            continue
        if stats["successes"] >= policy["minimum_successes"] and stats["success_rate"] >= policy["minimum_success_rate"]:
            with connect() as con:
                con.execute(
                    "UPDATE repair_policies SET automatic_allowed=1,updated_at=? WHERE action_name=?",
                    (now_iso(), policy["action_name"]),
                )
            promoted.append(policy["action_name"])
    return promoted


def _cooldown_clear(action_name: str, minutes: int) -> bool:
    cutoff = (datetime.now().astimezone() - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    with connect() as con:
        row = con.execute(
            "SELECT 1 FROM learning_events WHERE action_name=? AND decision='executed' AND created_at>=? LIMIT 1",
            (action_name, cutoff),
        ).fetchone()
    return row is None


def auto_heal_cycle() -> dict[str, Any]:
    init_learning()
    scan_failed_tracks()
    promoted = promote_proven_actions()
    policies = {item["action_name"]: item for item in policy_snapshot()}
    executed = []
    skipped = []

    for incident in list_incidents(limit=50):
        if incident["status"] != "open":
            continue
        action = incident.get("recommended_action") or "manual_review"
        policy = policies.get(action)
        stats = action_statistics(action)
        reason = ""
        if not policy or not policy["automatic_allowed"]:
            reason = "Herstelactie is nog niet automatisch vertrouwd."
        elif policy["risk_level"] != "low":
            reason = "Risiconiveau vereist menselijke goedkeuring."
        elif not _cooldown_clear(action, int(policy["cooldown_minutes"])):
            reason = "Cooldown is nog actief."
        else:
            result = execute_repair(int(incident["id"]), action)
            executed.append({"incident_id": incident["id"], "action": action, "result": result})
            with connect() as con:
                con.execute(
                    "INSERT INTO learning_events(incident_id,action_name,decision,reason,statistics_json,created_at) VALUES(?,?,?,?,?,?)",
                    (incident["id"], action, "executed", "Bewezen laag-risico beleid", json.dumps(stats), now_iso()),
                )
            continue
        skipped.append({"incident_id": incident["id"], "action": action, "reason": reason})
        with connect() as con:
            con.execute(
                "INSERT INTO learning_events(incident_id,action_name,decision,reason,statistics_json,created_at) VALUES(?,?,?,?,?,?)",
                (incident["id"], action, "skipped", reason, json.dumps(stats), now_iso()),
            )

    return {"promoted": promoted, "executed": executed, "skipped": skipped}
