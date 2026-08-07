from __future__ import annotations

from . import ai_recovery
from .service_recovery import run_service_recovery


def run_cycle() -> dict:
    service_report = run_service_recovery()
    report = ai_recovery.run_cycle()
    report["service_recovery"] = service_report
    report.setdefault("verification", {})["service_critical_after"] = service_report.get("critical_after", 0)
    report["ok"] = bool(report.get("ok")) and bool(service_report.get("ok"))
    ai_recovery._save(ai_recovery.REPORT_FILE, report)
    return report


if __name__ == "__main__":
    run_cycle()
