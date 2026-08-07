from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import ai_memory
from .config import DATA_DIR

STATE_FILES = (
    DATA_DIR / "ai" / "code-repair-state.json",
    DATA_DIR / "ai" / "code-improvement-state.json",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _save(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def handoff_official_update(version: str, sha: str) -> dict:
    """Sluit actieve lokale canaries neutraal af wanneer een officiële release ze vervangt."""
    superseded: list[dict] = []
    for path in STATE_FILES:
        state = _load(path)
        active = state.get("active")
        if not isinstance(active, dict):
            continue
        action_id = int(active.get("action_id") or 0)
        if action_id:
            with ai_memory.connect() as conn:
                row = conn.execute(
                    "SELECT result_json,status FROM action_execution WHERE id=?",
                    (action_id,),
                ).fetchone()
                if row and str(row["status"]) == "pending":
                    try:
                        result = json.loads(str(row["result_json"] or "{}"))
                    except json.JSONDecodeError:
                        result = {}
                    result["superseded_by_official_update"] = {
                        "version": version,
                        "sha": sha,
                        "at": _now(),
                    }
                    conn.execute(
                        """
                        UPDATE action_execution
                        SET status='superseded', completed_at=?, result_json=?
                        WHERE id=? AND status='pending'
                        """,
                        (_now(), json.dumps(result, ensure_ascii=False), action_id),
                    )
        superseded.append({
            "state_file": str(path),
            "action_id": action_id or None,
            "workspace_id": active.get("workspace_id"),
            "fingerprint": active.get("fingerprint") or active.get("problem_key"),
        })
        state["last_superseded"] = {
            "version": version,
            "sha": sha,
            "at": _now(),
            "active": active,
        }
        state["active"] = None
        _save(path, state)
    return {"ok": True, "version": version, "sha": sha, "superseded": superseded}


def main() -> int:
    version = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    sha = sys.argv[2] if len(sys.argv) > 2 else "unknown"
    print(json.dumps(handoff_official_update(version, sha), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
