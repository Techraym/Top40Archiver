from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from . import ai_memory
from .ai_control_room import (
    CONTROL_ROOM_DIR,
    LIVE_HTML,
    REQUIRED_SECTION_IDS,
    STATE_FILE,
    control_room_snapshot,
    validate_control_room_html,
)
from .ai_learning import complete_action, start_action

BACKUP_DIR = CONTROL_ROOM_DIR / "backups"
MODEL = os.getenv("TOP40_AI_MODEL", "qwen3:4b")
VERIFY_MINUTES = 20
STABLE_OPTIMIZE_HOURS = 6
ERROR_RETRY_MINUTES = 5
MIN_HEALTH_EVENTS_FOR_VERIFY = 3
MIN_HEALTH_EVENTS_FOR_OPTIMIZE = 8


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _load_state() -> dict[str, Any]:
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _save_state(state: dict[str, Any]) -> None:
    CONTROL_ROOM_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def _read_live() -> str:
    try:
        return LIVE_HTML.read_text(encoding="utf-8")
    except OSError:
        return ""


def _telemetry(revision: int, limit: int = 800) -> dict[str, Any]:
    with ai_memory.connect() as conn:
        rows = conn.execute(
            "SELECT event_type,duration_ms,detail_json,created_at FROM ui_telemetry WHERE revision=? ORDER BY id DESC LIMIT ?",
            (int(revision), max(1, min(limit, 2000))),
        ).fetchall()
    events = []
    for row in rows:
        try:
            detail = json.loads(str(row["detail_json"] or "{}"))
        except Exception:
            detail = {}
        events.append(dict(row) | {"detail": detail})
    page = [x for x in events if x["event_type"] == "page_health"]
    fatal = [x for x in events if x["event_type"] in {"js_error", "render_error"}]
    api_errors = [x for x in events if x["event_type"] == "api_error"]
    overflow = [x for x in page if bool((x.get("detail") or {}).get("horizontal_overflow"))]
    missing = [x for x in page if (x.get("detail") or {}).get("missing_sections")]
    durations = [float(x["duration_ms"]) for x in page if x.get("duration_ms") is not None]
    return {
        "events": len(events),
        "page_health": len(page),
        "fatal_errors": len(fatal),
        "api_errors": len(api_errors),
        "overflow_events": len(overflow),
        "missing_section_events": len(missing),
        "average_load_ms": round(sum(durations) / len(durations), 1) if durations else None,
        "latest": events[:20],
    }


def _record_revision(
    revision: int,
    *,
    status: str,
    reason: str,
    validation: dict[str, Any],
    generated_at: str,
    promoted_at: str | None = None,
) -> None:
    with ai_memory.connect() as conn:
        conn.execute(
            """
            INSERT INTO ui_revision(
              revision,status,model,reason,html_sha256,structural_score,
              validation_json,generated_at,promoted_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(revision) DO UPDATE SET
              status=excluded.status,reason=excluded.reason,
              html_sha256=excluded.html_sha256,structural_score=excluded.structural_score,
              validation_json=excluded.validation_json,promoted_at=COALESCE(excluded.promoted_at,ui_revision.promoted_at)
            """,
            (
                revision,
                status,
                MODEL,
                reason,
                str(validation.get("sha256") or ""),
                float(validation.get("structural_score") or 0),
                json.dumps(validation, ensure_ascii=False),
                generated_at,
                promoted_at,
            ),
        )


def _revision_status(revision: int, status: str, rollback_reason: str | None = None) -> None:
    with ai_memory.connect() as conn:
        if status == "verified":
            conn.execute(
                "UPDATE ui_revision SET status='verified' WHERE revision=?",
                (int(revision),),
            )
            conn.execute(
                "UPDATE ui_revision SET status='superseded',superseded_at=? WHERE revision<>? AND status='verified'",
                (_iso(), int(revision)),
            )
        elif status == "rolled_back":
            conn.execute(
                "UPDATE ui_revision SET status='rolled_back',rollback_reason=? WHERE revision=?",
                (rollback_reason, int(revision)),
            )


def _design_context(state: dict[str, Any]) -> dict[str, Any]:
    snapshot = control_room_snapshot(80)
    return {
        "version": snapshot.get("version"),
        "health": snapshot.get("health"),
        "autonomy": {
            "readiness_score": (snapshot.get("autonomy") or {}).get("readiness_score"),
            "actions": (snapshot.get("autonomy") or {}).get("actions"),
            "cycles": (snapshot.get("autonomy") or {}).get("cycles"),
            "top_learning": (snapshot.get("autonomy") or {}).get("top_learning", [])[:12],
        },
        "tasks": snapshot.get("tasks", [])[:25],
        "services": [
            {"unit": x.get("unit"), "health": x.get("health"), "status": x.get("status")}
            for x in snapshot.get("services", [])
        ],
        "downloads": snapshot.get("downloads"),
        "covers": snapshot.get("covers"),
        "database": snapshot.get("database"),
        "charts": snapshot.get("charts"),
        "incidents": (snapshot.get("incidents") or {}).get("summary"),
        "code": {
            "repair_active": bool(((snapshot.get("code") or {}).get("repair") or {}).get("active")),
            "improvement_active": bool(((snapshot.get("code") or {}).get("improvement") or {}).get("active")),
        },
        "ui_state": state,
        "telemetry": _telemetry(int(state.get("revision") or 0)),
    }


def _extract_html(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"^```(?:html)?\s*", "", value, flags=re.I)
    value = re.sub(r"\s*```$", "", value)
    start = value.casefold().find("<!doctype html")
    if start > 0:
        value = value[start:]
    end = value.casefold().rfind("</html>")
    if end >= 0:
        value = value[: end + len("</html>")]
    return value.strip()


def _ask_model(reason: str, state: dict[str, Any], current_html: str) -> str:
    required = ", ".join(REQUIRED_SECTION_IDS)
    context = json.dumps(_design_context(state), ensure_ascii=False, indent=2)[:32_000]
    current = current_html[:24_000]
    prompt = f"""Je bent de lokale Top40Archiver UI engineer. Jij bezit de HTML en CSS van de hoofdpagina op poort 8041.
Je opdracht is een professionele, extreem duidelijke Operations/AI Control Room te schrijven waarmee een beheerder ALLES kan zien wat jij doet, bewaakt, leert en aanpast.

REDEN VOOR DEZE REVISIE:
{reason}

HARDE CONTRACTREGELS:
- Geef uitsluitend EEN volledig HTML5-document, beginnend met <!doctype html> en eindigend met </html>.
- Schrijf HTML en CSS volledig zelf. GEEN JavaScript en GEEN <script>-tags; de beveiligde runtime wordt na validatie door de applicatie geïnjecteerd.
- GEEN externe URLs, fonts, afbeeldingen, CDN's, iframes, forms, event-handlers of javascript: links.
- De pagina moet mobiel, tablet en desktop bruikbaar zijn en horizontale overflow vermijden.
- Gebruik exact deze verplichte lege/structurele containers, ieder precies eenmaal: {required}.
- Gebruik daarnaast id='cr-updated' en id='cr-revision' voor de actuele tijd en UI-revisie.
- Zet de belangrijkste operationele toestand bovenaan: health, actieve taken, lopende canaries, achterstanden en fouten.
- Maak daarna alle AI-acties, services, downloads, covers, database, charts, incidenten, codewijzigingen, learning, UI-evolutie en logs gemakkelijk scanbaar.
- De container cr-raw moet aanwezig zijn zodat de volledige snapshot altijd inspecteerbaar blijft.
- Gebruik duidelijke statushiërarchie met classes good, warn en bad.
- Houd tekst Nederlands en zakelijk. Geen marketingtaal.
- De vaste runtime vervangt de inhoud van de containers; schrijf in de containers alleen zinvolle laadtekst/sectiekoppen.

LIVE CONTEXT:
{context}

HUIDIGE HTML (kan leeg zijn; verbeter aantoonbare problemen, maak geen cosmetische verandering zonder reden):
{current}
"""
    response = requests.post(
        os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate"),
        json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "keep_alive": "30m",
            "options": {"temperature": 0.25},
        },
        timeout=150,
    )
    response.raise_for_status()
    return _extract_html(str(response.json().get("response") or ""))


def _rollback(state: dict[str, Any], active: dict[str, Any], reason: str) -> dict[str, Any]:
    backup = Path(str(active.get("backup") or ""))
    revision = int(active.get("revision") or 0)
    if backup.is_file():
        shutil.copy2(backup, LIVE_HTML)
    else:
        try:
            LIVE_HTML.unlink(missing_ok=True)
        except OSError:
            pass
    action_id = int(active.get("action_id") or 0)
    if action_id:
        complete_action(
            action_id,
            success=False,
            after={"telemetry": _telemetry(revision), "rollback_reason": reason},
            result={"ui_revision": revision, "rolled_back": True},
            effect_score=-1.0,
        )
    _revision_status(revision, "rolled_back", reason)
    state["active"] = None
    state["status"] = "rolled_back"
    state["last_rollback_at"] = _iso()
    state["last_rollback_reason"] = reason
    _save_state(state)
    ai_memory.remember_event("ai_ui_rollback", f"AI Control Room revisie {revision} teruggerold", service="ui", metadata={"reason": reason})
    return {"ok": True, "action": "rolled_back", "revision": revision, "reason": reason}


def _verify_active(state: dict[str, Any]) -> dict[str, Any] | None:
    active = state.get("active")
    if not isinstance(active, dict):
        return None
    revision = int(active.get("revision") or 0)
    telemetry = _telemetry(revision)
    promoted_at = datetime.fromisoformat(str(active.get("promoted_at")))
    if promoted_at.tzinfo is None:
        promoted_at = promoted_at.replace(tzinfo=timezone.utc)
    age = _now() - promoted_at

    if telemetry["fatal_errors"] >= 2 or telemetry["missing_section_events"] >= 2:
        return _rollback(state, active, "browsertelemetrie toont herhaalde render-/sectiefouten")
    if telemetry["page_health"] >= 3 and telemetry["overflow_events"] >= max(2, telemetry["page_health"] // 2):
        return _rollback(state, active, "nieuwe layout veroorzaakt herhaald horizontaal overflow")

    verified = telemetry["page_health"] >= MIN_HEALTH_EVENTS_FOR_VERIFY and telemetry["fatal_errors"] == 0 and telemetry["missing_section_events"] == 0
    timed_verified = age >= timedelta(minutes=VERIFY_MINUTES) and telemetry["fatal_errors"] == 0 and telemetry["missing_section_events"] == 0
    if verified or timed_verified:
        action_id = int(active.get("action_id") or 0)
        if action_id:
            complete_action(
                action_id,
                success=True,
                after={"telemetry": telemetry, "verified_minutes": round(age.total_seconds() / 60, 1)},
                result={"ui_revision": revision, "verified": True},
                effect_score=1.0,
            )
        _revision_status(revision, "verified")
        state["active"] = None
        state["status"] = "verified"
        state["last_verified_at"] = _iso()
        _save_state(state)
        ai_memory.remember_event("ai_ui_verified", f"AI Control Room revisie {revision} geverifieerd", service="ui", metadata={"telemetry": telemetry})
        return {"ok": True, "action": "verified_revision", "revision": revision, "telemetry": telemetry}
    return {
        "ok": True,
        "action": "measure_ui_canary",
        "revision": revision,
        "minutes_remaining": max(0, VERIFY_MINUTES - int(age.total_seconds() // 60)),
        "telemetry": telemetry,
    }


def _reason_to_redesign(state: dict[str, Any], force: bool) -> str | None:
    if force:
        return "geforceerde lokale AI-herbouw"
    live = _read_live()
    validation = validate_control_room_html(live) if live else {"ok": False}
    if not live or not validation.get("ok"):
        return "de AI-hoofdpagina ontbreekt of voldoet niet aan het verplichte Control Room-contract"

    revision = int(state.get("revision") or 0)
    telemetry = _telemetry(revision)
    if telemetry["fatal_errors"] > 0 or telemetry["missing_section_events"] > 0:
        return "browsertelemetrie toont een renderfout of ontbrekende verplichte sectie"
    if telemetry["overflow_events"] >= 2:
        return "browsertelemetrie toont herhaald horizontaal overflow; verbeter responsiviteit"

    promoted = state.get("last_promoted_at")
    if promoted and telemetry["page_health"] >= MIN_HEALTH_EVENTS_FOR_OPTIMIZE:
        try:
            parsed = datetime.fromisoformat(str(promoted))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if _now() - parsed >= timedelta(hours=STABLE_OPTIMIZE_HOURS):
                return "periodieke AI-optimalisatie op basis van actuele taken, acties en browsertelemetrie"
        except ValueError:
            pass
    return None


def run_ui_designer(cycle_id: str, force: bool = False) -> dict[str, Any]:
    state = _load_state()
    state.setdefault("revision", 0)
    state.setdefault("status", "fallback")

    verification = _verify_active(state)
    if state.get("active"):
        return verification or {"ok": True, "action": "measure_ui_canary"}

    reason = _reason_to_redesign(state, force)
    if not reason:
        return {"ok": True, "action": "none", "revision": int(state.get("revision") or 0), "verification": verification}

    previous_attempt = state.get("last_attempt_at")
    if previous_attempt and not force:
        try:
            parsed = datetime.fromisoformat(str(previous_attempt))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if _now() - parsed < timedelta(minutes=ERROR_RETRY_MINUTES):
                return {"ok": True, "action": "cooldown", "reason": reason, "revision": int(state.get("revision") or 0)}
        except ValueError:
            pass

    current_html = _read_live()
    before_validation = validate_control_room_html(current_html) if current_html else {"ok": False, "structural_score": 0}
    next_revision = int(state.get("revision") or 0) + 1
    action_id = start_action(
        cycle_id=cycle_id,
        domain="ui",
        problem_key="ui:control_room",
        action="generate_and_promote_control_room",
        reason=reason,
        subject=f"ui-revision:{next_revision}",
        before={"revision": state.get("revision", 0), "validation": before_validation, "telemetry": _telemetry(int(state.get("revision") or 0))},
        reversible=True,
    )
    state["last_attempt_at"] = _iso()
    state["last_reason"] = reason
    _save_state(state)

    try:
        html = _ask_model(reason, state, current_html)
        validation = validate_control_room_html(html)
        generated_at = _iso()
        _record_revision(next_revision, status="candidate", reason=reason, validation=validation, generated_at=generated_at)
        if not validation.get("ok"):
            complete_action(
                action_id,
                success=False,
                after={"validation": validation},
                result={"reason": "generated_html_failed_contract"},
                effect_score=0.0,
            )
            state["status"] = "generation_rejected"
            state["last_validation"] = validation
            _save_state(state)
            return {"ok": True, "action": "candidate_rejected", "revision": next_revision, "validation": validation}

        current_sha = hashlib.sha256(current_html.encode("utf-8", "ignore")).hexdigest() if current_html else None
        if current_sha and current_sha == validation.get("sha256"):
            complete_action(action_id, success=True, after={"validation": validation}, result={"reason": "no_change_needed"}, effect_score=0.2)
            state["status"] = "unchanged"
            _save_state(state)
            return {"ok": True, "action": "no_change", "revision": int(state.get("revision") or 0)}

        CONTROL_ROOM_DIR.mkdir(parents=True, exist_ok=True)
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup = BACKUP_DIR / f"revision-{int(state.get('revision') or 0):06d}-{_now().strftime('%Y%m%dT%H%M%SZ')}.html"
        if current_html:
            backup.write_text(current_html, encoding="utf-8")
        else:
            backup.write_text("", encoding="utf-8")
        candidate_file = CONTROL_ROOM_DIR / f"revision-{next_revision:06d}.html"
        candidate_file.write_text(html, encoding="utf-8")
        shutil.copy2(candidate_file, LIVE_HTML)

        promoted_at = _iso()
        _record_revision(next_revision, status="canary", reason=reason, validation=validation, generated_at=generated_at, promoted_at=promoted_at)
        state["revision"] = next_revision
        state["status"] = "canary"
        state["model"] = MODEL
        state["last_promoted_at"] = promoted_at
        state["last_validation"] = validation
        state["active"] = {
            "revision": next_revision,
            "action_id": action_id,
            "promoted_at": promoted_at,
            "backup": str(backup),
            "candidate": str(candidate_file),
            "sha256": validation.get("sha256"),
        }
        _save_state(state)
        ai_memory.remember_event(
            "ai_ui_promoted",
            f"Lokale AI promoveerde Control Room revisie {next_revision} naar canary",
            service="ui",
            metadata={"reason": reason, "validation": validation},
        )
        return {"ok": True, "action": "promoted_ui_canary", "revision": next_revision, "reason": reason, "validation": validation}
    except Exception as exc:
        complete_action(action_id, success=False, result={"error": str(exc)[-3000:]}, effect_score=0.0)
        state["status"] = "generation_error"
        state["last_error"] = str(exc)[-3000:]
        _save_state(state)
        return {"ok": False, "action": "ui_generation_error", "error": str(exc)[-3000:]}


if __name__ == "__main__":
    import sys

    run_ui_designer("manual-ui-designer", force="--force" in sys.argv)
