from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from . import ai_memory
from .ai_learning import complete_action, start_action
from .ai_log_control import BACKUP_DIR, LIVE_HTML, LOG_CONTROL_DIR, STATE_FILE, validate_log_control_html
from .ai_session_console import operator_context

MODEL = os.getenv("TOP40_AI_MODEL", "qwen3:4b")
VERIFY_MINUTES = 20
STABLE_OPTIMIZE_HOURS = 3
ERROR_RETRY_MINUTES = 20
MODEL_TIMEOUT_SECONDS = 75


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _load() -> dict[str, Any]:
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _save(state: dict[str, Any]) -> None:
    LOG_CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def _read_live() -> str:
    try:
        return LIVE_HTML.read_text(encoding="utf-8")
    except OSError:
        return ""


def _health() -> bool:
    try:
        response = requests.get("http://127.0.0.1:8042/healthz", timeout=5)
        return response.ok
    except Exception:
        return False


def _rollback(state: dict[str, Any], reason: str) -> dict[str, Any]:
    active = state.get("active") if isinstance(state.get("active"), dict) else {}
    backup = Path(str(active.get("backup") or "")) if active else None
    if not backup or not backup.is_file():
        candidates = sorted(BACKUP_DIR.glob("*.html"), reverse=True) if BACKUP_DIR.is_dir() else []
        backup = candidates[0] if candidates else None
    if not backup or not backup.is_file():
        return {"ok": False, "action": "rollback_unavailable", "reason": reason}

    LOG_CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup, LIVE_HTML)
    action_id = int(active.get("action_id") or 0) if active else 0
    if action_id:
        try:
            complete_action(
                action_id,
                success=False,
                after={"rollback_reason": reason},
                result={"rolled_back": True, "backup": str(backup)},
                effect_score=-1.0,
            )
        except Exception:
            pass
    state["active"] = None
    state["status"] = "rolled_back"
    state["last_rollback_at"] = _iso()
    state["last_rollback_reason"] = reason
    _save(state)
    ai_memory.remember_event(
        "ai_ui_rollback",
        "8042 Log Control handmatig/automatisch teruggerold",
        service="ui",
        metadata={"reason": reason, "backup": str(backup)},
    )
    return {"ok": True, "action": "rolled_back", "port": 8042, "reason": reason, "backup": str(backup)}


def manual_rollback(reason: str = "menselijke operator rollback") -> dict[str, Any]:
    return _rollback(_load(), reason)


def _verify_active(state: dict[str, Any]) -> dict[str, Any] | None:
    active = state.get("active")
    if not isinstance(active, dict):
        return None
    current = _read_live()
    validation = validate_log_control_html(current)
    try:
        promoted = datetime.fromisoformat(str(active.get("promoted_at")))
        if promoted.tzinfo is None:
            promoted = promoted.replace(tzinfo=timezone.utc)
    except ValueError:
        return _rollback(state, "ongeldige canary-tijdstempel")
    age = _now() - promoted

    if not validation.get("ok") or not _health():
        return _rollback(state, "8042 canary faalde validatie of healthcheck")
    if age >= timedelta(minutes=VERIFY_MINUTES):
        action_id = int(active.get("action_id") or 0)
        if action_id:
            complete_action(
                action_id,
                success=True,
                after={"validation": validation, "health": True},
                result={"verified_minutes": VERIFY_MINUTES, "port": 8042},
                effect_score=1.0,
            )
        state["active"] = None
        state["status"] = "verified"
        state["last_verified_at"] = _iso()
        _save(state)
        return {"ok": True, "action": "verified_revision", "port": 8042, "revision": active.get("revision")}
    return {
        "ok": True,
        "action": "measure_ui_canary",
        "port": 8042,
        "revision": active.get("revision"),
        "minutes_remaining": max(0, VERIFY_MINUTES - int(age.total_seconds() // 60)),
    }


def _reason(state: dict[str, Any], force: bool) -> str | None:
    if force:
        return "geforceerde operatorgestuurde herbouw"
    live = _read_live()
    if not live or not validate_log_control_html(live).get("ok"):
        return "8042 beheerpagina ontbreekt of voldoet niet aan het vaste contract"
    last = state.get("last_promoted_at") or state.get("last_verified_at")
    if last:
        try:
            parsed = datetime.fromisoformat(str(last))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if _now() - parsed >= timedelta(hours=STABLE_OPTIMIZE_HOURS):
                return "periodieke verbetering van scanbaarheid en foutmonitoring op 8042"
        except ValueError:
            pass
    return None


def _ask_model(reason: str, current: str) -> str:
    guidance = operator_context("ui")
    prompt = f"""Je bent de lokale Top40Archiver UI engineer voor uitsluitend poort 8042.
De menselijke productpagina op poort 8040 is ABSOLUUT VERBODEN terrein: je mag niets voor 8040 ontwerpen of wijzigen.
Er bestaan maximaal drie top-level pagina's in het product: 8040, 8041 en 8042. Maak geen extra pagina's, routes of navigatieniveaus.
8042 is de compacte Log & AI Control pagina. De operator moet altijd kunnen controleren wat Qwen doet en via 8041 richtlijnen/HOLD/rollback kunnen corrigeren.

REDEN:
{reason}

HARDE REGELS:
- Geef uitsluitend één volledig HTML5-document.
- Alleen HTML en CSS; GEEN JavaScript of script-tags. De runtime wordt door policy-code geïnjecteerd.
- Geen externe URL's, fonts, afbeeldingen, CDN's, iframes, forms of event-handlers.
- Verplicht exact één container met ieder id: lc-status, lc-errors, lc-live, lc-policy.
- Mobiel en desktop bruikbaar, geen horizontale overflow.
- Zakelijk Nederlands, compact en scanbaar. Geen marketingtekst.
- Maak geen vierde pagina en verwijs niet naar wijzigingen aan 8040.

ACTIEVE OPERATORRICHTLIJNEN:
{guidance}

HUIDIGE HTML:
{current[:22000]}
"""
    response = requests.post(
        os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate"),
        json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "keep_alive": "30m",
            "options": {"temperature": 0.2, "num_predict": 1800},
        },
        timeout=MODEL_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    text = str(response.json().get("response") or "").strip()
    if text.startswith("```"):
        import re
        text = re.sub(r"^```(?:html)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    start = text.casefold().find("<!doctype html")
    if start > 0:
        text = text[start:]
    end = text.casefold().rfind("</html>")
    if end >= 0:
        text = text[: end + len("</html>")]
    return text.strip()


def run_log_ui_designer(cycle_id: str, force: bool = False) -> dict[str, Any]:
    state = _load()
    state.setdefault("revision", 0)
    verification = _verify_active(state)
    if state.get("active"):
        return verification or {"ok": True, "action": "measure_ui_canary", "port": 8042}

    reason = _reason(state, force)
    if not reason:
        return {"ok": True, "action": "none", "port": 8042, "revision": state.get("revision", 0), "verification": verification}

    previous = state.get("last_attempt_at")
    if previous and not force:
        try:
            parsed = datetime.fromisoformat(str(previous))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if _now() - parsed < timedelta(minutes=ERROR_RETRY_MINUTES):
                return {"ok": True, "action": "cooldown", "port": 8042, "reason": reason}
        except ValueError:
            pass

    current = _read_live()
    next_revision = int(state.get("revision") or 0) + 1
    action_id = start_action(
        cycle_id=cycle_id,
        domain="ui",
        problem_key="ui:log_control_8042",
        action="generate_and_promote_log_control",
        reason=reason,
        subject=f"8042-ui-revision:{next_revision}",
        before={"port": 8042, "revision": state.get("revision", 0), "validation": validate_log_control_html(current)},
        reversible=True,
    )
    state["last_attempt_at"] = _iso()
    state["last_reason"] = reason
    _save(state)

    try:
        html = _ask_model(reason, current)
        validation = validate_log_control_html(html)
        if not validation.get("ok"):
            complete_action(action_id, success=False, after={"validation": validation}, result={"reason": "generated_html_failed_contract"}, effect_score=0.0)
            state["status"] = "generation_rejected"
            state["last_validation"] = validation
            _save(state)
            return {"ok": True, "action": "candidate_rejected", "port": 8042, "validation": validation}

        old_sha = hashlib.sha256(current.encode("utf-8", "ignore")).hexdigest() if current else None
        if old_sha and old_sha == validation.get("sha256"):
            complete_action(action_id, success=True, after={"validation": validation}, result={"reason": "no_change_needed"}, effect_score=0.2)
            state["status"] = "unchanged"
            _save(state)
            return {"ok": True, "action": "no_change", "port": 8042, "revision": state.get("revision", 0)}

        LOG_CONTROL_DIR.mkdir(parents=True, exist_ok=True)
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup = BACKUP_DIR / f"revision-{int(state.get('revision') or 0):06d}-{_now().strftime('%Y%m%dT%H%M%SZ')}.html"
        backup.write_text(current, encoding="utf-8")
        candidate = LOG_CONTROL_DIR / f"revision-{next_revision:06d}.html"
        candidate.write_text(html, encoding="utf-8")
        shutil.copy2(candidate, LIVE_HTML)
        promoted_at = _iso()
        state.update({
            "revision": next_revision,
            "status": "canary",
            "model": MODEL,
            "last_promoted_at": promoted_at,
            "last_validation": validation,
            "active": {
                "revision": next_revision,
                "action_id": action_id,
                "promoted_at": promoted_at,
                "backup": str(backup),
                "candidate": str(candidate),
                "sha256": validation.get("sha256"),
            },
        })
        _save(state)
        ai_memory.remember_event(
            "ai_ui_promoted",
            f"Lokale AI promoveerde 8042 Log Control revisie {next_revision} naar canary",
            service="ui",
            metadata={"port": 8042, "reason": reason, "validation": validation},
        )
        return {"ok": True, "action": "promoted_ui_canary", "port": 8042, "revision": next_revision, "reason": reason, "validation": validation}
    except Exception as exc:
        try:
            complete_action(action_id, success=False, result={"error": str(exc)[-2000:]}, effect_score=0.0)
        except Exception:
            pass
        state["status"] = "generation_error"
        state["last_error"] = str(exc)[-2000:]
        _save(state)
        return {"ok": False, "action": "ui_generation_error", "port": 8042, "error": str(exc)[-2000:]}
