from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .ai_learning import learning_context
from .ai_session_console import operator_context, scope_held
from .config import DATA_DIR
from .service_watchdog import service_monitor, unhealthy_services

STATE_FILE = DATA_DIR / "ai" / "service-recovery-state.json"
REPORT_FILE = DATA_DIR / "ai" / "last-service-recovery-report.json"
COOLDOWN_MINUTES = 10
MODEL_TIMEOUT_SECONDS = 45


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"actions": {}}


def _save(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _cooldown_ready(state: dict, action: str) -> bool:
    raw = state.get("actions", {}).get(action)
    if not raw:
        return True
    try:
        previous = datetime.fromisoformat(str(raw))
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=timezone.utc)
        return _utcnow() - previous >= timedelta(minutes=COOLDOWN_MINUTES)
    except ValueError:
        return True


def _safe_action(action: str) -> dict:
    completed = subprocess.run(
        ["/usr/local/sbin/top40-safe-action", action],
        capture_output=True,
        text=True,
        timeout=100,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {
            "ok": False,
            "action": action,
            "returncode": completed.returncode,
            "stderr": completed.stderr[-1000:],
        }
    payload.setdefault("returncode", completed.returncode)
    return payload


def _model_assessment(critical: list[dict]) -> dict:
    if not critical:
        return {
            "available": True,
            "skipped": True,
            "summary": "Na de policy-acties zijn geen vereiste systemd-componenten meer defect; extra modeldiagnose is niet nodig.",
        }

    model = os.getenv("TOP40_AI_MODEL", "qwen3:4b")
    compact = [
        {
            "unit": item["unit"],
            "kind": item["kind"],
            "systemd_status": item["systemd_status"],
            "result": item["result"],
            "expected": item["expected"],
            "allowed_repair": item["repair_action"],
        }
        for item in critical
    ]
    compact_learning = learning_context(8)
    prompt = (
        "Je bent de lokale Top40Archiver operations-assistent. Gebruik eerdere geverifieerde "
        "actie-uitkomsten als ervaring. Analyseer uitsluitend de systemd-afwijkingen die NA de "
        "automatische policy-acties nog bestaan. Actieve menselijke operatorrichtlijnen sturen jouw "
        "beoordeling, maar mogen harde veiligheidsregels nooit versoepelen. De acties zijn door een vaste "
        "veiligheidslaag begrensd. Geef in maximaal 3 Nederlandse zinnen aan wat nog fout is, waarom dat "
        "relevant is en welke bekende oplossing eerder effectief of ineffectief was. Verzin geen "
        "shellcommando's en wijzig niets zelf.\n\n"
        + json.dumps(
            {
                "afwijkingen": compact,
                "geleerde_acties": compact_learning,
                "operatorrichtlijnen": operator_context("services"),
            },
            ensure_ascii=False,
        )
    )
    try:
        response = requests.post(
            os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate"),
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "keep_alive": "30m",
                "options": {"temperature": 0.1, "num_predict": 180},
            },
            timeout=MODEL_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        text = str(response.json().get("response") or "").strip()
        return {"available": True, "model": model, "summary": text[:1500]}
    except requests.Timeout as exc:
        return {
            "available": False,
            "model": model,
            "timed_out": True,
            "summary": "Modeldiagnose bereikte de tijdslimiet; de policy-engine heeft de herstelacties wel uitgevoerd en de cyclus blijft doorlopen.",
            "error": str(exc)[-500:],
        }
    except Exception as exc:
        return {
            "available": False,
            "model": model,
            "summary": "Modeldiagnose niet beschikbaar; de policy-engine heeft de herstelacties wel uitgevoerd.",
            "error": str(exc)[-500:],
        }


def run_service_recovery() -> dict:
    state = _load_state()
    state.setdefault("actions", {})
    before = service_monitor()
    critical = unhealthy_services(before)
    actions: list[dict] = []
    held = scope_held("services")

    for item in critical:
        action = str(item.get("repair_action") or "")
        if not action:
            continue
        if held:
            actions.append({
                "unit": item["unit"],
                "action": action,
                "result": "operator_hold",
                "ok": False,
            })
            continue
        if not _cooldown_ready(state, action):
            actions.append({
                "unit": item["unit"],
                "action": action,
                "result": "cooldown",
                "ok": False,
            })
            continue
        result = _safe_action(action)
        actions.append({
            "unit": item["unit"],
            "action": action,
            "result": "gelukt" if result.get("ok") else "mislukt",
            "ok": bool(result.get("ok")),
            "details": result,
        })
        state["actions"][action] = _utcnow().isoformat()

    after = service_monitor()
    critical_after = [x for x in after if x.get("health") == "critical"]
    model = _model_assessment(critical_after)

    report = {
        "ok": not critical_after or held,
        "generated_at": _utcnow().isoformat(),
        "mode": "learning-policy-guarded-ai-service-recovery",
        "operator_hold": held,
        "operator_guidance": operator_context("services"),
        "model_assessment": model,
        "critical_before": len(critical),
        "critical_after": len(critical_after),
        "actions": actions,
        "services_before": before,
        "services_after": after,
        "remaining": [
            {
                "unit": x["unit"],
                "display_status": x["display_status"],
                "explanation": x["explanation"],
                "repair_action": x.get("repair_action"),
            }
            for x in critical_after
        ],
    }
    state["last_cycle"] = report["generated_at"]
    _save(STATE_FILE, state)
    _save(REPORT_FILE, report)
    return report
