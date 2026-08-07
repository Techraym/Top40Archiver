from __future__ import annotations

from datetime import datetime, timezone

from . import ai_recovery
from .ai_code_improvement import run_code_improvement
from .ai_code_repair import run_code_repair
from .ai_learning import (
    autonomy_report,
    finalize_cycle,
    ingest_cycle_reports,
    new_cycle_id,
    record_action,
    resolve_pending_download_actions,
)
from .ai_learning_extras import record_recovery_side_effects
from .ai_operations_worker import run_operations_worker
from .ai_storage_recovery import run_storage_recovery
from .chart_freshness import run_freshness_check
from .service_recovery import run_service_recovery


def _count_executed_actions(*reports: dict) -> int:
    total = 0
    for report in reports:
        for action in report.get("actions") or []:
            if action.get("result") == "cooldown":
                continue
            total += 1
    return total


def run_cycle() -> dict:
    started_at = datetime.now(timezone.utc).isoformat()
    cycle_id = new_cycle_id()

    # Uitgestelde resultaten worden bij iedere cyclus opnieuw beoordeeld. Het
    # werkelijke resultaat beïnvloedt dus meteen de volgende keuze; geen dagdrempel.
    delayed_learning = resolve_pending_download_actions()

    service_report = run_service_recovery()
    storage_report = run_storage_recovery(cycle_id)
    freshness_report = run_freshness_check(False)
    operations_report = run_operations_worker()
    report = ai_recovery.run_cycle()

    learning_ingest = ingest_cycle_reports(
        cycle_id,
        service_report=service_report,
        operations_report=operations_report,
        recovery_report=report,
    )
    side_effect_actions = record_recovery_side_effects(cycle_id, report)

    freshness_action_count = 0
    if freshness_report.get("action") == "refresh_current_charts":
        record_action(
            cycle_id=cycle_id,
            domain="charts",
            problem_key="charts:current_edition_stale",
            action="refresh_current_charts",
            reason="Actuele Top 40 of Tipparade liep achter op de verwachte gepubliceerde ISO-week.",
            before=freshness_report.get("before") or {},
            after=freshness_report.get("after") or {},
            result=freshness_report,
            success=bool(freshness_report.get("ok")),
            effect_score=1.0 if freshness_report.get("ok") else 0.0,
            operator_needed=False,
        )
        freshness_action_count = 1

    # Eerst runtimefouten herstellen. Daarna mag de improvement-worker uitsluitend
    # op basis van aantoonbaar terugkerend herstelwerk een functionele optimalisatie
    # testen. Beide routes gebruiken sandboxtests, versiebackup en canary-rollback.
    code_report = run_code_repair(cycle_id)
    improvement_report = run_code_improvement(cycle_id)

    report["service_recovery"] = service_report
    report["storage_recovery"] = storage_report
    report["chart_freshness"] = freshness_report
    report["operations_worker"] = operations_report
    report["code_repair"] = code_report
    report["code_improvement"] = improvement_report
    report.setdefault("verification", {})["service_critical_after"] = service_report.get(
        "critical_after", 0
    )
    report["verification"]["storage_ok"] = bool(storage_report.get("ok"))
    report["verification"]["disk_free_percent"] = (
        storage_report.get("after", {}).get("free_percent")
    )
    report["verification"]["charts_current"] = bool(
        (freshness_report.get("after") or freshness_report.get("before") or {}).get("ok")
    )
    report["verification"]["operations_ok"] = bool(operations_report.get("ok"))
    report["verification"]["cover_queue_after"] = (
        operations_report.get("after", {}).get("covers", {}).get("eligible_queue", 0)
    )
    report["verification"]["cover_worker_running"] = (
        operations_report.get("after", {}).get("covers", {}).get("running", False)
    )
    report["ok"] = (
        bool(report.get("ok"))
        and bool(service_report.get("ok"))
        and bool(storage_report.get("ok"))
        and bool(operations_report.get("ok"))
        and bool(code_report.get("ok", True))
        and bool(improvement_report.get("ok", True))
    )

    service_incidents = int(service_report.get("critical_before") or 0)
    download_incidents = int(report.get("failure_count") or 0)
    operations_incidents = 0 if operations_report.get("ok") else 1
    storage_incidents = 1 if (storage_report.get("actions") or not storage_report.get("ok")) else 0
    chart_incidents = 0 if (freshness_report.get("before") or {}).get("ok") else 1
    code_incidents = 1 if code_report.get("action") not in {"none", "verify_existing_patch"} else 0
    improvement_incidents = 1 if improvement_report.get("action") not in {"none", "measure_existing_improvement"} else 0
    incidents_detected = (
        service_incidents
        + download_incidents
        + operations_incidents
        + storage_incidents
        + chart_incidents
        + code_incidents
        + improvement_incidents
    )

    unresolved_after = int(service_report.get("critical_after") or 0)
    if not operations_report.get("ok"):
        unresolved_after += 1
    if not storage_report.get("ok"):
        unresolved_after += 1
    if not (freshness_report.get("after") or freshness_report.get("before") or {}).get("ok"):
        unresolved_after += 1
    if not code_report.get("ok", True):
        unresolved_after += 1
    if not improvement_report.get("ok", True):
        unresolved_after += 1

    code_action_count = 1 if code_report.get("action") not in {"none", "cooldown", "verify_existing_patch"} else 0
    improvement_action_count = 1 if improvement_report.get("action") not in {"none", "cooldown", "measure_existing_improvement"} else 0
    actions_executed = (
        _count_executed_actions(service_report, operations_report, report)
        + len(storage_report.get("actions") or [])
        + side_effect_actions
        + freshness_action_count
        + code_action_count
        + improvement_action_count
    )
    operator_needed = unresolved_after + int(storage_report.get("operator_needed") or 0)

    learning_payload = {
        "cycle_id": cycle_id,
        "resolved_previous_actions": delayed_learning,
        "ingested_this_cycle": learning_ingest,
        "configuration_side_effect_actions": side_effect_actions,
        "storage_actions": len(storage_report.get("actions") or []),
        "chart_actions": freshness_action_count,
        "code_repair": code_report.get("action"),
        "code_improvement": improvement_report.get("action"),
        "learning_mode": "continuous_from_first_action",
    }
    report["learning"] = learning_payload

    finalize_cycle(
        cycle_id,
        started_at=started_at,
        ok=bool(report.get("ok")),
        incidents_detected=incidents_detected,
        actions_executed=actions_executed,
        unresolved_after=unresolved_after,
        operator_needed=operator_needed,
        report={
            "service": {
                "critical_before": service_report.get("critical_before", 0),
                "critical_after": service_report.get("critical_after", 0),
            },
            "storage": {
                "ok": storage_report.get("ok"),
                "free_percent": storage_report.get("after", {}).get("free_percent"),
                "actions": len(storage_report.get("actions") or []),
            },
            "charts_current": report["verification"]["charts_current"],
            "operations_ok": bool(operations_report.get("ok")),
            "code_repair": code_report.get("action"),
            "code_improvement": improvement_report.get("action"),
            "download_failure_count": report.get("failure_count", 0),
            "download_retryable_count": report.get("retryable_count", 0),
            "actions_executed": actions_executed,
            "configuration_side_effect_actions": side_effect_actions,
        },
    )
    # Zeven dagen is alleen een rolling trendvenster. Leren en readiness zijn
    # actie-/bewijsgebaseerd en beginnen vanaf de allereerste actie.
    report["learning"]["autonomy_7_days"] = autonomy_report(7)

    ai_recovery._save(ai_recovery.REPORT_FILE, report)
    return report


if __name__ == "__main__":
    run_cycle()
