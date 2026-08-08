from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .db import connect
from .download_db import init_download_db, provider_configs


SEARCH_MARKERS = ("no_candidate", "no_candidates", "no_result", "search", "not_found", "unavailable")
MATCH_MARKERS = ("low_match", "wrong_duration", "preview_duration", "mismatch", "rejected", "match")
DOWNLOAD_MARKERS = ("forbidden", "403", "429", "drm", "download", "network", "timeout", "rate_limit", "bot")
VALIDATION_MARKERS = ("ffprobe", "invalid_audio", "validation", "codec", "duration")
PROCESS_MARKERS = ("ffmpeg", "conversion", "processing", "transcode", "tag")
ARCHIVE_MARKERS = ("archive", "storage", "rename", "write", "filesystem", "disk")


def _stage(error_category: Any, error: Any, candidate_url: Any, success: Any) -> str:
    if int(success or 0) == 1:
        return "provider_success"
    text = f"{error_category or ''} {error or ''}".casefold()
    if any(x in text for x in ARCHIVE_MARKERS):
        return "archive"
    if any(x in text for x in PROCESS_MARKERS):
        return "processing"
    if any(x in text for x in VALIDATION_MARKERS):
        return "validation"
    if any(x in text for x in MATCH_MARKERS):
        return "matching"
    if any(x in text for x in DOWNLOAD_MARKERS):
        return "downloading"
    if any(x in text for x in SEARCH_MARKERS):
        return "search"
    return "provider_attempt" if candidate_url else "search_or_matching"


def _short(value: Any, limit: int = 220) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text[:limit]


def _table_exists(con, name: str) -> bool:
    return bool(
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
    )


def collect_download_diagnostics(*, attempt_limit: int = 240, example_limit: int = 10) -> dict[str, Any]:
    """Return a compact deterministic downloader diagnosis for the local Qwen model.

    Heavy aggregation happens in SQLite/Python. The model receives counts and a
    small number of concrete examples instead of thousands of raw rows.
    """
    init_download_db()
    attempt_limit = max(20, min(int(attempt_limit), 1000))
    example_limit = max(3, min(int(example_limit), 20))

    with connect() as con:
        tracks_available = _table_exists(con, "tracks")
        job_status = {
            str(row["status"]): int(row["c"])
            for row in con.execute("SELECT status,COUNT(*) c FROM download_jobs GROUP BY status").fetchall()
        }
        if tracks_available:
            attempt_sql = """
                SELECT a.id,a.job_id,a.track_id,a.provider,a.candidate_url,a.match_score,
                       a.success,a.error_category,a.error,a.search_ms,a.download_ms,a.completed_at,
                       t.artist,t.title
                FROM download_provider_attempts a
                LEFT JOIN tracks t ON t.id=a.track_id
                ORDER BY a.id DESC LIMIT ?
            """
            retry_sql = """
                SELECT j.id,j.track_id,j.attempts,j.error,j.next_attempt_at,j.updated_at,t.artist,t.title
                FROM download_jobs j LEFT JOIN tracks t ON t.id=j.track_id
                WHERE j.status='waiting_retry'
                ORDER BY j.updated_at DESC LIMIT ?
            """
        else:
            attempt_sql = """
                SELECT a.id,a.job_id,a.track_id,a.provider,a.candidate_url,a.match_score,
                       a.success,a.error_category,a.error,a.search_ms,a.download_ms,a.completed_at,
                       NULL AS artist,NULL AS title
                FROM download_provider_attempts a
                ORDER BY a.id DESC LIMIT ?
            """
            retry_sql = """
                SELECT j.id,j.track_id,j.attempts,j.error,j.next_attempt_at,j.updated_at,
                       NULL AS artist,NULL AS title
                FROM download_jobs j
                WHERE j.status='waiting_retry'
                ORDER BY j.updated_at DESC LIMIT ?
            """

        attempts = [dict(row) for row in con.execute(attempt_sql, (attempt_limit,)).fetchall()]
        rejected = [
            dict(row)
            for row in con.execute(
                """
                SELECT provider,reason,COUNT(*) c
                FROM rejected_candidates
                GROUP BY provider,reason
                ORDER BY c DESC LIMIT 40
                """
            ).fetchall()
        ]
        cache = [
            dict(row)
            for row in con.execute(
                "SELECT provider,COUNT(*) c FROM provider_search_cache GROUP BY provider ORDER BY c DESC"
            ).fetchall()
        ]
        retry_examples = [dict(row) for row in con.execute(retry_sql, (example_limit,)).fetchall()]
        completed_24h = int(
            con.execute(
                "SELECT COUNT(*) FROM download_jobs WHERE status='completed' AND datetime(updated_at)>=datetime('now','-24 hours')"
            ).fetchone()[0]
        )
        provider_success_24h = int(
            con.execute(
                "SELECT COUNT(*) FROM download_provider_attempts WHERE success=1 AND datetime(completed_at)>=datetime('now','-24 hours')"
            ).fetchone()[0]
        )

    providers: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "attempts": 0,
            "successes": 0,
            "candidate_urls": 0,
            "errors": Counter(),
            "stages": Counter(),
            "last_error": "",
        }
    )
    global_stages: Counter[str] = Counter()
    global_errors: Counter[str] = Counter()
    for row in attempts:
        provider = str(row.get("provider") or "unknown")
        item = providers[provider]
        item["attempts"] += 1
        item["successes"] += int(row.get("success") or 0)
        if row.get("candidate_url"):
            item["candidate_urls"] += 1
        category = str(row.get("error_category") or ("success" if row.get("success") else "uncategorized"))
        item["errors"][category] += 1
        global_errors[category] += 1
        stage = _stage(row.get("error_category"), row.get("error"), row.get("candidate_url"), row.get("success"))
        item["stages"][stage] += 1
        global_stages[stage] += 1
        if row.get("error") and not item["last_error"]:
            item["last_error"] = _short(row.get("error"))

    provider_summary = []
    configs = {str(x.get("provider")): x for x in provider_configs(enabled_only=False)}
    for provider in sorted(set(providers) | set(configs)):
        item = providers.get(provider, {})
        errors = item.get("errors") or Counter()
        stages = item.get("stages") or Counter()
        cfg = configs.get(provider) or {}
        provider_summary.append(
            {
                "provider": provider,
                "enabled": bool(cfg.get("enabled", True)),
                "health": cfg.get("status"),
                "health_score": cfg.get("health_score"),
                "attempts": int(item.get("attempts") or 0),
                "successes": int(item.get("successes") or 0),
                "candidate_urls": int(item.get("candidate_urls") or 0),
                "top_errors": errors.most_common(4),
                "top_stages": stages.most_common(4),
                "last_error": _short(item.get("last_error") or cfg.get("last_error")),
            }
        )

    examples = []
    for row in attempts[:example_limit]:
        track = f"{_short(row.get('artist'), 80)} - {_short(row.get('title'), 100)}".strip(" -")
        if not track:
            track = f"track_id={row.get('track_id')}"
        examples.append(
            {
                "track": track,
                "provider": row.get("provider"),
                "success": bool(row.get("success")),
                "stage": _stage(row.get("error_category"), row.get("error"), row.get("candidate_url"), row.get("success")),
                "error_category": row.get("error_category"),
                "error": _short(row.get("error")),
                "match_score": row.get("match_score"),
                "candidate": _short(row.get("candidate_url"), 160),
            }
        )

    reject_summary: dict[str, list[list[Any]]] = defaultdict(list)
    for row in rejected:
        bucket = reject_summary[str(row.get("provider") or "unknown")]
        if len(bucket) < 4:
            bucket.append([str(row.get("reason") or "unknown"), int(row.get("c") or 0)])

    dominant_stage = global_stages.most_common(1)[0][0] if global_stages else "no_attempt_evidence"
    return {
        "window": {"recent_attempts": len(attempts), "attempt_limit": attempt_limit},
        "job_status": job_status,
        "completed_jobs_24h": completed_24h,
        "successful_provider_attempts_24h": provider_success_24h,
        "dominant_failure_stage": dominant_stage,
        "stage_counts": global_stages.most_common(),
        "error_counts": global_errors.most_common(12),
        "providers": provider_summary,
        "rejected_candidates": dict(reject_summary),
        "search_cache": {str(row["provider"]): int(row["c"]) for row in cache},
        "recent_examples": examples,
        "waiting_retry_examples": [
            {
                "track": (
                    f"{_short(row.get('artist'), 80)} - {_short(row.get('title'), 100)}".strip(" -")
                    or f"track_id={row.get('track_id')}"
                ),
                "attempts": int(row.get("attempts") or 0),
                "error": _short(row.get("error")),
                "next_attempt_at": row.get("next_attempt_at"),
            }
            for row in retry_examples
        ],
        "success_definition": "requeue/search is not success; only completed job or provider attempt success=1 counts",
    }
