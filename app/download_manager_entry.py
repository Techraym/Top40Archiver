from __future__ import annotations

import json
import logging
import time
from typing import Any

from . import download_manager
from .db import connect, now_iso


LOGGER = logging.getLogger("top40.download_manager")
INTERRUPTED_STATUSES = ("searching", "downloading", "validating", "processing")
CANDIDATE_ONLY_ERRORS = {"drm", "unavailable"}


def _event(event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    payload = {"event": event, "at": now_iso(), **fields}
    LOGGER.log(level, json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def recover_interrupted_jobs() -> int:
    """Requeue jobs that belonged to a previous manager process.

    This runs once before workers start. At that point no job from the old process
    can still be active. Existing audio remains protected by download_manager's
    create-only final write, so recovery never overwrites downloaded files.
    """
    stamp = now_iso()
    with connect() as con:
        rows = con.execute(
            """
            SELECT id,track_id,status
            FROM download_jobs
            WHERE status IN ('searching','downloading','validating','processing')
            ORDER BY id
            """
        ).fetchall()
        if not rows:
            return 0

        con.execute(
            """
            UPDATE download_jobs
            SET status='queued',
                started_at=NULL,
                next_attempt_at=NULL,
                preferred_provider=NULL,
                providers_tried_json='[]',
                error='recovered_after_manager_restart',
                updated_at=?
            WHERE status IN ('searching','downloading','validating','processing')
            """,
            (stamp,),
        )
        track_ids = [int(row["track_id"]) for row in rows]
        placeholders = ",".join("?" for _ in track_ids)
        con.execute(
            f"""
            UPDATE tracks
            SET download_status='pending',
                error_message='Download hervat na manager-herstart',
                updated_at=?
            WHERE id IN ({placeholders})
              AND download_status NOT IN ('downloaded','unavailable')
            """,
            (stamp, *track_ids),
        )

    _event(
        "interrupted_jobs_requeued",
        count=len(rows),
        statuses={status: sum(1 for row in rows if row["status"] == status) for status in INTERRUPTED_STATUSES},
        sample_track_ids=[int(row["track_id"]) for row in rows[:20]],
    )
    return len(rows)


def _install_runtime_guards() -> None:
    original_update_provider_runtime = download_manager.update_provider_runtime

    def bounded_provider_runtime(provider: str, *, success: bool, error_category: str | None = None, **kwargs: Any):
        if not success and str(error_category or "") in CANDIDATE_ONLY_ERRORS:
            _event(
                "candidate_error_not_provider_health_error",
                level=logging.WARNING,
                provider=provider,
                category=error_category,
            )
            return None
        return original_update_provider_runtime(
            provider,
            success=success,
            error_category=error_category,
            **kwargs,
        )

    download_manager.update_provider_runtime = bounded_provider_runtime

    original_search_provider = download_manager._search_provider

    def logged_search_provider(row: dict[str, Any], track: dict[str, Any]) -> dict[str, Any]:
        result = original_search_provider(row, track)
        error = result.get("error")
        if error:
            _event(
                "provider_search_error",
                level=logging.WARNING,
                provider=result.get("provider"),
                track_id=track.get("track_id"),
                category=getattr(error, "category", "error"),
                error=str(error)[-1200:],
                search_ms=result.get("search_ms"),
            )
        return result

    download_manager._search_provider = logged_search_provider

    original_process_job = download_manager.process_job

    def logged_process_job(job: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        try:
            result = original_process_job(job)
        except Exception as exc:
            _event(
                "job_exception",
                level=logging.ERROR,
                job_id=job.get("id"),
                track_id=job.get("track_id"),
                artist=job.get("artist"),
                title=job.get("title"),
                elapsed_ms=int((time.monotonic() - started) * 1000),
                error=f"{type(exc).__name__}: {exc}"[-1800:],
            )
            raise

        ok = bool(result.get("ok"))
        _event(
            "job_result",
            level=logging.INFO if ok else logging.WARNING,
            job_id=job.get("id"),
            track_id=job.get("track_id"),
            artist=job.get("artist"),
            title=job.get("title"),
            ok=ok,
            status=result.get("status") or ("completed" if ok else "unknown"),
            provider=result.get("provider"),
            match_score=result.get("match_score"),
            providers_tried=result.get("providers_tried"),
            retry_seconds=result.get("retry_seconds"),
            elapsed_ms=int((time.monotonic() - started) * 1000),
            error=str(result.get("error") or "")[-1800:] or None,
        )
        return result

    download_manager.process_job = logged_process_job


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    recovered = recover_interrupted_jobs()
    _install_runtime_guards()
    _event(
        "manager_start",
        recovered_jobs=recovered,
        max_global_downloads=download_manager.MAX_GLOBAL_DOWNLOADS,
        max_parallel_provider_searches=download_manager.MAX_PARALLEL_PROVIDER_SEARCHES,
        audio_delete_allowed=False,
        overwrite_existing_audio_allowed=False,
    )
    download_manager.run_download_manager(batch_limit=20)


if __name__ == "__main__":
    main()
