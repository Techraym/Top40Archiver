from __future__ import annotations

from pathlib import Path

# Operator contract: the product UI on :8040 is human-owned and immutable for
# Ollama/Qwen. Local AI may evolve only the monitoring/control surfaces on :8041
# and :8042, and the installation may expose at most these three top-level pages.
MAX_TOP_LEVEL_PAGES = 3
HUMAN_OWNED_PORT = 8040
AI_MUTABLE_PORTS = (8041, 8042)
TOP_LEVEL_PORTS = (8040, 8041, 8042)

PORT_8040_PROTECTED_FILES = {
    "app/main.py",
    "app/dashboard.py",
}
PORT_8040_PROTECTED_PREFIXES = (
    "app/static/",
    "app/templates/",
)

# These files implement the boundary itself, trusted browser runtimes and human
# override/rollback controls. Autonomous Qwen code-repair is not allowed to edit
# the mechanism that constrains Qwen. Release updates may change them only via the
# normal GitHub/CI/update path.
AI_UI_POLICY_IMMUTABLE_FILES = {
    "app/ai_ui_policy.py",
    "app/ai_ui_admin.py",
    "app/ai_ui_operator_overlay.py",
    "app/ai_log_control.py",
    "app/ai_log_ui_designer.py",
    "app/ai_ui_designer.py",
    "app/ai_control_room.py",
    "app/ai_sidecar.py",
    "app/ai_platform.py",
    "app/ai_session_console.py",
    "app/log_reader_service.py",
}

# AI-owned UI output is data, not production source code. The designer is allowed
# to write only these bounded page slots. :8040 deliberately has no AI slot.
AI_PAGE_SLOTS = {
    8041: "control_room",
    8042: "log_control",
}


def _normalized(path: str | Path) -> str:
    return str(path).replace("\\", "/").lstrip("./")


def is_8040_protected_path(path: str | Path) -> bool:
    value = _normalized(path)
    return value in PORT_8040_PROTECTED_FILES or any(
        value.startswith(prefix) for prefix in PORT_8040_PROTECTED_PREFIXES
    )


def is_ai_ui_policy_immutable_path(path: str | Path) -> bool:
    return _normalized(path) in AI_UI_POLICY_IMMUTABLE_FILES


def assert_ai_source_mutation_allowed(path: str | Path) -> None:
    if is_8040_protected_path(path):
        raise ValueError(
            f"Qwen/Ollama mag de menselijke :8040-pagina nooit wijzigen: {path}"
        )
    if is_ai_ui_policy_immutable_path(path):
        raise ValueError(
            f"Qwen/Ollama mag zijn eigen UI-beveiligings- of operatorcontrolecode niet wijzigen: {path}"
        )


def page_policy() -> dict:
    return {
        "max_top_level_pages": MAX_TOP_LEVEL_PAGES,
        "ports": list(TOP_LEVEL_PORTS),
        "human_owned_immutable": [HUMAN_OWNED_PORT],
        "ai_mutable": list(AI_MUTABLE_PORTS),
        "ai_page_slots": dict(AI_PAGE_SLOTS),
        "operator_can_hold_ui": True,
        "operator_can_correct_ui": True,
        "operator_can_rollback_ui": True,
        "ai_can_create_extra_top_level_pages": False,
        "ai_can_modify_its_ui_policy": False,
        "trusted_ui_runtime_ai_mutable": False,
    }
