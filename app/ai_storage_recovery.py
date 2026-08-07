from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any

from .ai_learning import record_action
from .config import DATA_DIR


def _disk() -> dict[str, Any]:
    usage = shutil.disk_usage(DATA_DIR if DATA_DIR.exists() else "/")
    free_pct = (usage.free / usage.total * 100.0) if usage.total else 0.0
    return {
        "free_percent": round(free_pct, 2),
        "free_gb": round(usage.free / (1024**3), 2),
        "total_gb": round(usage.total / (1024**3), 2),
    }


def _safe_action(action: str) -> dict:
    completed = subprocess.run(
        ["/usr/local/sbin/top40-safe-action", action],
        capture_output=True,
        text=True,
        timeout=100,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {
            "ok": False,
            "action": action,
            "returncode": completed.returncode,
            "stderr": completed.stderr[-1000:],
        }
    payload.setdefault("returncode", completed.returncode)
    return payload


def run_storage_recovery(cycle_id: str) -> dict:
    before = _disk()
    actions: list[dict] = []
    free_before = float(before.get("free_percent") or 0.0)

    if free_before < 10.0:
        result = _safe_action("cleanup_stale_download_temp")
        after = _disk()
        free_after = float(after.get("free_percent") or 0.0)
        reclaimed = max(0.0, free_after - free_before)
        success = bool(result.get("ok"))
        action_id = record_action(
            cycle_id=cycle_id,
            domain="storage",
            problem_key="storage:low_disk_space",
            action="cleanup_stale_download_temp",
            reason=(
                f"Vrije schijfruimte was {free_before:.2f}%. Alleen oude tijdelijke "
                "onvoltooide downloadbestanden mogen worden opgeschoond; gedownloade audio niet."
            ),
            subject=str(DATA_DIR / "download-temp"),
            before=before,
            after=after,
            result=result,
            success=success,
            effect_score=min(1.0, 0.4 + reclaimed / 5.0) if success else 0.0,
            operator_needed=(free_after < 5.0),
            reversible=False,
        )
        actions.append({
            "action_id": action_id,
            "action": "cleanup_stale_download_temp",
            "ok": success,
            "before": before,
            "after": after,
            "result": result,
            "audio_deleted": False,
        })
    else:
        after = before

    critical = float(after.get("free_percent") or 0.0) < 5.0
    return {
        "ok": not critical,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "before": before,
        "after": after,
        "actions": actions,
        "operator_needed": 1 if critical else 0,
        "policy": {
            "downloaded_audio_delete_allowed": False,
            "automatic_cleanup_scope": "stale partial download-temp files only",
            "critical_free_percent": 5.0,
            "cleanup_trigger_percent": 10.0,
        },
    }
