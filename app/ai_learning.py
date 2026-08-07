from __future__ import annotations

import json
import math
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from . import ai_memory
from .db import connect as app_connect

TARGET_DAYS = 7


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def new_cycle_id() -> str:
    return f"cycle-{_now().strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"


def _loads(value: object, default: Any = None) -> Any:
    try:
        return json.loads(str(value or ""))
    except (json.JSONDecodeError, TypeError, ValueError):
        return {} if default is None else default


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def start_action(
    *,
    cycle_id: str,
    domain: str,
    problem_key: str,
    action: str,
    reason: str,
    subject: str | None = None,
    before: dict | None = None,
    result: dict | None = None,
    reversible: bool = True,
    backup_ref: str | None = None,
) -> int:
    """Registreer iedere door AI geïnitieerde actie, ook als verificatie later volgt."""
    with ai_memory.connect() as conn:
        existing = conn.execute(
            """
            SELECT id FROM action_execution
            WHERE cycle_id=? AND domain=? AND problem_key=? AND action=?
              AND COALESCE(subject,'')=COALESCE(?, '')
            LIMIT 1
            """,
            (cycle_id, domain, problem_key, action, subject),
        ).fetchone()
        if existing:
            return int(existing["id"])
        cursor = conn.execute(
            """
            INSERT INTO action_execution(
              cycle_id,domain,problem_key,action,subject,reason,status,
              before_json,result_json,reversible,backup_ref,started_at
            ) VALUES(?,?,?,?,?,?,'pending',?,?,?,?,?)
            """,
            (
                cycle_id,
                domain,
                problem_key,
                action,
                subject,
                reason,
                _json(before),
                _json(result),
                1 if reversible else 0,
                backup_ref,
                _iso(),
            ),
        )
        action_id = int(cursor.lastrowid)
    ai_memory.remember_event(
        "ai_action_started",
        f"AI start actie {action} voor {problem_key}",
        service=domain,
        metadata={"action_id": action_id, "cycle_id": cycle_id, "subject": subject, "reason": reason},
    )
    return action_id


def _update_learning(conn: sqlite3.Connection, row: sqlite3.Row, success: bool, effect_score: float) -> None:
    key = str(row["problem_key"])
    action = str(row["action"])
    existing = conn.execute(
        "SELECT * FROM action_learning WHERE problem_key=? AND action=?",
        (key, action),
    ).fetchone()
    successes = int(existing["successes"] if existing else 0) + (1 if success else 0)
    failures = int(existing["failures"] if existing else 0) + (0 if success else 1)
    evidence = successes + failures
    previous_total_effect = float(existing["total_effect"] if existing else 0.0)
    total_effect = previous_total_effect + float(effect_score)
    success_rate = successes / evidence if evidence else 0.0
    average_effect = total_effect / evidence if evidence else 0.0
    # Bayesiaanse smoothing voorkomt dat één toevalstreffer meteen alle andere strategieën verdringt.
    confidence = (successes + 1.0) / (evidence + 2.0)
    now = _iso()
    conn.execute(
        """
        INSERT INTO action_learning(
          problem_key,action,successes,failures,evidence_count,total_effect,
          success_rate,average_effect,confidence,last_result,last_success_at,
          last_failure_at,last_used_at,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(problem_key,action) DO UPDATE SET
          successes=excluded.successes,
          failures=excluded.failures,
          evidence_count=excluded.evidence_count,
          total_effect=excluded.total_effect,
          success_rate=excluded.success_rate,
          average_effect=excluded.average_effect,
          confidence=excluded.confidence,
          last_result=excluded.last_result,
          last_success_at=COALESCE(excluded.last_success_at,action_learning.last_success_at),
          last_failure_at=COALESCE(excluded.last_failure_at,action_learning.last_failure_at),
          last_used_at=excluded.last_used_at,
          updated_at=excluded.updated_at
        """,
        (
            key,
            action,
            successes,
            failures,
            evidence,
            total_effect,
            success_rate,
            average_effect,
            confidence,
            "success" if success else "failure",
            now if success else None,
            None if success else now,
            now,
            now,
        ),
    )


def complete_action(
    action_id: int,
    *,
    success: bool,
    after: dict | None = None,
    result: dict | None = None,
    effect_score: float | None = None,
    operator_needed: bool = False,
) -> dict:
    score = float(effect_score if effect_score is not None else (1.0 if success else 0.0))
    score = max(-1.0, min(score, 1.0))
    with ai_memory.connect() as conn:
        row = conn.execute("SELECT * FROM action_execution WHERE id=?", (int(action_id),)).fetchone()
        if not row:
            return {"ok": False, "error": "action_not_found", "id": action_id}
        if str(row["status"]) == "completed":
            return {"ok": True, "id": action_id, "already_completed": True}
        merged_result = _loads(row["result_json"], {})
        if isinstance(result, dict):
            merged_result.update(result)
        conn.execute(
            """
            UPDATE action_execution
            SET status='completed', after_json=?, result_json=?, success=?, effect_score=?,
                operator_needed=?, completed_at=?
            WHERE id=?
            """,
            (
                _json(after),
                _json(merged_result),
                1 if success else 0,
                score,
                1 if operator_needed else 0,
                _iso(),
                int(action_id),
            ),
        )
        _update_learning(conn, row, bool(success), score)
    ai_memory.remember_event(
        "ai_action_completed",
        f"AI actie #{action_id} {'geslaagd' if success else 'mislukt'}",
        metadata={
            "action_id": action_id,
            "success": bool(success),
            "effect_score": score,
            "operator_needed": bool(operator_needed),
        },
    )
    return {"ok": True, "id": action_id, "success": bool(success), "effect_score": score}


def record_action(
    *,
    cycle_id: str,
    domain: str,
    problem_key: str,
    action: str,
    reason: str,
    success: bool,
    subject: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    result: dict | None = None,
    effect_score: float | None = None,
    operator_needed: bool = False,
    reversible: bool = True,
    backup_ref: str | None = None,
) -> int:
    action_id = start_action(
        cycle_id=cycle_id,
        domain=domain,
        problem_key=problem_key,
        action=action,
        reason=reason,
        subject=subject,
        before=before,
        result=result,
        reversible=reversible,
        backup_ref=backup_ref,
    )
    complete_action(
        action_id,
        success=success,
        after=after,
        result=result,
        effect_score=effect_score,
        operator_needed=operator_needed,
    )
    return action_id


def learned_actions(problem_key: str, candidates: Iterable[str] | None = None) -> list[dict[str, Any]]:
    candidate_list = [str(x) for x in candidates] if candidates is not None else []
    with ai_memory.connect() as conn:
        if candidate_list:
            placeholders = ",".join("?" for _ in candidate_list)
            rows = conn.execute(
                f"SELECT * FROM action_learning WHERE problem_key=? AND action IN ({placeholders})",
                [problem_key, *candidate_list],
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM action_learning WHERE problem_key=? ORDER BY evidence_count DESC",
                (problem_key,),
            ).fetchall()
    return [dict(row) for row in rows]


def choose_action(problem_key: str, candidates: list[str], exploration_index: int = 0) -> str:
    """Exploreer onbekende strategieën eerst; gebruik daarna de bewezen beste oplossing."""
    if not candidates:
        raise ValueError("candidates mag niet leeg zijn")
    stats = {str(x["action"]): x for x in learned_actions(problem_key, candidates)}
    untried = [name for name in candidates if int(stats.get(name, {}).get("evidence_count", 0)) < 2]
    if untried:
        return untried[int(exploration_index) % len(untried)]

    def score(name: str) -> tuple[float, int]:
        item = stats.get(name, {})
        confidence = float(item.get("confidence", 0.5))
        effect = float(item.get("average_effect", 0.0))
        success_rate = float(item.get("success_rate", 0.0))
        evidence = int(item.get("evidence_count", 0))
        return (success_rate * 0.55 + confidence * 0.25 + max(0.0, effect) * 0.20, evidence)

    return max(candidates, key=score)


def _service_item(items: list[dict], unit: str) -> dict:
    return next((x for x in items if str(x.get("unit")) == unit), {})


def _operation_problem(action: str) -> str:
    mapping = {
        "run_cover_art": "covers:worker_stopped_with_queue",
        "restart_cover_art": "covers:worker_stalled",
        "restart_ollama": "ollama:http_unreachable",
        "run_database_check": "database:health_not_ok",
        "run_history_sync": "history:sync_required",
    }
    return mapping.get(action, f"operations:{action}")


def ingest_cycle_reports(
    cycle_id: str,
    service_report: dict,
    operations_report: dict,
    recovery_report: dict,
) -> dict[str, int]:
    """Leer van iedere AI-actie uit de drie beheerlagen, met verificatie na uitvoering."""
    ingested = 0
    pending = 0

    services_before = list(service_report.get("services_before") or [])
    services_after = list(service_report.get("services_after") or [])
    for item in service_report.get("actions") or []:
        action = str(item.get("action") or "")
        if not action or item.get("result") == "cooldown":
            continue
        unit = str(item.get("unit") or "unknown")
        before = _service_item(services_before, unit)
        after = _service_item(services_after, unit)
        success = bool(item.get("ok")) and after.get("health") != "critical"
        record_action(
            cycle_id=cycle_id,
            domain="service",
            problem_key=f"service:{unit}",
            action=action,
            reason=f"Vereiste component {unit} week af van het servicebeleid.",
            subject=unit,
            before=before,
            after=after,
            result=item,
            success=success,
            effect_score=1.0 if success else 0.0,
            operator_needed=not success,
        )
        ingested += 1

    op_before = operations_report.get("before") or {}
    op_after = operations_report.get("after") or {}
    for item in operations_report.get("actions") or []:
        action = str(item.get("action") or "")
        if not action:
            continue
        success = bool(item.get("ok"))
        if action in {"run_cover_art", "restart_cover_art"}:
            covers = op_after.get("covers") or {}
            success = success and (bool(covers.get("running")) or int(covers.get("eligible_queue") or 0) == 0)
        elif action == "restart_ollama":
            success = success and bool((op_after.get("ollama") or {}).get("reachable"))
        elif action == "run_database_check":
            success = success and (op_after.get("database") or {}).get("health") in {"ok", "missing"}
        record_action(
            cycle_id=cycle_id,
            domain="operations",
            problem_key=_operation_problem(action),
            action=action,
            reason=str(item.get("reason") or "Automatische operations-policy."),
            before=op_before,
            after=op_after,
            result=item,
            success=success,
            effect_score=1.0 if success else 0.0,
            operator_needed=not success,
        )
        ingested += 1

    verification = recovery_report.get("verification") or {}
    for item in recovery_report.get("actions") or []:
        action = str(item.get("action") or "")
        if not action:
            continue
        restart = item.get("restart") or {"ok": True}
        success = str(item.get("result") or "").casefold() == "gelukt" and bool(restart.get("ok", True))
        record_action(
            cycle_id=cycle_id,
            domain="download",
            problem_key=f"downloads:{action}",
            action=action,
            reason=str((recovery_report.get("decision") or {}).get("reason") or "Automatisch downloadherstel."),
            before={"failure_count": recovery_report.get("failure_count"), "categories": recovery_report.get("categories")},
            after=verification,
            result=item,
            success=success,
            effect_score=1.0 if success else 0.0,
            operator_needed=False,
        )
        ingested += 1

        for repair in item.get("repairs") or []:
            track_id = int(repair.get("id") or 0)
            strategy = str(repair.get("strategy") or "")
            category = str(repair.get("category") or "other")
            if not track_id or not strategy:
                continue
            start_action(
                cycle_id=cycle_id,
                domain="download_track",
                problem_key=f"download:{category}",
                action=strategy,
                reason=f"Track opnieuw ingepland na foutcategorie {category}.",
                subject=f"track:{track_id}",
                before=repair,
                result={"query": repair.get("query"), "recovery_number": repair.get("recovery_number")},
                reversible=True,
            )
            pending += 1

    return {"ingested": ingested, "pending_track_actions": pending}


def resolve_pending_download_actions(max_age_hours: int = 8) -> dict[str, int]:
    with ai_memory.connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM action_execution
            WHERE status='pending' AND domain='download_track'
            ORDER BY id ASC LIMIT 1000
            """
        ).fetchall()
    resolved = 0
    success_count = 0
    failure_count = 0
    now = _now()
    for row in rows:
        subject = str(row["subject"] or "")
        if not subject.startswith("track:"):
            continue
        try:
            track_id = int(subject.split(":", 1)[1])
        except ValueError:
            continue
        with app_connect() as con:
            track = con.execute(
                "SELECT id,download_status,error_message,updated_at FROM tracks WHERE id=?",
                (track_id,),
            ).fetchone()
        if not track:
            complete_action(int(row["id"]), success=False, result={"reason": "track_missing"}, effect_score=0.0)
            resolved += 1
            failure_count += 1
            continue

        status = str(track["download_status"] or "")
        started = datetime.fromisoformat(str(row["started_at"]))
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        age = now - started
        if status == "downloaded":
            complete_action(
                int(row["id"]),
                success=True,
                after={"download_status": status, "updated_at": track["updated_at"]},
                result={"verified": "track_downloaded"},
                effect_score=1.0,
            )
            resolved += 1
            success_count += 1
        elif status in {"failed", "unavailable"}:
            complete_action(
                int(row["id"]),
                success=False,
                after={"download_status": status, "error_message": track["error_message"], "updated_at": track["updated_at"]},
                result={"verified": "track_failed_after_strategy"},
                effect_score=0.0,
                operator_needed=False,
            )
            resolved += 1
            failure_count += 1
        elif age >= timedelta(hours=max_age_hours):
            complete_action(
                int(row["id"]),
                success=False,
                after={"download_status": status, "updated_at": track["updated_at"]},
                result={"verified": "strategy_timed_out"},
                effect_score=0.1,
                operator_needed=False,
            )
            resolved += 1
            failure_count += 1
    return {"resolved": resolved, "success": success_count, "failure": failure_count, "pending_seen": len(rows)}


def finalize_cycle(
    cycle_id: str,
    *,
    started_at: str,
    ok: bool,
    incidents_detected: int,
    actions_executed: int,
    unresolved_after: int,
    operator_needed: int,
    report: dict,
) -> None:
    with ai_memory.connect() as conn:
        successful = int(conn.execute(
            "SELECT COUNT(*) FROM action_execution WHERE cycle_id=? AND status='completed' AND success=1",
            (cycle_id,),
        ).fetchone()[0])
        conn.execute(
            """
            INSERT INTO autonomy_cycle(
              cycle_id,started_at,completed_at,ok,incidents_detected,actions_executed,
              actions_successful,unresolved_after,operator_needed,report_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(cycle_id) DO UPDATE SET
              completed_at=excluded.completed_at,ok=excluded.ok,
              incidents_detected=excluded.incidents_detected,actions_executed=excluded.actions_executed,
              actions_successful=excluded.actions_successful,unresolved_after=excluded.unresolved_after,
              operator_needed=excluded.operator_needed,report_json=excluded.report_json
            """,
            (
                cycle_id,
                started_at,
                _iso(),
                1 if ok else 0,
                int(incidents_detected),
                int(actions_executed),
                successful,
                int(unresolved_after),
                int(operator_needed),
                _json(report),
            ),
        )


def autonomy_report(days: int = TARGET_DAYS) -> dict[str, Any]:
    days = max(1, min(int(days), 30))
    cutoff = _now() - timedelta(days=days)
    with ai_memory.connect() as conn:
        first = conn.execute("SELECT MIN(started_at) FROM action_execution").fetchone()[0]
        actions = conn.execute(
            """
            SELECT COUNT(*) total,
                   SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) completed,
                   SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) successes,
                   SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) failures,
                   SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) pending,
                   SUM(operator_needed) operator_needed
            FROM action_execution WHERE started_at>=?
            """,
            (cutoff.isoformat(),),
        ).fetchone()
        cycles = conn.execute(
            """
            SELECT COUNT(*) total,
                   SUM(CASE WHEN ok=1 THEN 1 ELSE 0 END) ok_cycles,
                   SUM(unresolved_after) unresolved,
                   SUM(operator_needed) operator_needed
            FROM autonomy_cycle WHERE started_at>=?
            """,
            (cutoff.isoformat(),),
        ).fetchone()
        patterns = conn.execute("SELECT COUNT(*) FROM action_learning WHERE evidence_count>=2").fetchone()[0]
        top = conn.execute(
            """
            SELECT * FROM action_learning
            ORDER BY evidence_count DESC,success_rate DESC,average_effect DESC LIMIT 25
            """
        ).fetchall()

    total = int(actions["total"] or 0)
    completed = int(actions["completed"] or 0)
    successes = int(actions["successes"] or 0)
    pending = int(actions["pending"] or 0)
    action_operator = int(actions["operator_needed"] or 0)
    cycle_total = int(cycles["total"] or 0)
    unresolved = int(cycles["unresolved"] or 0)
    cycle_operator = int(cycles["operator_needed"] or 0)
    success_rate = successes / completed if completed else 1.0
    resolution_rate = max(0.0, 1.0 - (unresolved / max(1, cycle_total)))
    evidence_factor = min(1.0, int(patterns or 0) / 10.0)
    penalty = min(30.0, (action_operator + cycle_operator) * 5.0)
    readiness = max(0.0, min(100.0, success_rate * 60.0 + resolution_rate * 30.0 + evidence_factor * 10.0 - penalty))

    days_observed = 0.0
    if first:
        try:
            first_dt = datetime.fromisoformat(str(first))
            if first_dt.tzinfo is None:
                first_dt = first_dt.replace(tzinfo=timezone.utc)
            days_observed = max(0.0, (_now() - first_dt).total_seconds() / 86400.0)
        except ValueError:
            pass

    ready = (
        days_observed >= TARGET_DAYS
        and readiness >= 95.0
        and action_operator == 0
        and cycle_operator == 0
        and unresolved == 0
    )
    return {
        "window_days": days,
        "target_days": TARGET_DAYS,
        "days_observed": round(days_observed, 2),
        "readiness_score": round(readiness, 1),
        "ready_to_replace_manual_checks": ready,
        "goal": "Binnen 7 dagen aantoonbaar het normale Top40Archiver-beheer zelfstandig afhandelen.",
        "actions": {
            "total": total,
            "completed": completed,
            "successful": successes,
            "failed": int(actions["failures"] or 0),
            "pending": pending,
            "success_rate": round(success_rate, 4),
            "operator_needed": action_operator,
        },
        "cycles": {
            "total": cycle_total,
            "healthy": int(cycles["ok_cycles"] or 0),
            "unresolved": unresolved,
            "operator_needed": cycle_operator,
        },
        "learned_patterns": int(patterns or 0),
        "top_learning": [dict(row) for row in top],
        "generated_at": _iso(),
    }


def learning_context(limit: int = 12) -> list[dict[str, Any]]:
    with ai_memory.connect() as conn:
        rows = conn.execute(
            """
            SELECT problem_key,action,evidence_count,success_rate,average_effect,confidence,last_result
            FROM action_learning
            ORDER BY evidence_count DESC,success_rate DESC,average_effect DESC LIMIT ?
            """,
            (max(1, min(int(limit), 50)),),
        ).fetchall()
    return [dict(row) for row in rows]
