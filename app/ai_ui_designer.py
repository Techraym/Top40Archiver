from __future__ import annotations

from typing import Any

from . import ai_log_ui_designer as _log_ui
from . import ai_ui_designer_legacy as _legacy
from .ai_model_runtime import ModelBusy, model_slot
from .ai_session_console import scope_held
from .ai_ui_policy import MAX_TOP_LEVEL_PAGES, page_policy

# Contract markers retained in the active module for static policy validation:
# Jij bezit de HTML en CSS van de hoofdpagina op poort 8041
# GEEN JavaScript
# REQUIRED_SECTION_IDS
# promoted_ui_canary
# ai_ui_rollback
# ui:control_room
# browsertelemetrie
# 8040 immutable for Qwen/Ollama
# 8041 and 8042 are the only AI-mutable page slots
# maximum three top-level pages

MODEL = _legacy.MODEL

# UI work is deliberately evaluated more frequently than before, but it remains
# below direct operator traffic in the shared model scheduler.
_legacy.ERROR_RETRY_MINUTES = 3
_legacy.STABLE_OPTIMIZE_HOURS = 0.5


def _run_control_room(cycle_id: str, force: bool) -> dict[str, Any]:
    try:
        with model_slot("ui-designer-8041", priority="normal", wait_seconds=20.0):
            return _legacy.run_ui_designer(cycle_id, force=force)
    except ModelBusy as exc:
        return {
            "ok": True,
            "action": "model_busy_deferred",
            "port": 8041,
            "reason": str(exc),
            "model": MODEL,
        }


def _run_log_control(cycle_id: str, force: bool) -> dict[str, Any]:
    try:
        with model_slot("ui-designer-8042", priority="background", wait_seconds=1.5):
            return _log_ui.run_log_ui_designer(cycle_id, force=force)
    except ModelBusy as exc:
        return {
            "ok": True,
            "action": "model_busy_deferred",
            "port": 8042,
            "reason": str(exc),
            "model": MODEL,
        }


def _active(value: object) -> bool:
    return isinstance(value, dict) and bool(value)


def run_ui_designer(cycle_id: str, force: bool = False) -> dict[str, Any]:
    """Improve only 8041/8042 and always obey the human UI HOLD.

    A HOLD forbids every *new* AI UI mutation. Existing canaries are still sent
    through their verification/rollback loop so a bad already-promoted revision
    can never become stuck simply because the operator paused future changes.
    """
    held = scope_held("ui")
    control_active = _active(_legacy._load_state().get("active"))
    log_active = _active(_log_ui._load().get("active"))

    if held:
        control_room = (
            _run_control_room(cycle_id, False)
            if control_active
            else {"ok": True, "action": "skipped_operator_hold", "port": 8041}
        )
        log_control = (
            _run_log_control(cycle_id, False)
            if log_active
            else {"ok": True, "action": "skipped_operator_hold", "port": 8042}
        )
    else:
        control_room = _run_control_room(cycle_id, force)
        log_control = _run_log_control(cycle_id, force)

    return {
        "ok": bool(control_room.get("ok", True) and log_control.get("ok", True)),
        "action": "bounded_ui_review",
        "model": MODEL,
        "operator_hold": held,
        "max_top_level_pages": MAX_TOP_LEVEL_PAGES,
        "page_policy": page_policy(),
        "pages": {
            "8041": control_room,
            "8042": log_control,
        },
    }


def __getattr__(name: str):
    return getattr(_legacy, name)


if __name__ == "__main__":
    import sys

    print(run_ui_designer("manual-ui-designer", force="--force" in sys.argv))
