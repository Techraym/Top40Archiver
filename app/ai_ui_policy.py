from __future__ import annotations

from pathlib import Path

# Operator contract: the product UI on :8040 is human-owned and immutable for
# Ollama/Qwen. Local AI may evolve only the monitoring/control surfaces on :8041
# and :8042, and the installation may expose at most these three top-level pages.
MAX_TOP_LEVEL_PAGES = 3
HUMAN_OWNED_PORT = 8040
AI_MUTABLE_PORTS = (8041, 8042)
TOP_LEVEL_PORTS = (8040, 8041, 8042)

# These repository paths define/render the human-owned :8040 page. Autonomous
# code-repair/improvement must never promote a patch touching them. Prefixes are
# used for the static/template trees because they may contain many assets.
PORT_8040_PROTECTED_FILES = {
    "app/main.py",
    "app/dashboard.py",
}
PORT_8040_PROTECTED_PREFIXES = (
    "app/static/",
    "app/templates/",
)

# AI-owned UI output is data, not production source code. The designer is allowed
# to write only these bounded page slots. :8040 deliberately has no AI slot.
AI_PAGE_SLOTS = {
    8041: "control_room",
    8042: "log_control",
}


def is_8040_protected_path(path: str | Path) -> bool:
    value = str(path).replace("\\", "/").lstrip("./")
    return value in PORT_8040_PROTECTED_FILES or any(
        value.startswith(prefix) for prefix in PORT_8040_PROTECTED_PREFIXES
    )


def assert_ai_source_mutation_allowed(path: str | Path) -> None:
    if is_8040_protected_path(path):
        raise ValueError(
            f"Qwen/Ollama mag de menselijke :8040-pagina nooit wijzigen: {path}"
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
    }
