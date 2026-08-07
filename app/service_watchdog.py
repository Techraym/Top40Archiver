from __future__ import annotations

import subprocess
from typing import Any

SERVICE_POLICIES: dict[str, dict[str, Any]] = {
    "top40-archiver-web.service": {"group": "web", "kind": "daemon", "required": True, "repair_action": "restart_web"},
    "top40-download-manager.service": {"group": "download", "kind": "daemon", "required": True, "repair_action": "restart_download"},
    "top40-archiver-ai.service": {"group": "ai", "kind": "daemon", "required": True, "repair_action": "restart_ai"},
    "ollama.service": {"group": "ollama", "kind": "daemon", "required": True, "repair_action": "restart_ollama"},
    "top40-log-reader.service": {"group": "system", "kind": "daemon", "required": True, "repair_action": "restart_log_reader"},

    "top40-archiver-cover-art.timer": {"group": "cover", "kind": "timer", "required": True, "repair_action": "repair_cover_timer"},
    "top40-archiver-id3-cover.timer": {"group": "cover", "kind": "timer", "required": True, "repair_action": "repair_id3_cover_timer"},
    "top40-archiver-history.timer": {"group": "database", "kind": "timer", "required": True, "repair_action": "repair_history_timer"},
    "top40-archiver-check.timer": {"group": "charts", "kind": "timer", "required": True, "repair_action": "repair_check_timer"},
    "top40-archiver-freshness.timer": {"group": "charts", "kind": "timer", "required": True, "repair_action": "repair_freshness_timer"},
    "top40-archiver-auto-update.timer": {"group": "updater", "kind": "timer", "required": True, "repair_action": "repair_auto_update_timer"},
    "top40-ai-recovery.timer": {"group": "ai", "kind": "timer", "required": True, "repair_action": "repair_ai_recovery_timer"},
    "top40-archiver-incident-scan.timer": {"group": "system", "kind": "timer", "required": True, "repair_action": "repair_incident_timer"},

    "top40-archiver-cover-art.service": {"group": "cover", "kind": "oneshot", "required": True, "paired_timer": "top40-archiver-cover-art.timer"},
    "top40-archiver-id3-cover.service": {"group": "cover", "kind": "oneshot", "required": True, "paired_timer": "top40-archiver-id3-cover.timer"},
    "top40-archiver-history.service": {"group": "database", "kind": "oneshot", "required": True, "paired_timer": "top40-archiver-history.timer"},
    "top40-archiver-check.service": {"group": "charts", "kind": "oneshot", "required": True, "paired_timer": "top40-archiver-check.timer"},
    "top40-archiver-freshness.service": {"group": "charts", "kind": "oneshot", "required": True, "paired_timer": "top40-archiver-freshness.timer"},
    "top40-archiver-auto-update.service": {"group": "updater", "kind": "oneshot", "required": True, "paired_timer": "top40-archiver-auto-update.timer"},
    "top40-ai-recovery.service": {"group": "ai", "kind": "oneshot", "required": True, "paired_timer": "top40-ai-recovery.timer"},
    "top40-archiver-incident-scan.service": {"group": "system", "kind": "oneshot", "required": True, "paired_timer": "top40-archiver-incident-scan.timer"},
}

PROPERTIES = (
    "LoadState", "UnitFileState", "ActiveState", "SubState", "Result", "MainPID",
    "NRestarts", "ActiveEnterTimestamp", "MemoryCurrent", "CPUUsageNSec", "TasksCurrent",
)

FAILED_RESULTS = {"failed", "timeout", "exit-code", "signal", "core-dump"}


def _as_int(value: object, default: int = 0) -> int:
    try:
        text = str(value or "").strip()
        if not text or text.casefold() in {"[not set]", "n/a", "none", "unknown", "infinity"}:
            return default
        return int(text)
    except (TypeError, ValueError, OverflowError):
        return default


def _show(unit: str) -> dict[str, str]:
    try:
        proc = subprocess.run(
            ["systemctl", "show", unit, "--property=" + ",".join(PROPERTIES)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"LoadState": "unknown", "ActiveState": "unknown", "SubState": "unknown", "Result": "error", "Error": str(exc)}
    values = {
        key: value
        for line in (proc.stdout or "").splitlines()
        if "=" in line
        for key, value in [line.split("=", 1)]
    }
    if proc.returncode and not values:
        values.update({"LoadState": "unknown", "ActiveState": "unknown", "SubState": "unknown", "Result": "error"})
        values["Error"] = (proc.stderr or "systemctl show mislukt")[-500:]
    return values


def _logical_state(unit: str, state: dict[str, str], all_states: dict[str, dict[str, str]]) -> tuple[str, str, str]:
    policy = SERVICE_POLICIES[unit]
    kind = policy["kind"]
    load = (state.get("LoadState") or "unknown").casefold()
    active = (state.get("ActiveState") or "unknown").casefold()
    sub = (state.get("SubState") or "unknown").casefold()
    result = (state.get("Result") or "").casefold()

    if load == "not-found":
        return "critical", "ontbreekt", "De vereiste systemd-unit is niet geïnstalleerd."

    if kind == "daemon":
        if active == "active":
            return "healthy", "actief", "Permanente service draait."
        if active == "activating":
            return "attention", "start op", "Permanente service is bezig met starten."
        return "critical", active or "onbekend", "Permanente service hoort continu actief te zijn."

    if kind == "timer":
        if active == "active":
            return "healthy", "timer actief", "Timer bewaakt en start de gekoppelde onderhoudstaak automatisch."
        if active == "activating":
            return "attention", "timer start op", "Timer is bezig met activeren."
        return "critical", active or "onbekend", "Deze timer hoort actief te zijn zodat de onderhoudstaak automatisch blijft lopen."

    paired = str(policy.get("paired_timer") or "")
    paired_state = all_states.get(paired, {})
    paired_active = (paired_state.get("ActiveState") or "").casefold() == "active"
    failed_last_run = active == "failed" or result in FAILED_RESULTS

    if active in {"active", "activating"}:
        return "healthy", "bezig", "Oneshot-taak is op dit moment actief."

    if failed_last_run and paired_active:
        return (
            "attention",
            "laatste run mislukt; retry gepland",
            "De laatste oneshot-uitvoering mislukte, maar de gekoppelde timer is actief en plant automatisch een nieuwe poging.",
        )
    if failed_last_run and not paired_active:
        return (
            "critical",
            "mislukt zonder actieve retry",
            "De laatste oneshot-uitvoering mislukte en de gekoppelde timer is niet actief; automatische retry ontbreekt.",
        )
    if active == "inactive" and paired_active:
        return "healthy", "stand-by", "Normaal voor een oneshot-service: de gekoppelde timer is actief en start hem wanneer nodig."
    if active == "inactive" and not paired_active:
        return "attention", "stand-by zonder timer", "De worker hoeft niet continu actief te zijn, maar de gekoppelde timer is niet actief."
    return "attention", active or sub or "onbekend", "Status wijkt af van het verwachte oneshot-gedrag."


def service_monitor() -> list[dict[str, Any]]:
    all_states = {unit: _show(unit) for unit in SERVICE_POLICIES}
    result: list[dict[str, Any]] = []
    for unit, policy in SERVICE_POLICIES.items():
        state = all_states[unit]
        health, display_status, explanation = _logical_state(unit, state, all_states)
        raw_status = state.get("ActiveState") or "unknown"
        logical_status = "active" if health == "healthy" else "activating" if health == "attention" else "failed"
        result.append({
            "group": policy["group"],
            "unit": unit,
            "kind": policy["kind"],
            "required": bool(policy.get("required", False)),
            "status": logical_status,
            "substatus": state.get("SubState") or "unknown",
            "systemd_status": raw_status,
            "unit_file_state": state.get("UnitFileState") or "unknown",
            "result": state.get("Result") or "unknown",
            "pid": _as_int(state.get("MainPID")),
            "restarts": _as_int(state.get("NRestarts")),
            "last_restart": state.get("ActiveEnterTimestamp") or None,
            "ram_mb": round(_as_int(state.get("MemoryCurrent")) / 1048576, 1),
            "cpu_seconds": round(_as_int(state.get("CPUUsageNSec")) / 1_000_000_000, 1),
            "threads": _as_int(state.get("TasksCurrent")),
            "error": state.get("Error"),
            "health": health,
            "display_status": display_status,
            "expected": "continu actief" if policy["kind"] == "daemon" else "timer actief" if policy["kind"] == "timer" else "alleen actief tijdens uitvoering",
            "explanation": explanation,
            "paired_timer": policy.get("paired_timer"),
            "repair_action": policy.get("repair_action"),
        })
    return result


def unhealthy_services(items: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    rows = items if items is not None else service_monitor()
    return [row for row in rows if row.get("health") == "critical" and row.get("repair_action")]
