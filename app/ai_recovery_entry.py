from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import ai_recovery
from .ai_code_improvement import STATE_FILE as CODE_IMPROVEMENT_STATE, run_code_improvement
from .ai_code_repair import STATE_FILE as CODE_REPAIR_STATE, run_code_repair
from .ai_control_room import STATE_FILE as CONTROL_ROOM_STATE
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
from .ai_session_console import log_session_event, mark_guidance_applied, operator_context, scope_held
from .ai_storage_recovery import run_storage_recovery
from .ai_ui_designer import run_ui_designer
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


def _active_state(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return isinstance(data, dict) and isinstance(data.get("active"), dict)
    except Exception:
        return False


def _sync_ui_operator_context() -> None:
    try:
        state = json.loads(CONTROL_ROOM_STATE.read_text(encoding="utf-8")) if CONTROL_ROOM_STATE.is_file() else {}
        if not isinstance(state, dict):
            state = {}
        state["operator_guidance"] = operator_context("ui")
        CONTROL_ROOM_STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONTROL_ROOM_STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(CONTROL_ROOM_STATE)
    except Exception:
        pass


def _working(cycle_id: str, domain: str, title: str, message: str) -> None:
    log_session_event(
        event_type="working",
        title=title,
        message=message,
        cycle_id=cycle_id,
        domain=domain,
        role="assistant",
        status="working",
    )


def _result(cycle_id: str, domain: str, title: str, report: dict) -> None:
    action = str(report.get("action") or "controle afgerond")
    ok = bool(report.get("ok", True))
    summary = ""
    model = report.get("model_assessment") or {}
    if isinstance(model, dict):
        summary = str(model.get("summary") or "")
    if not summary:
        summary = str(report.get("reason") or report.get("message") or "")
    if not summary:
        summary = f"Resultaat: {action}."
    raw = json.dumps(report, ensure_ascii=False, default=str)
    preview_limit = 12_000
    log_session_event(
        event_type="stage_result",
        title=title,
        message=summary,
        cycle_id=cycle_id,
        domain=domain,
        role="assistant",
        status="ok" if ok else "attention",
        metadata={
            "action": action,
            "ok": ok,
            "report_preview": raw[:preview_limit],
            "report_truncated": len(raw) > preview_limit,
            "report_bytes": len(raw.encode("utf-8", "ignore")),
        },
    )


def run_cycle() -> dict:
    started_at = datetime.now(timezone.utc).isoformat()
    cycle_id = new_cycle_id()
    log_session_event(
        event_type="cycle_start",
        title="Nieuwe autonome AI-cyclus",
        message="Ik start zelfstandig een nieuwe controle- en herstelcyclus. Menselijke input is niet nodig; actieve operatorrichtlijnen worden wel eerst geladen.",
        cycle_id=cycle_id,
        domain="orchestrator",
        role="assistant",
        status="working",
    )
    mark_guidance_applied("global", cycle_id)

    delayed_learning = resolve_pending_download_actions()
    if delayed_learning:
        log_session_event(
            event_type="learning",
            title="Eerdere acties opnieuw beoordeeld",
            message=f"Ik heb {delayed_learning} uitgestelde actie-resultaten opnieuw beoordeeld voordat ik nieuwe keuzes maak.",
            cycle_id=cycle_id,
            domain="learning",
            role="assistant",
            status="ok",
        )

    _working(cycle_id, "services", "Services controleren", "Ik controleer kritieke services en timers en herstel alleen via de bestaande whitelist-policy.")
    service_report = run_service_recovery()
    _result(cycle_id, "services", "Servicecontrole afgerond", service_report)

    _working(cycle_id, "storage", "Opslag controleren", "Ik controleer vrije ruimte en veilige tijdelijke opslag. Gedownloade audio blijft buiten bereik.")
    storage_report = run_storage_recovery(cycle_id)
    _result(cycle_id, "storage", "Opslagcontrole afgerond", storage_report)

    _working(cycle_id, "charts", "Top 40 en Tipparade controleren", "Ik controleer of de actuele hitlijsten bij de verwachte editie/week horen.")
    freshness_report = run_freshness_check(False)
    _result(cycle_id, "charts", "Hitlijstcontrole afgerond", freshness_report)

    _working(cycle_id, "operations", "Operations controleren", "Ik controleer downloads, covers, database, backups, schijfruimte en Ollama en gebruik eerdere leerresultaten bij de beoordeling.")
    operations_report = run_operations_worker()
    _result(cycle_id, "operations", "Operations-beoordeling afgerond", operations_report)

    _working(cycle_id, "downloads", "Downloadherstel controleren", "Ik beoordeel downloadfouten en retries volgens de begrensde herstelstrategieën.")
    report = ai_recovery.run_cycle()
    _result(cycle_id, "downloads", "Downloadherstel afgerond", report)

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

    code_hold = scope_held("code")
    repair_active = _active_state(CODE_REPAIR_STATE)
    improvement_active = _active_state(CODE_IMPROVEMENT_STATE)
    if code_hold and not repair_active and not improvement_active:
        code_report = {
            "ok": True,
            "action": "skipped_operator_hold",
            "reason": "Menselijke operator heeft nieuwe autonome codewijzigingen tijdelijk gepauzeerd.",
        }
        improvement_report = {
            "ok": True,
            "action": "skipped_operator_hold",
            "reason": "Menselijke operator heeft nieuwe autonome codewijzigingen tijdelijk gepauzeerd.",
        }
        _result(cycle_id, "code", "Codewijzigingen gepauzeerd", code_report)
    else:
        _working(cycle_id, "code", "Runtime-code controleren", "Ik zoek naar aantoonbare terugkerende runtimefouten. Bestaande canaries worden altijd geverifieerd, ook tijdens een operator-hold.")
        code_report = run_code_repair(cycle_id)
        _result(cycle_id, "code", "Runtime-codecontrole afgerond", code_report)
        if code_report.get("action") == "none" and not code_hold:
            _working(cycle_id, "code", "Structurele verbetering beoordelen", "Als dezelfde herstelactie vaak nodig blijft, onderzoek ik een kleine meetbare broncodeverbetering in sandbox.")
            improvement_report = run_code_improvement(cycle_id)
        elif improvement_active:
            improvement_report = run_code_improvement(cycle_id)
        else:
            improvement_report = {
                "ok": True,
                "action": "skipped_code_repair_active" if not code_hold else "skipped_operator_hold",
                "reason": "Runtime-repair en optimalisatie worden nooit tegelijk gepromoveerd." if not code_hold else "Nieuwe code-optimalisatie is door de operator gepauzeerd.",
            }
        _result(cycle_id, "code", "Codeverbetering afgerond", improvement_report)

    _sync_ui_operator_context()
    ui_hold = scope_held("ui")
    ui_active = _active_state(CONTROL_ROOM_STATE)
    if ui_hold and not ui_active:
        ui_report = {
            "ok": True,
            "action": "skipped_operator_hold",
            "reason": "Menselijke operator heeft nieuwe autonome wijzigingen van de Control Room tijdelijk gepauzeerd.",
        }
        _result(cycle_id, "ui", "Control Room wijziging gepauzeerd", ui_report)
    else:
        _working(cycle_id, "ui", "Control Room beoordelen", "Ik beoordeel de 8041-layout en browsertelemetrie. Een bestaande UI-canary blijft onder toezicht; nieuwe revisies volgen operatorrichtlijnen.")
        ui_report = run_ui_designer(cycle_id)
        _result(cycle_id, "ui", "Control Room beoordeling afgerond", ui_report)

    report["service_recovery"] = service_report
    report["storage_recovery"] = storage_report
    report["chart_freshness"] = freshness_report
    report["operations_worker"] = operations_report
    report["code_repair"] = code_report
    report["code_improvement"] = improvement_report
    report["control_room_ui"] = ui_report
    report.setdefault("verification", {})["service_critical_after"] = service_report.get("critical_after", 0)
    report["verification"]["storage_ok"] = bool(storage_report.get("ok"))
    report["verification"]["disk_free_percent"] = storage_report.get("after", {}).get("free_percent")
    report["verification"]["charts_current"] = bool((freshness_report.get("after") or freshness_report.get("before") or {}).get("ok"))
    report["verification"]["operations_ok"] = bool(operations_report.get("ok"))
    report["verification"]["cover_queue_after"] = operations_report.get("after", {}).get("covers", {}).get("eligible_queue", 0)
    report["verification"]["cover_worker_running"] = operations_report.get("after", {}).get("covers", {}).get("running", False)
    report["verification"]["control_room_ui_ok"] = bool(ui_report.get("ok", True))
    report["ok"] = (
        bool(report.get("ok"))
        and bool(service_report.get("ok"))
        and bool(storage_report.get("ok"))
        and bool(operations_report.get("ok"))
        and bool(code_report.get("ok", True))
        and bool(improvement_report.get("ok", True))
        and bool(ui_report.get("ok", True))
    )

    service_incidents = int(service_report.get("critical_before") or 0)
    download_incidents = int(report.get("failure_count") or 0)
    operations_incidents = 0 if operations_report.get("ok") else 1
    storage_incidents = 1 if (storage_report.get("actions") or not storage_report.get("ok")) else 0
    chart_incidents = 0 if (freshness_report.get("before") or {}).get("ok") else 1
    code_incidents = 1 if code_report.get("action") not in {"none", "verify_existing_patch", "skipped_operator_hold"} else 0
    improvement_incidents = 1 if improvement_report.get("action") not in {"none", "measure_existing_improvement", "skipped_code_repair_active", "skipped_operator_hold"} else 0
    ui_incidents = 1 if ui_report.get("action") in {"candidate_rejected", "ui_generation_error", "rolled_back"} else 0
    incidents_detected = service_incidents + download_incidents + operations_incidents + storage_incidents + chart_incidents + code_incidents + improvement_incidents + ui_incidents

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
    if not ui_report.get("ok", True):
        unresolved_after += 1

    code_action_count = 1 if code_report.get("action") not in {"none", "cooldown", "verify_existing_patch", "skipped_operator_hold"} else 0
    improvement_action_count = 1 if improvement_report.get("action") not in {"none", "cooldown", "measure_existing_improvement", "skipped_code_repair_active", "skipped_operator_hold"} else 0
    ui_action_count = 1 if ui_report.get("action") in {"promoted_ui_canary", "candidate_rejected", "ui_generation_error", "rolled_back", "verified_revision"} else 0
    actions_executed = (
        _count_executed_actions(service_report, operations_report, report)
        + len(storage_report.get("actions") or [])
        + side_effect_actions
        + freshness_action_count
        + code_action_count
        + improvement_action_count
        + ui_action_count
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
        "control_room_ui": ui_report.get("action"),
        "operator_guidance": operator_context("global"),
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
            "service": {"critical_before": service_report.get("critical_before", 0), "critical_after": service_report.get("critical_after", 0)},
            "storage": {"ok": storage_report.get("ok"), "free_percent": storage_report.get("after", {}).get("free_percent"), "actions": len(storage_report.get("actions") or [])},
            "charts_current": report["verification"]["charts_current"],
            "operations_ok": bool(operations_report.get("ok")),
            "code_repair": code_report.get("action"),
            "code_improvement": improvement_report.get("action"),
            "control_room_ui": ui_report.get("action"),
            "download_failure_count": report.get("failure_count", 0),
            "download_retryable_count": report.get("retryable_count", 0),
            "actions_executed": actions_executed,
            "configuration_side_effect_actions": side_effect_actions,
        },
    )
    report["learning"]["autonomy_7_days"] = autonomy_report(7)

    log_session_event(
        event_type="cycle_complete",
        title="Autonome cyclus afgerond",
        message=(
            f"Ik heb de cyclus {'zonder kritieke restfouten afgerond' if report.get('ok') else 'met aandachtspunten afgerond'}. "
            f"Gedetecteerde incidenten: {incidents_detected}; uitgevoerde acties: {actions_executed}; onopgelost na afloop: {unresolved_after}. "
            "Ik ga zonder menselijke bevestiging door met de volgende geplande cyclus."
        ),
        cycle_id=cycle_id,
        domain="orchestrator",
        role="assistant",
        status="ok" if report.get("ok") else "attention",
        metadata={"incidents_detected": incidents_detected, "actions_executed": actions_executed, "unresolved_after": unresolved_after},
    )

    ai_recovery._save(ai_recovery.REPORT_FILE, report)
    return report


if __name__ == "__main__":
    run_cycle()
