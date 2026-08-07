from __future__ import annotations

from datetime import datetime, timezone

from . import ai_recovery
from .ai_learning import (
    autonomy_report,
    finalize_cycle,
    ingest_cycle_reports,
    new_cycle_id,
    resolve_pending_download_actions,
)
from .ai_operations_worker import run_operations_worker
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

    # Eerst verifiëren we uitgestelde resultaten van eerdere acties. Vooral bij
    # downloads is pas in een latere cyclus zichtbaar of de gekozen zoekstrategie
    # werkelijk tot een geldig gedownload nummer heeft geleid.
    delayed_learning = resolve_pending_download_actions()

    service_report = run_service_recovery()
    operations_report = run_operations_worker()
    report = ai_recovery.run_cycle()

    learning_ingest = ingest_cycle_reports(
        cycle_id,
        service_report=service_report,
        operations_report=operations_report,
        recovery_report=report,
    )

    report["service_recovery"] = service_report
    report["operations_worker"] = operations_report
    report.setdefault("verification", {})["service_critical_after"] = service_report.get(
        "critical_after", 0
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
        and bool(operations_report.get("ok"))
    )

    service_incidents = int(service_report.get("critical_before") or 0)
    download_incidents = int(report.get("failure_count") or 0)
    operations_incidents = 0 if operations_report.get("ok") else 1
    incidents_detected = service_incidents + download_incidents + operations_incidents

    unresolved_after = int(service_report.get("critical_after") or 0)
    if not operations_report.get("ok"):
        unresolved_after += 1

    actions_executed = _count_executed_actions(service_report, operations_report, report)
    operator_needed = unresolved_after

    learning_payload = {
        "cycle_id": cycle_id,
        "resolved_previous_actions": delayed_learning,
        "ingested_this_cycle": learning_ingest,
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
            "operations_ok": bool(operations_report.get("ok")),
            "download_failure_count": report.get("failure_count", 0),
            "download_retryable_count": report.get("retryable_count", 0),
            "actions_executed": actions_executed,
        },
    )
    report["learning"]["autonomy_7_days"] = autonomy_report(7)

    ai_recovery._save(ai_recovery.REPORT_FILE, report)
    return report


if __name__ == "__main__":
    run_cycle()
