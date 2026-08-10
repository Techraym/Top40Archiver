from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import requests

from .ai_control_room import (
    CONTROL_ROOM_DIR,
    LIVE_HTML,
    STATE_FILE,
    validate_control_room_html,
)

MODEL = os.getenv("TOP40_AI_MODEL", "qwen3:4b")
BACKUP_DIR = CONTROL_ROOM_DIR / "backups"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state() -> dict:
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def save_state(state: dict) -> None:
    CONTROL_ROOM_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(STATE_FILE)


def read_html() -> str:
    return LIVE_HTML.read_text(encoding="utf-8")


def extract_style(html: str) -> str:
    match = re.search(r"<style>(.*?)</style>", html, flags=re.I | re.S)
    return match.group(1).strip() if match else ""


def replace_style(html: str, css: str) -> str:
    if re.search(r"<style>.*?</style>", html, flags=re.I | re.S):
        return re.sub(
            r"<style>.*?</style>",
            "<style>\n" + css.strip() + "\n</style>",
            html,
            count=1,
            flags=re.I | re.S,
        )

    return html.replace(
        "</head>",
        "<style>\n" + css.strip() + "\n</style>\n</head>",
        1,
    )


def css_safe(css: str) -> tuple[bool, str]:
    value = str(css or "").strip()

    if value.startswith("```"):
        value = re.sub(r"^```(?:css)?\s*", "", value, flags=re.I)
        value = re.sub(r"\s*```$", "", value)

    forbidden = [
        "<",
        ">",
        "@import",
        "javascript:",
        "url(http",
        "url(https",
        "expression(",
        "behavior:",
    ]

    lowered = value.casefold()

    for marker in forbidden:
        if marker in lowered:
            return False, value

    if len(value) < 200:
        return False, value

    if len(value) > 14000:
        return False, value

    return True, value


def ask_qwen(current_css: str, guidance: str) -> str:
    compact_css = current_css[:6500]
    compact_guidance = str(guidance or "")[:1200]

    prompt = f"""Je verbetert uitsluitend de CSS van de Top40Archiver AI Control Room op poort 8041.

DOEL:
- menselijke, moderne uitstraling
- lichte rustige kleuren
- professioneel dashboard
- duidelijke navigatie
- goede leesbaarheid
- mobiel en desktop
- geen horizontale overflow

BELANGRIJKE REGELS:
- geef ALLEEN CSS terug
- GEEN HTML
- GEEN Markdown
- GEEN uitleg
- GEEN externe URLs
- GEEN imports
- behoud bestaande class- en id-selectors
- maak alleen nuttige visuele verbeteringen
- maximaal compacte CSS

Operatorrichtlijn:
{compact_guidance}

Huidige CSS:
{compact_css}

Geef nu alleen de verbeterde CSS."""

    response = requests.post(
        os.getenv(
            "OLLAMA_URL",
            "http://127.0.0.1:11434/api/generate",
        ),
        json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "keep_alive": "2h",
            "options": {
                "temperature": 0.15,
                "num_ctx": 2048,
                "num_predict": 350,
            },
        },
        timeout=60,
    )
    response.raise_for_status()

    data = response.json()
    return str(data.get("response") or "").strip()


def run_css_revision() -> dict:
    state = load_state()
    state.setdefault("revision", 0)

    current_html = read_html()
    current_css = extract_style(current_html)

    state["last_attempt_at"] = now_iso()
    state["last_reason"] = "css-only-qwen-refinement"
    state["status"] = "css_generation"
    state["last_error"] = None
    save_state(state)

    try:
        css = ask_qwen(
            current_css,
            state.get("operator_guidance") or "",
        )
    except Exception as exc:
        state["status"] = "css_generation_error"
        state["last_error"] = str(exc)[-1000:]
        save_state(state)
        return {
            "ok": False,
            "action": "css_generation_error",
            "error": str(exc),
        }

    ok, css = css_safe(css)

    if not ok:
        state["status"] = "css_rejected"
        state["last_error"] = "Qwen CSS output rejected by safety validation"
        save_state(state)
        return {
            "ok": False,
            "action": "css_rejected",
            "bytes": len(css.encode("utf-8", "ignore")),
        }

    candidate = replace_style(current_html, css)
    validation = validate_control_room_html(candidate)

    if not validation.get("ok"):
        state["status"] = "css_candidate_invalid"
        state["last_error"] = json.dumps(
            validation,
            ensure_ascii=False,
        )[-1000:]
        save_state(state)
        return {
            "ok": False,
            "action": "candidate_invalid",
            "validation": validation,
        }

    old_sha = hashlib.sha256(
        current_html.encode("utf-8", "ignore")
    ).hexdigest()

    new_sha = validation.get("sha256")

    if old_sha == new_sha:
        state["status"] = "unchanged"
        state["last_error"] = None
        save_state(state)
        return {
            "ok": True,
            "action": "unchanged",
            "revision": state["revision"],
        }

    next_revision = int(state.get("revision") or 0) + 1

    CONTROL_ROOM_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    backup = BACKUP_DIR / (
        f"css-revision-{int(state.get('revision') or 0):06d}-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.html"
    )

    backup.write_text(current_html, encoding="utf-8")

    candidate_file = CONTROL_ROOM_DIR / (
        f"revision-{next_revision:06d}.html"
    )

    candidate_file.write_text(candidate, encoding="utf-8")

    shutil.copy2(candidate_file, LIVE_HTML)

    state["revision"] = next_revision
    state["status"] = "css_canary"
    state["model"] = MODEL
    state["last_promoted_at"] = now_iso()
    state["last_error"] = None
    state["last_validation"] = validation
    state["active"] = {
        "revision": next_revision,
        "type": "css-only",
        "backup": str(backup),
        "candidate": str(candidate_file),
        "sha256": new_sha,
        "promoted_at": state["last_promoted_at"],
    }

    save_state(state)

    return {
        "ok": True,
        "action": "css_promoted",
        "revision": next_revision,
        "validation": validation,
        "css_bytes": len(css.encode("utf-8")),
    }


if __name__ == "__main__":
    print(
        json.dumps(
            run_css_revision(),
            ensure_ascii=False,
        ),
        flush=True,
    )
