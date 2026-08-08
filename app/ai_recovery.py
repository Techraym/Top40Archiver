from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .ai_learning import choose_action
from .ai_session_console import operator_context, scope_held
from .config import DATA_DIR
from .db import connect, now_iso
from .download_db import retry_job
from .rejection_log import classify_rejection

STATE_FILE = DATA_DIR / "ai" / "recovery-state.json"
REPORT_FILE = DATA_DIR / "ai" / "last-recovery-report.json"
HISTORY_FILE = DATA_DIR / "ai" / "recovery-history.jsonl"
TRANSIENT = {"rate_limit", "forbidden", "timeout", "network", "youtube_bot_check", "database"}
SEARCH_FAILURES = {"no_search_results", "low_match_score", "invalid_source_url"}
PERMANENT = {"youtube_private", "youtube_removed", "youtube_geo_block", "youtube_copyright", "storage"}
RETRYABLE = TRANSIENT | SEARCH_FAILURES | {"other"}
COOLDOWN_MINUTES = 5
RECOVERY_RESET_HOURS = 6
MAX_RECOVERIES_PER_ERROR = 6
SEARCH_BATCH_LIMIT = 80
TRANSIENT_BATCH_LIMIT = 20
OTHER_BATCH_LIMIT = 40
ACTIVE_JOB_STATUSES = {"searching", "downloading", "validating", "processing"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _append_history(payload: dict) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _cooldown_ready(state: dict, action: str) -> bool:
    raw = state.get("actions", {}).get(action)
    if not raw:
        return True
    try:
        previous = datetime.fromisoformat(raw)
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=timezone.utc)
        return _utcnow() - previous >= timedelta(minutes=COOLDOWN_MINUTES)
    except (TypeError, ValueError):
        return True


def _normalise_error(value: str) -> str:
    text = " ".join(str(value or "").casefold().split())
    text = re.sub(r"\b\d{2,}\b", "#", text)
    return text[-1200:]


def _error_fingerprint(category: str, message: str) -> str:
    raw = f"{category}|{_normalise_error(message)}".encode("utf-8", "ignore")
    return hashlib.sha1(raw).hexdigest()[:16]


def _recovery_record(state: dict, item: dict) -> dict:
    records = state.setdefault("track_recoveries", {})
    key = str(item["id"])
    existing = records.get(key, {})
    if isinstance(existing, int):
        existing = {"count": existing}
    if not isinstance(existing, dict):
        existing = {}

    fingerprint = _error_fingerprint(item["category"], item.get("error_message") or "")
    last_at = existing.get("last_at")
    reset = existing.get("fingerprint") != fingerprint
    if last_at and not reset:
        try:
            parsed = datetime.fromisoformat(str(last_at))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            reset = _utcnow() - parsed >= timedelta(hours=RECOVERY_RESET_HOURS)
        except ValueError:
            reset = True

    if reset:
        existing = {"count": 0, "fingerprint": fingerprint, "category": item["category"]}
    else:
        existing.setdefault("fingerprint", fingerprint)
        existing.setdefault("category", item["category"])
        existing.setdefault("count", 0)
    records[key] = existing
    return existing


def _split_primary_artist(value: str) -> str:
    artist = " ".join(str(value or "").split()).strip()
    artist = re.sub(r"\s+(?:feat\.?|ft\.?|featuring|met)\s+.+$", "", artist, flags=re.I)
    if artist.count(" & ") >= 2 or len(artist) > 70:
        artist = artist.split(" & ", 1)[0].strip()
    if " / " in artist:
        artist = artist.split(" / ", 1)[0].strip()
    return artist


def _plain_title(value: str) -> str:
    title = " ".join(str(value or "").split()).strip()
    title = re.sub(r"\s*[\[(](?:official|video|audio|lyrics?|clip|hd|4k)[^\])]*[\])]", "", title, flags=re.I)
    return " ".join(title.split()).strip()


def _repair_strategy(item: dict, recovery_count: int) -> tuple[str, str | None]:
    category = item["category"]
    artist = str(item.get("artist") or "").strip()
    title = str(item.get("title") or "").strip()
    primary_artist = _split_primary_artist(artist)
    plain_title = _plain_title(title)

    if category in TRANSIENT:
        return "backoff_retry", None
    if category in SEARCH_FAILURES:
        strategy = choose_action(
            f"download:{category}",
            ["canonical_search", "simplified_artist", "title_first", "audio_fallback"],
            exploration_index=recovery_count,
        )
        if strategy == "canonical_search":
            return strategy, None
        if strategy == "simplified_artist":
            return strategy, f"{primary_artist} - {plain_title}".strip(" -")
        if strategy == "title_first":
            return strategy, f"{plain_title} {primary_artist}".strip()
        return strategy, f"{primary_artist} {plain_title} audio".strip()
    return "clean_retry", None


def _failure_snapshot() -> tuple[list[dict], Counter]:
    with connect() as con:
        rows = con.execute(
            """
            SELECT t.id,t.artist,t.title,t.download_status,t.download_attempts,
                   t.custom_search_query,t.youtube_url,t.error_message,t.updated_at,
                   j.id AS job_id,j.status AS job_status,j.next_attempt_at AS job_next_attempt_at,
                   j.updated_at AS job_updated_at,j.error AS job_error
            FROM tracks t
            LEFT JOIN download_jobs j ON j.track_id=t.id
            WHERE t.download_status IN ('failed','unavailable','downloading')
            ORDER BY CASE t.download_status WHEN 'failed' THEN 0 WHEN 'downloading' THEN 1 ELSE 2 END,
                     t.updated_at ASC
            LIMIT 1500
            """
        ).fetchall()
    failures: list[dict] = []
    categories: Counter = Counter()
    for row in rows:
        message = row["job_error"] or row["error_message"] or ""
        category = classify_rejection(message)
        item = dict(row)
        item["category"] = category
        failures.append(item)
        categories[category] += 1
    return failures, categories


def _release_selected(selected: list[dict], state: dict) -> tuple[int, list[dict]]:
    if not selected:
        return 0, []

    released = 0
    details: list[dict] = []
    for item in selected:
        record = _recovery_record(state, item)
        count_before = int(record.get("count", 0))
        strategy, query = _repair_strategy(item, count_before)
        queued = retry_job(int(item["id"]))
        if not queued:
            continue
        with connect() as con:
            con.execute(
                """
                UPDATE tracks
                SET youtube_url=NULL,
                    custom_search_query=?,
                    error_message=?,
                    updated_at=?
                WHERE id=? AND download_status!='downloaded'
                """,
                (
                    query,
                    f"AI-herstel: strategie {strategy}; download_job opnieuw ingepland na {item['category']}.",
                    now_iso(),
                    int(item["id"]),
                ),
            )
        released += 1
        record["count"] = count_before + 1
        record["last_at"] = _utcnow().isoformat()
        record["last_strategy"] = strategy
        record["last_query"] = query
        details.append(
            {
                "id": item["id"],
                "artist": item["artist"],
                "title": item["title"],
                "category": item["category"],
                "strategy": strategy,
                "query": query,
                "recovery_number": count_before + 1,
                "download_job_requeued": True,
                "manager_restart_requested": False,
            }
        )
    return released, details


def _batch_limit_for(item: dict) -> int:
    if item["category"] in TRANSIENT:
        return TRANSIENT_BATCH_LIMIT
    if item["category"] in SEARCH_FAILURES:
        return SEARCH_BATCH_LIMIT
    return OTHER_BATCH_LIMIT


def _is_stale_active(item: dict, stale_cutoff: datetime) -> bool:
    if str(item.get("job_status") or "") not in ACTIVE_JOB_STATUSES and item.get("download_status") != "downloading":
        return False
    raw = item.get("job_updated_at") or item.get("updated_at")
    try:
        updated = datetime.fromisoformat(str(raw or ""))
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return updated < stale_cutoff
    except ValueError:
        return True


def run_cycle() -> dict:
    state = _load_state()
    state.setdefault("actions", {})
    state.setdefault("track_recoveries", {})
    failures, counts = _failure_snapshot()
    actions: list[dict] = []
    recommendations: list[str] = []
    held = scope_held("downloads")
    guidance = operator_context("downloads")

    retryable: list[dict] = []
    manager_backoff: list[dict] = []
    skipped_permanent: list[dict] = []
    skipped_limit: list[dict] = []
    stale_downloading: list[dict] = []

    stale_cutoff = _utcnow() - timedelta(minutes=30)
    for item in failures:
        category = item["category"]
        if _is_stale_active(item, stale_cutoff):
            stale_downloading.append(item)
            continue
        if str(item.get("job_status") or "") in ACTIVE_JOB_STATUSES:
            continue
        if category in PERMANENT:
            skipped_permanent.append(item)
            continue
        if category in TRANSIENT and item.get("job_status") == "waiting_retry":
            manager_backoff.append(item)
            continue

        record = _recovery_record(state, item)
        if int(record.get("count", 0)) >= MAX_RECOVERIES_PER_ERROR:
            skipped_limit.append(item)
            continue
        if category in RETRYABLE:
            retryable.append(item)

    decision = {
        "status": "observe",
        "reason": "Geen herstelbare mislukte downloads gevonden.",
        "confidence": 0.98,
    }

    if held:
        decision = {
            "status": "operator_hold",
            "reason": (
                "Menselijke operator heeft nieuwe automatische downloadmutaties gepauzeerd. "
                "Fouten, vastgelopen downloads en retrykandidaten worden wel volledig gemonitord."
            ),
            "confidence": 1.0,
        }
        recommendations.append(
            f"Download-hold actief: {len(retryable)} retrykandidaten en {len(stale_downloading)} mogelijk vastgelopen downloads blijven ongewijzigd totdat de operator de hold beëindigt."
        )
    else:
        if stale_downloading:
            stale_ids = [int(x["id"]) for x in stale_downloading]
            requeued = sum(1 for track_id in stale_ids if retry_job(track_id))
            if requeued:
                actions.append({
                    "action": "release_stale_download_jobs",
                    "released": requeued,
                    "result": "gelukt",
                    "manager_restart_requested": False,
                })
                recommendations.append(
                    f"{requeued} stale downloadjobs zijn via de download_jobs-queue opnieuw aangeboden zonder de gezonde manager te herstarten."
                )

        if retryable and _cooldown_ready(state, "retry_failed"):
            first = retryable[0]
            limit = _batch_limit_for(first)
            selected: list[dict] = []
            for item in retryable:
                if len(selected) >= limit:
                    break
                if first["category"] in TRANSIENT and item["category"] not in TRANSIENT:
                    continue
                selected.append(item)

            released, repair_details = _release_selected(selected, state)
            action = {
                "action": "retry_failed_downloads",
                "released": released,
                "selected": len(selected),
                "manager_restart_requested": False,
                "result": "gelukt" if released else "overgeslagen",
                "repairs": repair_details[:50],
            }
            actions.append(action)
            state["actions"]["retry_failed"] = _utcnow().isoformat()
            strategies = Counter(x["strategy"] for x in repair_details)
            decision = {
                "status": "recover",
                "reason": f"{released} downloads opnieuw ingepland in download_jobs met {len(strategies)} herstelstrategie(ën); downloadmanager niet onderbroken.",
                "confidence": 0.98 if released else 0.8,
            }
            recommendations.append("De AI heeft mislukte downloads via de actuele download_jobs-architectuur opnieuw in de actieve wachtrij geplaatst.")
            if strategies:
                recommendations.append("Gebruikte strategieën: " + ", ".join(f"{k}={v}" for k, v in strategies.items()) + ".")
        elif retryable:
            decision = {
                "status": "cooldown",
                "reason": f"{len(retryable)} herstelbare downloads wachten maximaal {COOLDOWN_MINUTES} minuten om herhaalde bronbelasting te voorkomen.",
                "confidence": 0.95,
            }
        elif manager_backoff:
            decision = {
                "status": "managed_backoff",
                "reason": f"{len(manager_backoff)} tijdelijke provider/netwerkfouten staan al in waiting_retry; de downloadmanager bewaakt hun backoff en wordt niet door AI doorkruist.",
                "confidence": 0.99,
            }

    if manager_backoff:
        recommendations.append(
            f"{len(manager_backoff)} tijdelijke fouten blijven onder het eigen waiting_retry/backoffbeleid van top40-download-manager.service."
        )
    if skipped_limit:
        recommendations.append(
            f"{len(skipped_limit)} tracks bereikten de limiet voor dezelfde fout. Bij een gewijzigde fout of na {RECOVERY_RESET_HOURS} uur worden ze automatisch opnieuw toegelaten."
        )
    if skipped_permanent:
        recommendations.append(
            f"{len(skipped_permanent)} fouten lijken permanent of vereisen menselijke actie; die worden niet blind opnieuw belast."
        )

    with connect() as con:
        status_rows = con.execute(
            "SELECT download_status, COUNT(*) c FROM tracks GROUP BY download_status"
        ).fetchall()
        status_after = {str(row["download_status"]): int(row["c"]) for row in status_rows}
        job_rows = con.execute(
            "SELECT status,COUNT(*) c FROM download_jobs GROUP BY status"
        ).fetchall()
        jobs_after = {str(row["status"]): int(row["c"]) for row in job_rows}

    report = {
        "ok": True,
        "generated_at": _utcnow().isoformat(),
        "failure_count": len(failures),
        "retryable_count": len(retryable),
        "manager_backoff_count": len(manager_backoff),
        "permanent_count": len(skipped_permanent),
        "recovery_limit_count": len(skipped_limit),
        "categories": dict(counts),
        "decision": decision,
        "actions": actions,
        "recommendations": recommendations,
        "operator_hold": held,
        "operator_guidance": guidance,
        "verification": {
            "status_after": status_after,
            "download_jobs_after": jobs_after,
            "pending_after": status_after.get("pending", 0),
            "failed_after": status_after.get("failed", 0),
            "downloading_after": status_after.get("downloading", 0),
            "download_manager_restart_requested": False,
            "recovery_uses_download_jobs": True,
        },
        "samples": {
            "retryable": [
                {"id": x["id"], "artist": x["artist"], "title": x["title"], "category": x["category"], "job_status": x.get("job_status")}
                for x in retryable[:20]
            ],
            "manager_backoff": [
                {"id": x["id"], "artist": x["artist"], "title": x["title"], "category": x["category"], "next_attempt_at": x.get("job_next_attempt_at")}
                for x in manager_backoff[:20]
            ],
            "permanent": [
                {"id": x["id"], "artist": x["artist"], "title": x["title"], "category": x["category"]}
                for x in skipped_permanent[:20]
            ],
            "limit": [
                {"id": x["id"], "artist": x["artist"], "title": x["title"], "category": x["category"]}
                for x in skipped_limit[:20]
            ],
        },
        "mode": "download-jobs-aware-bounded-autorecovery",
        "limits": {
            "transient_batch": TRANSIENT_BATCH_LIMIT,
            "search_batch": SEARCH_BATCH_LIMIT,
            "other_batch": OTHER_BATCH_LIMIT,
            "cooldown_minutes": COOLDOWN_MINUTES,
            "max_recoveries_per_error": MAX_RECOVERIES_PER_ERROR,
            "recovery_reset_hours": RECOVERY_RESET_HOURS,
        },
    }
    state["last_cycle"] = report["generated_at"]
    state["last_decision"] = decision
    _save(STATE_FILE, state)
    _save(REPORT_FILE, report)
    _append_history(report)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return report


if __name__ == "__main__":
    run_cycle()
