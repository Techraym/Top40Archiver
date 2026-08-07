from __future__ import annotations

from . import ai_recovery
from .ai_operations_worker import run_operations_worker
from .service_recovery import run_service_recovery


def run_cycle() -> dict:
    service_report = run_service_recovery()
    operations_report = run_operations_worker()
    report = ai_recovery.run_cycle()

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
    ai_recovery._save(ai_recovery.REPORT_FILE, report)
    return report


if __name__ == "__main__":
    run_cycle()
