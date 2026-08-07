from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DATA_DIR

STATE_PATH = DATA_DIR / "cover_state.json"


def write_cover_state(**values: Any) -> None:
    payload: dict[str, Any] = {}
    try:
        if STATE_PATH.exists():
            payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                payload = {}
    except Exception:
        payload = {}

    payload.update(values)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)
