from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import json
import time
from typing import Any

from . import download_manager, download_manager_entry
from .ai_session_console import scope_held
from .db import now_iso
from .download_concurrency import (
    DEFAULT_DOWNLOAD_WORKERS,
    MAX_DOWNLOAD_WORKERS,
    evidence_worker_ceiling,
    hard_worker_ceiling,
    system_capacity_snapshot,
    system_worker_ceiling,
    worker_state,
)
from .download_db import reject_candidate as _store_rejected_candidate
from .download_metrics import provider_dashboard
from .download_policy import (
    FIRST_PROVIDER,
    TRANSIENT_CANDIDATE_ERRORS,
    apply_current_chart_fast_retry,
    claim_jobs_current_first,
    enqueue_pending_tracks_current_first,
    ensure_provider_order_policy,
)


def _persistent_reject_candidate(
    track_id: int,
    provider: str,
    url: str,
    reason: str,
    match_score: float | None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Persist only candidate/content failures, never temporary transport failures."""
    if str(reason or "") in TRANSIENT_CANDIDATE_ERRORS:
        return
    _store_rejected_candidate(track_id, provider, url, reason, match_score, detail)


def _youtube_first_provider_groups() -> tuple[list[list[dict[str, Any]]], list[list[dict[str, Any]]]]:
    """Give direct YouTube one exclusive first attempt before every other source."""
    rows = [
        row
        for row in download_manager.provider_configs(enabled_only=True)
        if download_manager._provider_available(row)
    ]
    rows.sort(
        key=lambda row: (
            int(row.get("priority") or 999)
            + int(row.get("ai_priority_adjustment") or 0),
            str(row.get("provider") or ""),
        )
    )
    first = [row for row in rows if str(row.get("provider")) == FIRST_PROVIDER]
    remaining = [row for row in rows if str(row.get("provider")) != FIRST_PROVIDER]

    primary_groups: list[list[dict[str, Any]]] = [[first[0]]] if first else []
    primary_groups.extend(
        remaining[index : index + download_manager.MAX_PARALLEL_PROVIDER_SEARCHES]
        for index in range(0, len(remaining), download_manager.MAX_PARALLEL_PROVIDER_SEARCHES)
    )
    return primary_groups, []


def _install_download_policy() -> None:
    ensure_provider_order_policy()
    download_manager.enqueue_pending_tracks = enqueue_pending_tracks_current_first
    download_manager.claim_jobs = claim_jobs_current_first
    download_manager._provider_groups = _youtube_first_provider_groups
    download_manager.reject_candidate = _persistent_reject_candidate


def _worker_configuration(snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    metrics = snapshot or provider_dashboard()
    state = worker_state()
    system = system_capacity_snapshot()
    evidence_ceiling = evidence_worker_ceiling(metrics)
    system_ceiling = system_worker_ceiling(system)
    hard_ceiling = hard_worker_ceiling(metrics, system)
    effective = max(
        DEFAULT_DOWNLOAD_WORKERS,
        min(
            MAX_DOWNLOAD_WORKERS,
            int(state.get("effective") or DEFAULT_DOWNLOAD_WORKERS),
            int(hard_ceiling),
        ),
    )
    return {
        **state,
        "effective": effective,
        "evidence_ceiling": evidence_ceiling,
        "system_ceiling": system_ceiling,
        "hard_ceiling": hard_ceiling,
        "system": system,
    }


def _write_state(
    *,
    state: str,
    results: list[dict[str, Any]] | None = None,
    error: str | None = None,
    worker_config: dict[str, Any] | None = None,
) -> None:
    try:
        dashboard = provider_dashboard()
        jobs = dashboard.get("jobs") or {}
        workers = worker_config or _worker_configuration(dashboard)
        payload = {
            "state": state,
            "workers": int(workers["effective"]),
            "workers_base": int(workers["base"]),
            "workers_max": MAX_DOWNLOAD_WORKERS,
            "workers_evidence_ceiling": int(workers["evidence_ceiling"]),
            "workers_system_ceiling": int(workers["system_ceiling"]),
            "workers_hard_ceiling": int(workers["hard_ceiling"]),
            "workers_ai_target": workers.get("ai_target"),
            "workers_ai_active": bool(workers.get("ai_active")),
            "workers_ai_until": workers.get("ai_until"),
            "workers_ai_reason": workers.get("ai_reason"),
            "system_capacity": workers.get("system"),
            "queue": int(jobs.get("queued", 0)) + int(jobs.get("searching", 0)),
            "running": sum(
                int(jobs.get(key, 0))
                for key in ("searching", "downloading", "validating", "processing")
            ),
            "retry": int(jobs.get("waiting_retry", 0)),
            "first_provider": FIRST_PROVIDER,
            "queue_priority": "current_top40,current_tipparade,archive",
            "single_queue_class_per_batch": True,
            "current_chart_fast_retry": True,
            "transient_candidate_retry": True,
            "youtube_errors": sum(
                int(item.get("consecutive_errors") or 0)
                for item in dashboard.get("providers", [])
                if item.get("provider") in {"youtube", "youtube_music"}
            ),
            "youtube_dependency_percent": dashboard.get("youtube_dependency_percent"),
            "results": (results or [])[-20:],
            "error": error,
            "updated_at": now_iso(),
        }
        download_manager.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = download_manager.STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(download_manager.STATE_FILE)
    except Exception:
        pass


def _run_one_job(job: dict[str, Any]) -> dict[str, Any]:
    result = download_manager.process_job(job)
    return apply_current_chart_fast_retry(job, result)


def run_dynamic_download_manager(batch_limit: int = 20, idle_seconds: float = 5.0) -> None:
    download_manager.DATA_DIR.mkdir(parents=True, exist_ok=True)
    (download_manager.DATA_DIR / "download-temp").mkdir(parents=True, exist_ok=True)
    download_manager.init_download_db()
    _install_download_policy()

    with download_manager.MANAGER_LOCK.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Er draait al een Top40 downloadmanager") from exc

        config = _worker_configuration()
        _write_state(state="started", worker_config=config)

        while True:
            try:
                config = _worker_configuration()
                if scope_held("downloads"):
                    _write_state(state="operator_hold", worker_config=config)
                    time.sleep(max(5.0, idle_seconds))
                    continue

                download_manager.enqueue_pending_tracks(max(100, batch_limit * 5))
                config = _worker_configuration()
                worker_limit = int(config["effective"])
                jobs = download_manager.claim_jobs(
                    min(worker_limit, max(1, int(batch_limit)))
                )
                if not jobs:
                    _write_state(state="idle", worker_config=config)
                    time.sleep(max(2.0, idle_seconds))
                    continue

                results: list[dict[str, Any]] = []
                with ThreadPoolExecutor(
                    max_workers=min(worker_limit, len(jobs)),
                    thread_name_prefix="download-job",
                ) as executor:
                    futures = {
                        executor.submit(_run_one_job, job): int(job["track_id"])
                        for job in jobs
                    }
                    for future in as_completed(futures):
                        track_id = futures[future]
                        try:
                            results.append(future.result())
                        except Exception as exc:
                            results.append(
                                {
                                    "ok": False,
                                    "track_id": track_id,
                                    "status": "worker_error",
                                    "error": str(exc)[-2000:],
                                }
                            )

                _write_state(state="processed", results=results, worker_config=config)
                time.sleep(0.5)
            except Exception as exc:
                _write_state(state="error", error=str(exc)[-3000:])
                time.sleep(max(5.0, idle_seconds))


def main() -> None:
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    download_manager.init_download_db()
    _install_download_policy()
    recovered = download_manager_entry.recover_interrupted_jobs()
    download_manager_entry._install_runtime_guards()
    initial = _worker_configuration()
    download_manager_entry._event(
        "manager_start",
        recovered_jobs=recovered,
        max_global_downloads=MAX_DOWNLOAD_WORKERS,
        default_global_downloads=DEFAULT_DOWNLOAD_WORKERS,
        active_global_downloads=int(initial["effective"]),
        evidence_worker_ceiling=int(initial["evidence_ceiling"]),
        system_worker_ceiling=int(initial["system_ceiling"]),
        hard_worker_ceiling=int(initial["hard_ceiling"]),
        ai_worker_scaling=True,
        ai_worker_target=initial.get("ai_target"),
        ai_worker_active=bool(initial.get("ai_active")),
        first_provider=FIRST_PROVIDER,
        queue_priority="current_top40,current_tipparade,archive",
        single_queue_class_per_batch=True,
        current_chart_fast_retry=True,
        transient_candidate_retry=True,
        max_parallel_provider_searches=download_manager.MAX_PARALLEL_PROVIDER_SEARCHES,
        audio_delete_allowed=False,
        overwrite_existing_audio_allowed=False,
        soft_rejections_rescored=sorted(download_manager_entry.SOFT_REJECTION_REASONS),
        network_readiness_guard=True,
        network_initial_cache_trusted=False,
        network_min_reachable=download_manager_entry.NETWORK_MIN_REACHABLE,
        network_stable_passes=download_manager_entry.NETWORK_STABLE_PASSES,
        post_download_preview_guard=True,
    )
    download_manager_entry._wait_for_stable_network()
    run_dynamic_download_manager(batch_limit=20)


if __name__ == "__main__":
    main()
