from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import socket
import threading
import time
from typing import Any

from . import download_manager
from .db import connect, now_iso


LOGGER = logging.getLogger("top40.download_manager")
INTERRUPTED_STATUSES = ("searching", "downloading", "validating", "processing")
CANDIDATE_ONLY_ERRORS = {"drm", "unavailable"}
GLOBAL_NETWORK_ERRORS = {"network"}
SOFT_REJECTION_REASONS = {"try_other_provider"}
NETWORK_PROBE_HOSTS = ("api-v2.soundcloud.com", "audiomack.com", "www.youtube.com")
NETWORK_PROBE_TTL_SECONDS = 10.0
_NETWORK_PROBE_LOCK = threading.Lock()
_NETWORK_PROBE_AT = 0.0
_NETWORK_PROBE_OK = True


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


def _network_ready() -> bool:
    """Return True when at least one independent provider edge is TCP reachable.

    The result is cached briefly so four workers do not turn a boot-time network
    outage into a burst of DNS/TCP probes. This is a readiness check only; it does
    not bypass provider rate limits or security controls.
    """
    global _NETWORK_PROBE_AT, _NETWORK_PROBE_OK
    now = time.monotonic()
    with _NETWORK_PROBE_LOCK:
        if now - _NETWORK_PROBE_AT < NETWORK_PROBE_TTL_SECONDS:
            return _NETWORK_PROBE_OK

        errors: list[str] = []
        ok = False
        for host in NETWORK_PROBE_HOSTS:
            try:
                socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
                with socket.create_connection((host, 443), timeout=2.0):
                    pass
                ok = True
                break
            except OSError as exc:
                errors.append(f"{host}: {exc}")

        _NETWORK_PROBE_AT = now
        _NETWORK_PROBE_OK = ok
        if not ok:
            _event(
                "global_network_unavailable",
                level=logging.WARNING,
                probe_hosts=list(NETWORK_PROBE_HOSTS),
                errors=errors[-3:],
            )
        return ok


def _rescorable_rejected_urls(track_id: int, provider: str) -> set[str]:
    """Only hard rejects are excluded from future provider searches.

    `try_other_provider` was a ranking decision, not proof that the candidate was
    wrong. 1.16.9 production data showed official candidates at 96-100 points in
    this state, so they must be re-scoreable after policy improvements.
    """
    with connect() as con:
        rows = con.execute(
            """
            SELECT candidate_url
            FROM rejected_candidates
            WHERE track_id=? AND provider=? AND reason NOT IN ('try_other_provider')
            """,
            (int(track_id), provider),
        ).fetchall()
    return {str(row["candidate_url"]) for row in rows}


def _clear_reaccepted_soft_rejects(track_id: int, provider: str, urls: list[str]) -> int:
    if not urls:
        return 0
    placeholders = ",".join("?" for _ in urls)
    with connect() as con:
        cursor = con.execute(
            f"""
            DELETE FROM rejected_candidates
            WHERE track_id=? AND provider=?
              AND reason IN ('try_other_provider')
              AND candidate_url IN ({placeholders})
            """,
            (int(track_id), provider, *urls),
        )
        return int(cursor.rowcount or 0)


def _defer_job_for_network(job: dict[str, Any]) -> dict[str, Any]:
    retry_seconds = 30
    next_attempt = (datetime.now(timezone.utc) + timedelta(seconds=retry_seconds)).isoformat()
    download_manager.set_job_state(
        int(job["id"]),
        "waiting_retry",
        error="global_network_unavailable",
        next_attempt_at=next_attempt,
        providers_tried=[],
    )
    with connect() as con:
        con.execute(
            """
            UPDATE tracks
            SET download_status='pending',error_message='Netwerk nog niet gereed; download wordt hervat',updated_at=?
            WHERE id=? AND download_status NOT IN ('downloaded','unavailable')
            """,
            (now_iso(), int(job["track_id"])),
        )
    _event(
        "job_waiting_for_network",
        level=logging.WARNING,
        job_id=job.get("id"),
        track_id=job.get("track_id"),
        artist=job.get("artist"),
        title=job.get("title"),
        retry_seconds=retry_seconds,
    )
    return {
        "ok": False,
        "track_id": int(job["track_id"]),
        "status": "waiting_retry",
        "retry_seconds": retry_seconds,
        "providers_tried": [],
        "error": "global_network_unavailable",
    }


def _install_runtime_guards() -> None:
    original_update_provider_runtime = download_manager.update_provider_runtime

    def bounded_provider_runtime(provider: str, *, success: bool, error_category: str | None = None, **kwargs: Any):
        category = str(error_category or "")
        if not success and category in CANDIDATE_ONLY_ERRORS:
            _event(
                "candidate_error_not_provider_health_error",
                level=logging.WARNING,
                provider=provider,
                category=error_category,
            )
            return None
        if not success and category in GLOBAL_NETWORK_ERRORS:
            _event(
                "global_network_error_not_provider_health_error",
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

    # 1.16.9 stored high-confidence ranking deferrals as rejected candidates.
    # Replace the imported lookup so those soft rejects can be re-scored while
    # hard evidence (wrong duration, cover, invalid audio, DRM, etc.) stays cached.
    download_manager.rejected_urls = _rescorable_rejected_urls

    original_search_provider = download_manager._search_provider

    def logged_search_provider(row: dict[str, Any], track: dict[str, Any]) -> dict[str, Any]:
        result = original_search_provider(row, track)
        accepted_urls = [
            str(item["candidate"].url)
            for item in (result.get("accepted") or [])
            if item.get("candidate") is not None
        ]
        cleared = _clear_reaccepted_soft_rejects(
            int(track.get("track_id") or 0),
            str(result.get("provider") or row.get("provider") or ""),
            accepted_urls,
        )
        if cleared:
            _event(
                "soft_candidates_reaccepted",
                provider=result.get("provider"),
                track_id=track.get("track_id"),
                count=cleared,
                urls=accepted_urls[:4],
            )

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
            if not _network_ready():
                result = _defer_job_for_network(job)
            else:
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
        soft_rejections_rescored=sorted(SOFT_REJECTION_REASONS),
        network_readiness_guard=True,
    )
    download_manager.run_download_manager(batch_limit=20)


if __name__ == "__main__":
    main()
