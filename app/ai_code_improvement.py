from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone

import requests

from . import ai_memory
from .ai_code_repair import (
    _health,
    _promote,
    _rollback_active,
    _safe_touched_files,
)
from .ai_learning import complete_action, start_action
from .config import APP_DIR, DATA_DIR
from .dev_assistant import create_workspace, save_patch, validate_workspace, workspace_status

STATE_FILE = DATA_DIR / "ai" / "code-improvement-state.json"
LOOKBACK_HOURS = 6
MIN_REPEAT_ACTIONS = 5
VERIFY_MINUTES = 60
COOLDOWN_HOURS = 6

# Verbeteringen mogen alleen functionele implementatie wijzigen. De freshness-
# guard, monitoring, learning, backup- en veiligheidsbestanden staan bewust niet
# in deze mapping: een optimalisatie mag zijn eigen succescriterium niet wijzigen.
SOURCE_MAP = {
    "downloads:": ["app/downloader.py", "app/service_queue.py"],
    "download:": ["app/downloader.py", "app/service_queue.py"],
    "covers:": ["app/cover_art.py"],
    "charts:": ["app/top40.py", "app/service.py"],
    "service:top40-archiver-download.service": ["app/downloader.py", "app/service_queue.py"],
    "service:top40-archiver-cover-art.service": ["app/cover_art.py"],
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"active": None, "last_attempts": {}}


def _save(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def _mapped_sources(problem_key: str) -> list[str]:
    for prefix, files in SOURCE_MAP.items():
        if problem_key.startswith(prefix):
            return files
    return []


def _candidate() -> dict | None:
    cutoff = (_now() - timedelta(hours=LOOKBACK_HOURS)).isoformat()
    with ai_memory.connect() as conn:
        rows = conn.execute(
            """
            SELECT problem_key,action,COUNT(*) AS uses,
                   SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) AS successes,
                   MAX(started_at) AS last_seen
            FROM action_execution
            WHERE started_at>=? AND status='completed'
              AND domain IN ('service','operations','download','download_track','download_config','charts')
            GROUP BY problem_key,action
            HAVING COUNT(*)>=?
            ORDER BY COUNT(*) DESC, MAX(started_at) DESC
            LIMIT 30
            """,
            (cutoff, MIN_REPEAT_ACTIONS),
        ).fetchall()
    for row in rows:
        problem = str(row["problem_key"] or "")
        sources = _mapped_sources(problem)
        if sources:
            return {
                "problem_key": problem,
                "action": str(row["action"] or ""),
                "uses": int(row["uses"] or 0),
                "successes": int(row["successes"] or 0),
                "last_seen": row["last_seen"],
                "sources": sources,
                "lookback_hours": LOOKBACK_HOURS,
            }
    return None


def _read_sources(files: list[str]) -> str:
    parts = []
    for rel in files:
        path = APP_DIR / rel
        if path.is_file():
            parts.append(f"\n### {rel}\n{path.read_text(encoding='utf-8', errors='replace')[:40000]}\n")
    return "".join(parts)[:100000]


def _ask_model(candidate: dict) -> str:
    prompt = (
        "Je bent de Top40Archiver autonomous improvement worker. De leerdatabase toont dat dezelfde veilige "
        "herstelactie vaak nodig blijft. Verbeter de functionele broncode zodat deze herstelactie aantoonbaar "
        "minder vaak nodig wordt. Verwijder of verzwak GEEN monitoring, logging, validatie, foutdetectie, "
        "backup, downloadbeveiliging of veiligheidsregels. Wijzig alleen de meegeleverde functionele bestanden. "
        "Geef uitsluitend een minimale unified git diff; geen markdown. Als geen veilige causale verbetering uit "
        "deze informatie volgt, antwoord NO_PATCH.\n\n"
        f"PROBLEEM={candidate['problem_key']}\nHERSTELACTIE={candidate['action']}\n"
        f"AANTAL_IN_{LOOKBACK_HOURS}U={candidate['uses']}\nSUCCESVOLLE_HERSTELLINGEN={candidate['successes']}\n"
        + _read_sources(candidate["sources"])
    )
    response = requests.post(
        os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate"),
        json={"model": os.getenv("TOP40_AI_MODEL", "qwen3:4b"), "prompt": prompt, "stream": False, "keep_alive": "30m"},
        timeout=120,
    )
    response.raise_for_status()
    text = str(response.json().get("response") or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:diff)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _count_problem(problem_key: str, since: str) -> int:
    with ai_memory.connect() as conn:
        return int(conn.execute(
            "SELECT COUNT(*) FROM action_execution WHERE problem_key=? AND started_at>=?",
            (problem_key, since),
        ).fetchone()[0])


def _verify(state: dict) -> dict | None:
    active = state.get("active")
    if not isinstance(active, dict):
        return None
    promoted_at = datetime.fromisoformat(str(active["promoted_at"]))
    if promoted_at.tzinfo is None:
        promoted_at = promoted_at.replace(tzinfo=timezone.utc)
    new_uses = _count_problem(str(active["problem_key"]), promoted_at.isoformat())
    age = _now() - promoted_at

    # Twee nieuwe herstelacties tijdens de canary betekenen dat de wijziging het
    # concrete beheerprobleem niet heeft opgelost. Direct terugrollen.
    if not _health() or new_uses >= 2:
        rollback = _rollback_active(active)
        complete_action(
            int(active["action_id"]),
            success=False,
            after={"new_recovery_actions": new_uses, "health": _health()},
            result={"rollback": rollback, "reason": "improvement_not_demonstrated"},
            effect_score=-1.0,
        )
        state["active"] = None
        _save(state)
        return {"status": "rolled_back", "new_recovery_actions": new_uses, "rollback": rollback}

    if age >= timedelta(minutes=VERIFY_MINUTES):
        before_rate = float(active.get("before_rate_per_hour") or 0.0)
        after_rate = new_uses / max(age.total_seconds() / 3600.0, 0.01)
        improved = after_rate < before_rate * 0.5
        if improved:
            complete_action(
                int(active["action_id"]),
                success=True,
                after={"before_rate_per_hour": before_rate, "after_rate_per_hour": after_rate, "new_recovery_actions": new_uses},
                result={"verified_minutes": VERIFY_MINUTES, "improvement_demonstrated": True},
                effect_score=1.0,
            )
            state["active"] = None
            _save(state)
            return {"status": "verified_improved", "before_rate_per_hour": before_rate, "after_rate_per_hour": after_rate}
        rollback = _rollback_active(active)
        complete_action(
            int(active["action_id"]), success=False,
            after={"before_rate_per_hour": before_rate, "after_rate_per_hour": after_rate},
            result={"rollback": rollback, "reason": "measured_improvement_below_50_percent"},
            effect_score=-0.5,
        )
        state["active"] = None
        _save(state)
        return {"status": "rolled_back_no_measured_gain", "before_rate_per_hour": before_rate, "after_rate_per_hour": after_rate}
    return {"status": "measuring", "new_recovery_actions": new_uses, "minutes_remaining": max(0, VERIFY_MINUTES-int(age.total_seconds()//60))}


def run_code_improvement(cycle_id: str) -> dict:
    state = _load()
    verification = _verify(state)
    if state.get("active"):
        return {"ok": True, "action": "measure_existing_improvement", "verification": verification}

    candidate = _candidate()
    if not candidate:
        return {"ok": True, "action": "none", "verification": verification}
    last = state.setdefault("last_attempts", {}).get(candidate["problem_key"])
    if last:
        try:
            parsed = datetime.fromisoformat(str(last))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if _now() - parsed < timedelta(hours=COOLDOWN_HOURS):
                return {"ok": True, "action": "cooldown", "candidate": candidate}
        except ValueError:
            pass
    state["last_attempts"][candidate["problem_key"]] = _now().isoformat()
    _save(state)

    analysis_id = start_action(
        cycle_id=cycle_id,
        domain="code_improvement",
        problem_key=f"improve:{candidate['problem_key']}",
        action="analyze_repeated_recovery",
        reason="Dezelfde herstelactie blijft vaak nodig; onderzoek een causale broncodeverbetering.",
        subject=candidate["problem_key"],
        before=candidate,
    )
    try:
        patch = _ask_model(candidate)
        if patch == "NO_PATCH" or "diff --git" not in patch:
            complete_action(analysis_id, success=False, result={"reason": "no_causal_safe_improvement"}, effect_score=0.0)
            return {"ok": True, "action": "no_safe_improvement", "candidate": candidate}
        workspace = create_workspace(f"Auto improvement {candidate['problem_key']}", json.dumps(candidate, ensure_ascii=False))
        save_patch(workspace["id"], patch, "Verminder aantoonbaar terugkerend beheerwerk")
        validation = validate_workspace(workspace["id"])
        if not validation.get("ok"):
            complete_action(analysis_id, success=False, after={"workspace": workspace["id"]}, result={"validation": False}, effect_score=0.0)
            return {"ok": True, "action": "validation_failed", "workspace": workspace["id"]}
        status = workspace_status(workspace["id"])
        touched = _safe_touched_files(status)
        allowed = set(candidate["sources"])
        if not set(touched).issubset(allowed):
            complete_action(analysis_id, success=False, result={"reason": "patch_touched_non_functional_file", "files": touched}, effect_score=0.0)
            return {"ok": True, "action": "policy_rejected", "files": touched}
        complete_action(analysis_id, success=True, after={"workspace": workspace["id"]}, result={"validation": True}, effect_score=0.5)

        promote_id = start_action(
            cycle_id=cycle_id,
            domain="code_improvement",
            problem_key=f"improve:{candidate['problem_key']}",
            action="promote_measured_improvement",
            reason="Sandboxtests slagen; meet nu of het concrete herstelwerk minimaal 50% afneemt.",
            subject=candidate["problem_key"],
            before=candidate,
            reversible=True,
        )
        promotion = _promote(workspace["id"], re.sub(r"[^a-zA-Z0-9]", "", candidate["problem_key"])[:24] or "improvement")
        state["active"] = {
            "problem_key": candidate["problem_key"],
            "workspace_id": workspace["id"],
            "action_id": promote_id,
            "promoted_at": _now().isoformat(),
            "files": promotion["files"],
            "file_backup": promotion["file_backup"],
            "version_backup": promotion["version_backup"],
            "before_rate_per_hour": candidate["uses"] / LOOKBACK_HOURS,
        }
        _save(state)
        return {"ok": True, "action": "promoted_measured_canary", "candidate": candidate, "promotion": promotion}
    except Exception as exc:
        try:
            complete_action(analysis_id, success=False, result={"error": str(exc)[-2000:]}, effect_score=0.0)
        except Exception:
            pass
        return {"ok": False, "action": "improvement_error", "error": str(exc)[-2000:]}
