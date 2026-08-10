from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import ai_ui_designer_legacy as control_ui
from .ai_log_control import STATE_FILE as LOG_STATE_FILE
from .ai_log_ui_designer import manual_rollback as rollback_log_ui
from .ai_session_console import acknowledge_guidance, close_guidance, create_operator_guidance
from .ai_ui_policy import page_policy

router = APIRouter()


class GuidanceIn(BaseModel):
    instruction: str = Field(min_length=2, max_length=4000)
    hold: bool = False


class RollbackIn(BaseModel):
    reason: str = Field(default="menselijke operator rollback", min_length=2, max_length=1000)


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _save_control_state(state: dict[str, Any]) -> None:
    control_ui.CONTROL_ROOM_DIR.mkdir(parents=True, exist_ok=True)
    tmp = control_ui.STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(control_ui.STATE_FILE)


def _rollback_control_room(reason: str) -> dict[str, Any]:
    state = control_ui._load_state()
    active = state.get("active")
    if isinstance(active, dict):
        return control_ui._rollback(state, active, reason)

    backups = sorted(control_ui.BACKUP_DIR.glob("*.html"), reverse=True) if control_ui.BACKUP_DIR.is_dir() else []
    if not backups:
        return {"ok": False, "action": "rollback_unavailable", "port": 8041, "reason": reason}
    shutil.copy2(backups[0], control_ui.LIVE_HTML)
    state["status"] = "operator_rollback"
    state["last_rollback_reason"] = reason
    state["active"] = None
    _save_control_state(state)
    return {
        "ok": True,
        "action": "operator_rollback",
        "port": 8041,
        "backup": str(backups[0]),
        "reason": reason,
    }


@router.get("/api/ai/ui-policy")
def ui_policy():
    return {
        "ok": True,
        **page_policy(),
        "control_room_state": _json(control_ui.STATE_FILE),
        "log_control_state": _json(LOG_STATE_FILE),
    }


@router.post("/api/ai/ui-guidance")
def ui_guidance(payload: GuidanceIn):
    item = create_operator_guidance(
        payload.instruction,
        scope="ui",
        mode="hold" if payload.hold else "guidance",
    )
    return {
        "ok": True,
        "guidance": item,
        "qwen_acknowledgement": acknowledge_guidance(item),
        "effect": "Nieuwe AI-UI-mutaties gepauzeerd" if payload.hold else "Correctie wordt bij de volgende UI-beoordeling toegepast",
    }


@router.post("/api/ai/ui-guidance/{guidance_id}/close")
def ui_guidance_close(guidance_id: int):
    try:
        return close_guidance(guidance_id)
    except KeyError as exc:
        raise HTTPException(404, "UI-richtlijn niet gevonden") from exc


@router.post("/api/ai/ui-rollback/{port}")
def ui_rollback(port: int, payload: RollbackIn):
    if port == 8041:
        return _rollback_control_room(payload.reason)
    if port == 8042:
        return rollback_log_ui(payload.reason)
    if port == 8040:
        raise HTTPException(403, "8040 is menselijk beheerd en heeft geen AI-revisies om terug te rollen")
    raise HTTPException(404, "Alleen 8041 en 8042 zijn AI-UI-slots")
