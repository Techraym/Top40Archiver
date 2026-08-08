from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import ai_code_improvement_legacy as _legacy
from .ai_model_runtime import ModelBusy, model_slot
from .config import APP_DIR
from .db import connect as app_connect

DOWNLOAD_SOURCES = [
    "app/download_manager.py",
    "app/download_manager_entry.py",
    "app/download_matching.py",
    "app/download_db.py",
    "app/ai_recovery.py",
]
INEFFECTIVE_COOLDOWN_MINUTES = 30
MAX_MODEL_SOURCE_BYTES = 30_000

# Point autonomous improvement at the current multi-source architecture instead
# of the pre-1.16 downloader/service_queue implementation.
_legacy.SOURCE_MAP = {
    **_legacy.SOURCE_MAP,
    "downloads:": DOWNLOAD_SOURCES,
    "download:": DOWNLOAD_SOURCES,
    "service:top40-download-manager.service": DOWNLOAD_SOURCES,
}
_legacy.SOURCE_MAP.pop("service:top40-archiver-download.service", None)
_ORIGINAL_CANDIDATE = _legacy._candidate


def _download_downstream_metrics(cutoff: str) -> dict[str, int]:
    try:
        with app_connect() as con:
            completed_jobs = int(con.execute(
                "SELECT COUNT(*) FROM download_jobs WHERE status='completed' AND updated_at>=?",
                (cutoff,),
            ).fetchone()[0])
            successful_attempts = int(con.execute(
                "SELECT COUNT(*) FROM download_provider_attempts WHERE success=1 AND completed_at>=?",
                (cutoff,),
            ).fetchone()[0])
            attempts = int(con.execute(
                "SELECT COUNT(*) FROM download_provider_attempts WHERE completed_at>=?",
                (cutoff,),
            ).fetchone()[0])
            waiting_retry = int(con.execute(
                "SELECT COUNT(*) FROM download_jobs WHERE status='waiting_retry'",
            ).fetchone()[0])
        return {
            "completed_jobs": completed_jobs,
            "successful_provider_attempts": successful_attempts,
            "provider_attempts": attempts,
            "waiting_retry_now": waiting_retry,
        }
    except Exception:
        return {
            "completed_jobs": 0,
            "successful_provider_attempts": 0,
            "provider_attempts": 0,
            "waiting_retry_now": 0,
        }


def _candidate() -> dict | None:
    candidate = _ORIGINAL_CANDIDATE()
    if not candidate:
        return None
    problem = str(candidate.get("problem_key") or "")
    if not (problem.startswith("download:") or problem.startswith("downloads:") or problem == "service:top40-download-manager.service"):
        return candidate

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=_legacy.LOOKBACK_HOURS)).isoformat()
    metrics = _download_downstream_metrics(cutoff)
    administrative = int(candidate.get("successes") or 0)
    downstream = max(metrics["completed_jobs"], metrics["successful_provider_attempts"])
    candidate["administrative_successes"] = administrative
    candidate["successes"] = downstream
    candidate["downstream_successes"] = downstream
    candidate["downstream_metrics"] = metrics
    candidate["downstream_effective"] = downstream > 0
    candidate["success_semantics"] = "completed download job/provider attempt; requeue alone is not success"
    return candidate


def _read_sources(files: list[str]) -> str:
    parts: list[str] = []
    budget = MAX_MODEL_SOURCE_BYTES
    for rel in files:
        if budget <= 0:
            break
        path = APP_DIR / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        take = min(7_000, budget)
        piece = f"\n### {rel}\n{text[:take]}\n"
        parts.append(piece)
        budget -= len(piece.encode("utf-8"))
    return "".join(parts)[:MAX_MODEL_SOURCE_BYTES]


def _relax_cooldown_for_proven_ineffective_recovery(candidate: dict | None) -> None:
    if not candidate:
        return
    if bool(candidate.get("downstream_effective")) or int(candidate.get("uses") or 0) < _legacy.MIN_REPEAT_ACTIONS:
        return
    state = _legacy._load()
    last_attempts = state.setdefault("last_attempts", {})
    raw = last_attempts.get(candidate["problem_key"])
    if not raw:
        return
    try:
        parsed = datetime.fromisoformat(str(raw))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        parsed = datetime.min.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - parsed >= timedelta(minutes=INEFFECTIVE_COOLDOWN_MINUTES):
        last_attempts.pop(candidate["problem_key"], None)
        _legacy._save(state)


# Patch legacy globals so its existing tested sandbox/promotion/rollback contract
# remains intact while candidate selection uses the current downloader.
_legacy._candidate = _candidate
_legacy._read_sources = _read_sources

SOURCE_MAP = _legacy.SOURCE_MAP
LOOKBACK_HOURS = _legacy.LOOKBACK_HOURS
MIN_REPEAT_ACTIONS = _legacy.MIN_REPEAT_ACTIONS
VERIFY_MINUTES = _legacy.VERIFY_MINUTES
COOLDOWN_HOURS = _legacy.COOLDOWN_HOURS


def run_code_improvement(cycle_id: str) -> dict[str, Any]:
    candidate = _candidate()
    _relax_cooldown_for_proven_ineffective_recovery(candidate)
    try:
        with model_slot("code-improvement", priority="background", wait_seconds=1.5):
            result = _legacy.run_code_improvement(cycle_id)
    except ModelBusy as exc:
        return {
            "ok": True,
            "action": "model_busy_deferred",
            "reason": str(exc),
            "candidate": candidate,
        }
    if isinstance(result, dict) and candidate and str(candidate.get("problem_key")) == str((result.get("candidate") or {}).get("problem_key")):
        result["candidate"] = candidate
    return result


def __getattr__(name: str):
    return getattr(_legacy, name)


if __name__ == "__main__":
    print(run_code_improvement("manual-code-improvement"))
