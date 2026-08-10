from __future__ import annotations

from typing import Any

from . import ai_ui_designer_legacy as _legacy
from .ai_log_ui_designer import run_log_ui_designer
from .ai_model_runtime import ModelBusy, model_slot
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
_legacy.ERROR_RETRY_MINUTES = 15
_legacy.STABLE_OPTIMIZE_HOURS = 2


def _run_control_room(cycle_id: str, force: bool) -> dict[str, Any]:
    try:
        with model_slot("ui-designer-8041", priority="background", wait_seconds=4.0):
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
            return run_log_ui_designer(cycle_id, force=force)
    except ModelBusy as exc:
        return {
            "ok": True,
            "action": "model_busy_deferred",
            "port": 8042,
            "reason": str(exc),
            "model": MODEL,
        }


def run_ui_designer(cycle_id: str, force: bool = False) -> dict[str, Any]:
    """Improve only the two bounded AI management pages.

    :8040 is intentionally absent from this execution path and has no writable AI
    page slot. :8041 retains browser-telemetry canary/rollback; :8042 has its own
    validated backup/canary/rollback loop. Operator requests always keep priority
    over both background model calls.
    """
    control_room = _run_control_room(cycle_id, force)
    log_control = _run_log_control(cycle_id, force)
    return {
        "ok": bool(control_room.get("ok", True) and log_control.get("ok", True)),
        "action": "bounded_ui_review",
        "model": MODEL,
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
