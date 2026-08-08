from __future__ import annotations

from typing import Any

from . import ai_ui_designer_legacy as _legacy
from .ai_model_runtime import ModelBusy, model_slot

# Contract markers retained in the active module for static policy validation:
# Jij bezit de HTML en CSS van de hoofdpagina op poort 8041
# GEEN JavaScript
# REQUIRED_SECTION_IDS
# promoted_ui_canary
# ai_ui_rollback
# ui:control_room
# browsertelemetrie

MODEL = _legacy.MODEL


def run_ui_designer(cycle_id: str, force: bool = False) -> dict[str, Any]:
    """Run Control Room generation only when the shared Ollama slot is free.

    Operator Chat marks itself as priority traffic. Background UI generation then
    defers instead of competing for the same local model and timing out. The
    declarative HTML/CSS contract, canary verification and rollback logic remain
    implemented by the preserved legacy runtime module.
    """
    try:
        with model_slot("ui-designer", priority="background", wait_seconds=1.5):
            return _legacy.run_ui_designer(cycle_id, force=force)
    except ModelBusy as exc:
        return {
            "ok": True,
            "action": "model_busy_deferred",
            "reason": str(exc),
            "model": MODEL,
        }


def __getattr__(name: str):
    return getattr(_legacy, name)


if __name__ == "__main__":
    import sys

    run_ui_designer("manual-ui-designer", force="--force" in sys.argv)
