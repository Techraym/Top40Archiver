from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from .ai_learning import learning_context
from .backup_health import backup_health
from .config import DATA_DIR
from .operations_center import cover_dashboard, database_dashboard, download_dashboard
from .service_watchdog import service_monitor

STATE_FILE = DATA_DIR / "ai" / "operations-worker-state.json"
REPORT_FILE = DATA_DIR / "ai" / "last-operations-worker-report.json"
COOLDOWNS = {
    "run_cover_art": 5,
    "restart_cover_art": 30,
    "restart_ollama": 15,
    "run_database_check": 30,
    "run_history_sync": 30,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _cooldown_ready(state: dict, action: str) -> bool:
    minutes = int(COOLDOWNS.get(action, 10))
    raw = state.get("actions", {}).get(action)
    if not raw:
        return True
    try:
        previous = datetime.fromisoformat(str(raw))
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=timezone.utc)
        return _utcnow() - previous >= timedelta(minutes=minutes)
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


def _service(items: list[dict], unit: str) -> dict:
    return next((x for x in items if x.get("unit") == unit), {})


def _disk_snapshot() -> dict[str, float]:
    usage = shutil.disk_usage(DATA_DIR if DATA_DIR.exists() else "/")
    free_pct = (usage.free / usage.total * 100) if usage.total else 0.0
    return {
        "free_percent": round(free_pct, 2),
        "free_gb": round(usage.free / (1024**3), 2),
        "total_gb": round(usage.total / (1024**3), 2),
    }


def _ollama_snapshot() -> dict[str, Any]:
    url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
    base = url[:-13] if url.endswith("/api/generate") else url.rstrip("/")
    try:
        response = requests.get(base + "/api/tags", timeout=3)
        response.raise_for_status()
        models = [str(x.get("name") or "") for x in response.json().get("models", [])]
        return {
            "reachable": True,
            "model": os.getenv("TOP40_AI_MODEL", "qwen3:4b"),
            "models": models[:20],
        }
    except Exception as exc:
        return {
            "reachable": False,
            "model": os.getenv("TOP40_AI_MODEL", "qwen3:4b"),
            "error": str(exc)[-500:],
        }


def collect_snapshot() -> dict[str, Any]:
    services = service_monitor()
    return {
        "generated_at": _utcnow().isoformat(),
        "services": {
            "critical": [x["unit"] for x in services if x.get("health") == "critical"],
            "attention": [x["unit"] for x in services if x.get("health") == "attention"],
            "cover_worker": _service(services, "top40-archiver-cover-art.service"),
            "cover_timer": _service(services, "top40-archiver-cover-art.timer"),
            "download": _service(services, "top40-archiver-download.service"),
            "ollama": _service(services, "ollama.service"),
        },
        "covers": cover_dashboard(),
        "database": database_dashboard(),
        "downloads": download_dashboard(),
        "disk": _disk_snapshot(),
        "ollama": _ollama_snapshot(),
        "backup": backup_health(),
    }


def _model_assessment(snapshot: dict, actions: list[dict], recommendations: list[str]) -> dict:
    if not snapshot.get("ollama", {}).get("reachable"):
        return {
            "available": False,
            "summary": "Ollama is niet bereikbaar; deterministische veiligheidsregels blijven actief.",
        }

    compact = {
        "services": snapshot.get("services"),
        "covers": snapshot.get("covers"),
        "database": snapshot.get("database"),
        "downloads": snapshot.get("downloads"),
        "disk": snapshot.get("disk"),
        "backup": snapshot.get("backup"),
        "learned_action_outcomes": learning_context(12),
        "actions_already_selected_by_policy": [
            {"action": x.get("action"), "ok": x.get("ok"), "reason": x.get("reason")}
            for x in actions
        ],
        "policy_recommendations": recommendations,
    }
    prompt = (
        "Je bent de lokale Top40Archiver operations-assistent. Analyseer de compacte status NA de "
        "automatische policy-acties en gebruik de meegegeven eerdere actie-uitkomsten als ervaring. "
        "Je mag GEEN shellcommando's, verwijderacties voor audio of nieuwe uitvoerbare acties verzinnen; "
        "uitvoerbare acties worden uitsluitend door de policy-engine bepaald. Retourneer alleen JSON "
        "met velden summary, risk (low/medium/high), attention (array van korte Nederlandse teksten) "
        "en next_check. Benoem downloadwachtrij, coververwerking, database, backups, schijfruimte en "
        "services alleen wanneer ze werkelijk aandacht vragen.\n\n"
        + json.dumps(compact, ensure_ascii=False)
    )
    try:
        response = requests.post(
            os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate"),
            json={
                "model": os.getenv("TOP40_AI_MODEL", "qwen3:4b"),
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "keep_alive": "30m",
            },
            timeout=120,
        )
        response.raise_for_status()
        text = str(response.json().get("response") or "").strip()
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("model gaf geen JSON-object")
        return {
            "available": True,
            "model": os.getenv("TOP40_AI_MODEL", "qwen3:4b"),
            **payload,
        }
    except Exception as exc:
        return {
            "available": False,
            "model": os.getenv("TOP40_AI_MODEL", "qwen3:4b"),
            "summary": "Modelanalyse mislukt; policy-engine heeft de veilige controles wel uitgevoerd.",
            "error": str(exc)[-500:],
        }


def run_operations_worker() -> dict:
    state = _load_json(STATE_FILE, {"actions": {}})
    if not isinstance(state, dict):
        state = {"actions": {}}
    state.setdefault("actions", {})

    before = collect_snapshot()
    actions: list[dict] = []
    recommendations: list[str] = []

    covers = before["covers"]
    cover_worker = before["services"]["cover_worker"]
    eligible = int(covers.get("eligible_queue") or 0)
    worker_active = cover_worker.get("systemd_status") in {"active", "activating"}

    if eligible > 0 and not worker_active and _cooldown_ready(state, "run_cover_art"):
        result = _safe_action("run_cover_art")
        actions.append({
            "action": "run_cover_art",
            "ok": bool(result.get("ok")),
            "reason": f"Er staan {eligible} covers in de actieve wachtrij en de drain-worker draaide niet.",
            "details": result,
        })
        state["actions"]["run_cover_art"] = _utcnow().isoformat()

    cover_state_updated = covers.get("updated_at")
    if eligible > 0 and worker_active and cover_state_updated:
        try:
            updated = datetime.fromisoformat(str(cover_state_updated))
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            stale = _utcnow() - updated > timedelta(minutes=20)
        except ValueError:
            stale = False
        if stale and _cooldown_ready(state, "restart_cover_art"):
            result = _safe_action("restart_cover_art")
            actions.append({
                "action": "restart_cover_art",
                "ok": bool(result.get("ok")),
                "reason": "Coverworker is actief maar heeft ruim 20 minuten geen voortgang gerapporteerd.",
                "details": result,
            })
            state["actions"]["restart_cover_art"] = _utcnow().isoformat()

    if eligible == 0 and int(covers.get("without_cover") or 0) > 0:
        recommendations.append(
            f"De actuele coverwachtrij is volledig verwerkt. {covers.get('without_cover')} tracks hebben nog geen match en worden volgens het retrybeleid later opnieuw gecontroleerd."
        )

    db = before["database"]
    if db.get("health") not in {"ok", "missing"} and _cooldown_ready(state, "run_database_check"):
        result = _safe_action("run_database_check")
        actions.append({
            "action": "run_database_check",
            "ok": bool(result.get("ok")),
            "reason": f"SQLite quick_check rapporteert {db.get('health')!r}.",
            "details": result,
        })
        state["actions"]["run_database_check"] = _utcnow().isoformat()

    disk = before["disk"]
    if float(disk.get("free_percent") or 0) < 5:
        recommendations.append(
            f"Kritiek weinig vrije schijfruimte: {disk.get('free_percent')}% ({disk.get('free_gb')} GB). AI verwijdert geen gedownloade nummers."
        )
    elif float(disk.get("free_percent") or 0) < 10:
        recommendations.append(
            f"Vrije schijfruimte is laag: {disk.get('free_percent')}% ({disk.get('free_gb')} GB)."
        )

    if not before["ollama"].get("reachable") and _cooldown_ready(state, "restart_ollama"):
        result = _safe_action("restart_ollama")
        actions.append({
            "action": "restart_ollama",
            "ok": bool(result.get("ok")),
            "reason": "Ollama-service kan actief lijken terwijl de HTTP-API niet reageert.",
            "details": result,
        })
        state["actions"]["restart_ollama"] = _utcnow().isoformat()

    backup = before.get("backup") or {}
    if not backup.get("ok"):
        recommendations.append(
            "Er is nog geen volledig geverifieerd versie-rollbackpakket beschikbaar. Iedere versie-update wordt geblokkeerd totdat zo'n backup succesvol is gemaakt."
        )

    after = collect_snapshot()
    model = _model_assessment(after, actions, recommendations)
    report = {
        "ok": (
            not after["services"]["critical"]
            and after["database"].get("health") in {"ok", "missing"}
        ),
        "generated_at": _utcnow().isoformat(),
        "mode": "learning-bounded-full-operations-worker",
        "before": before,
        "actions": actions,
        "recommendations": recommendations,
        "after": after,
        "model_assessment": model,
        "learned_action_outcomes": learning_context(20),
        "policy": {
            "shell_access": False,
            "destructive_actions": False,
            "audio_delete_allowed": False,
            "allowed_executor": "/usr/local/sbin/top40-safe-action",
            "cover_drain_required": True,
            "model_can_execute": False,
            "learn_from_every_action": True,
            "verified_backup_before_version_change": True,
        },
    }
    state["last_cycle"] = report["generated_at"]
    _save(STATE_FILE, state)
    _save(REPORT_FILE, report)
    return report


if __name__ == "__main__":
    print(json.dumps(run_operations_worker(), ensure_ascii=False), flush=True)
