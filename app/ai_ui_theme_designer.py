from __future__ import annotations

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

MARKER_START = "/* AI_THEME_START */"
MARKER_END = "/* AI_THEME_END */"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_state():
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(state):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(STATE_FILE)


def valid_hex(value, fallback):
    value = str(value or "").strip()

    if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        return value.lower()

    return fallback


def clamp_int(value, low, high, fallback):
    try:
        return max(low, min(high, int(value)))
    except Exception:
        return fallback


def ask_qwen():
    themes = {
        "A": {
            "accent": "#52705d",
            "background": "#f5f7f3",
            "surface": "#ffffff",
            "soft": "#edf1eb",
            "text": "#20241f",
            "muted": "#70776d",
            "radius": 18,
            "gap": 14,
        },
        "B": {
            "accent": "#4f6d7a",
            "background": "#f4f7f8",
            "surface": "#ffffff",
            "soft": "#eaf0f2",
            "text": "#20262a",
            "muted": "#69777d",
            "radius": 20,
            "gap": 16,
        },
        "C": {
            "accent": "#6b6254",
            "background": "#f8f6f2",
            "surface": "#ffffff",
            "soft": "#f0ece5",
            "text": "#292620",
            "muted": "#777065",
            "radius": 18,
            "gap": 15,
        },
        "D": {
            "accent": "#596b78",
            "background": "#f6f7f8",
            "surface": "#ffffff",
            "soft": "#eceff2",
            "text": "#22272b",
            "muted": "#6e767c",
            "radius": 22,
            "gap": 14,
        },
    }

    response = requests.post(
        "http://127.0.0.1:11434/api/generate",
        json={
            "model": MODEL,
            "prompt": (
                "Kies het beste lichte, moderne, menselijke professionele "
                "dashboardthema. Antwoord uitsluitend met A, B, C of D."
            ),
            "stream": False,
            "think": False,
            "keep_alive": "2h",
            "options": {
                "temperature": 0.1,
                "num_ctx": 256,
                "num_predict": 2,
            },
        },
        timeout=20,
    )

    response.raise_for_status()

    raw = str(response.json().get("response") or "").strip().upper()

    match = re.search(r"[ABCD]", raw)

    if not match:
        raise RuntimeError("Geen geldige themakeuze: " + repr(raw))

    choice = match.group(0)
    theme = themes[choice].copy()
    theme["choice"] = choice

    return theme

def theme_css(theme):
    accent = valid_hex(theme.get("accent"), "#52705d")
    background = valid_hex(theme.get("background"), "#f5f7f3")
    surface = valid_hex(theme.get("surface"), "#ffffff")
    soft = valid_hex(theme.get("soft"), "#edf1eb")
    text = valid_hex(theme.get("text"), "#20241f")
    muted = valid_hex(theme.get("muted"), "#70776d")

    radius = clamp_int(theme.get("radius"), 14, 24, 18)
    gap = clamp_int(theme.get("gap"), 10, 20, 14)

    return f"""
{MARKER_START}

:root {{
  --bg:{background};
  --surface:{surface};
  --soft:{soft};
  --text:{text};
  --muted:{muted};
  --accent:{accent};
}}

.grid {{
  gap:{gap}px;
}}

.panel {{
  border-radius:{radius}px;
}}

.hero {{
  border-radius:{min(26, radius + 4)}px;
}}

.nav {{
  border-radius:{max(12, radius - 2)}px;
}}

.nav a {{
  border-radius:{max(9, radius - 7)}px;
}}

.panel,
.hero {{
  transition:
    box-shadow .18s ease,
    border-color .18s ease,
    transform .18s ease;
}}

.nav a:hover {{
  transform:translateY(-1px);
}}

{MARKER_END}
""".strip()


def inject_theme(html, css):
    block = re.compile(
        re.escape(MARKER_START)
        + r".*?"
        + re.escape(MARKER_END),
        flags=re.S,
    )

    if block.search(html):
        return block.sub(css, html, count=1)

    pos = html.lower().find("</style>")

    if pos < 0:
        raise RuntimeError("Geen style-blok in bootstrap HTML")

    return html[:pos] + "\n" + css + "\n" + html[pos:]


def run():
    state = load_state()

    state["last_attempt_at"] = now_iso()
    state["last_reason"] = "qwen-theme-token-refinement"
    state["status"] = "theme_generation"
    state["last_error"] = None
    save_state(state)

    try:
        theme = ask_qwen()
    except Exception as exc:
        state["status"] = "theme_generation_error"
        state["last_error"] = str(exc)[-1000:]
        save_state(state)

        return {
            "ok": False,
            "action": "theme_generation_error",
            "error": str(exc),
        }

    current = LIVE_HTML.read_text(encoding="utf-8")
    candidate = inject_theme(current, theme_css(theme))

    validation = validate_control_room_html(candidate)

    if not validation.get("ok"):
        state["status"] = "theme_rejected"
        state["last_error"] = json.dumps(
            validation,
            ensure_ascii=False,
        )[-1000:]
        save_state(state)

        return {
            "ok": False,
            "action": "theme_rejected",
            "validation": validation,
        }

    revision = int(state.get("revision") or 0) + 1

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    backup = BACKUP_DIR / (
        f"theme-before-{revision:06d}-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.html"
    )

    backup.write_text(current, encoding="utf-8")

    candidate_file = CONTROL_ROOM_DIR / f"revision-{revision:06d}.html"
    candidate_file.write_text(candidate, encoding="utf-8")

    shutil.copy2(candidate_file, LIVE_HTML)

    state["revision"] = revision
    state["status"] = "theme_canary"
    state["model"] = MODEL
    state["last_promoted_at"] = now_iso()
    state["last_error"] = None
    state["last_validation"] = validation
    state["last_theme"] = theme
    state["active"] = {
        "revision": revision,
        "type": "qwen-theme",
        "backup": str(backup),
        "candidate": str(candidate_file),
        "promoted_at": state["last_promoted_at"],
    }

    save_state(state)

    return {
        "ok": True,
        "action": "theme_promoted",
        "revision": revision,
        "theme": theme,
        "validation": validation,
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False), flush=True)
