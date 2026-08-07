from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import DATA_DIR
from .db import connect, get_settings, now_iso, set_settings
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


def _run_safe_action(action: str) -> dict:
    completed = subprocess.run(
        ["/usr/local/sbin/top40-safe-action", action],
        capture_output=True,
        text=True,
        timeout=75,
        check=False,
    )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        result = {
            "ok": False,
            "action": action,
            "returncode": completed.returncode,
            "stderr": completed.stderr[-1000:],
        }
    result.setdefault("returncode", completed.returncode)
    return result


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
        phase = recovery_count % 4
        if phase == 0:
            return "canonical_search", None
        if phase == 1:
            return "simplified_artist", f"{primary_artist} - {plain_title}".strip(" -")
        if phase == 2:
            return "title_first", f"{plain_title} {primary_artist}".strip()
        return "audio_fallback", f"{primary_artist} {plain_title} audio".strip()
    return "clean_retry", None


def _failure_snapshot() -> tuple[list[dict], Counter]:
    with connect() as con:
        rows = con.execute(
            """
            SELECT id, artist, title, download_status, download_attempts,
                   custom_search_query, youtube_url, error_message, updated_at
            FROM tracks
            WHERE download_status IN ('failed','unavailable','downloading')
            ORDER BY CASE download_status WHEN 'failed' THEN 0 WHEN 'downloading' THEN 1 ELSE 2 END,
                     updated_at ASC
            LIMIT 1500
            """
        ).fetchall()
    failures: list[dict] = []
    categories: Counter = Counter()
    for row in rows:
        category = classify_rejection(row["error_message"] or "")
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
    with connect() as con:
        for item in selected:
            record = _recovery_record(state, item)
            count_before = int(record.get("count", 0))
            strategy, query = _repair_strategy(item, count_before)
            cursor = con.execute(
                """
                UPDATE tracks
                SET download_status='pending',
                    download_attempts=0,
                    youtube_url=NULL,
                    custom_search_query=?,
                    error_message=?,
                    updated_at=?
                WHERE id=? AND download_status!='downloaded'
                """,
                (
                    query,
                    f"AI-herstel: strategie {strategy}; opnieuw ingepland na {item['category']}.",
                    now_iso(),
                    int(item["id"]),
                ),
            )
            if int(cursor.rowcount or 0) > 0:
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
                    }
                )
    return released, details


def _batch_limit_for(item: dict) -> int:
    if item["category"] in TRANSIENT:
        return TRANSIENT_BATCH_LIMIT
    if item["category"] in SEARCH_FAILURES:
        return SEARCH_BATCH_LIMIT
    return OTHER_BATCH_LIMIT


def run_cycle() -> dict:
    state = _load_state()
    state.setdefault("actions", {})
    state.setdefault("track_recoveries", {})
    failures, counts = _failure_snapshot()
    actions: list[dict] = []
    recommendations: list[str] = []

    retryable: list[dict] = []
    skipped_permanent: list[dict] = []
    skipped_limit: list[dict] = []
    stale_downloading: list[dict] = []

    stale_cutoff = _utcnow() - timedelta(minutes=30)
    for item in failures:
        category = item["category"]
        if item["download_status"] == "downloading":
            try:
                updated = datetime.fromisoformat(str(item.get("updated_at") or ""))
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)
                if updated < stale_cutoff:
                    stale_downloading.append(item)
            except ValueError:
                stale_downloading.append(item)
            continue
        if category in PERMANENT:
            skipped_permanent.append(item)
            continue

        record = _recovery_record(state, item)
        if int(record.get("count", 0)) >= MAX_RECOVERIES_PER_ERROR:
            skipped_limit.append(item)
            continue
        if category in RETRYABLE:
            retryable.append(item)

    transient_total = sum(counts[name] for name in TRANSIENT)
    decision = {
        "status": "observe",
        "reason": "Geen herstelbare mislukte downloads gevonden.",
        "confidence": 0.98,
    }

    if stale_downloading:
        with connect() as con:
            ids = [int(x["id"]) for x in stale_downloading]
            placeholders = ",".join("?" for _ in ids)
            cursor = con.execute(
                f"""
                UPDATE tracks
                SET download_status='pending', download_attempts=0, youtube_url=NULL,
                    error_message='AI-herstel: vastgelopen download opnieuw ingepland.', updated_at=?
                WHERE id IN ({placeholders})
                """,
                [now_iso(), *ids],
            )
            stale_released = int(cursor.rowcount or 0)
        if stale_released:
            actions.append({"action": "release_stale_downloads", "released": stale_released, "result": "gelukt"})

    if retryable and _cooldown_ready(state, "retry_failed"):
        first = retryable[0]
        limit = _batch_limit_for(first)
        selected: list[dict] = []
        for item in retryable:
            if len(selected) >= limit:
                break
            # Bij rate limiting niet tegelijk ook tientallen zoekfouten vrijgeven.
            if first["category"] in TRANSIENT and item["category"] not in TRANSIENT:
                continue
            selected.append(item)

        workers_before = None
        if transient_total:
            with connect() as con:
                settings = get_settings(con)
            workers_before = int(settings.get("download_workers", "1") or 1)
            if workers_before != 1:
                set_settings({"download_workers": "1"})

        released, repair_details = _release_selected(selected, state)
        restart = _run_safe_action("restart_download") if released else {"ok": True, "skipped": True}
        action = {
            "action": "retry_failed_downloads",
            "released": released,
            "selected": len(selected),
            "workers_before": workers_before,
            "workers_after": 1 if transient_total else workers_before,
            "restart": restart,
            "result": "gelukt" if released and restart.get("ok") else "gedeeltelijk" if released else "overgeslagen",
            "repairs": repair_details[:50],
        }
        actions.append(action)
        state["actions"]["retry_failed"] = _utcnow().isoformat()
        strategies = Counter(x["strategy"] for x in repair_details)
        decision = {
            "status": "recover",
            "reason": f"{released} downloads opnieuw ingepland met {len(strategies)} herstelstrategie(ën); downloader gecontroleerd herstart.",
            "confidence": 0.97 if restart.get("ok") else 0.78,
        }
        recommendations.append("De AI heeft mislukte downloads opnieuw in de actieve wachtrij geplaatst.")
        if strategies:
            recommendations.append("Gebruikte strategieën: " + ", ".join(f"{k}={v}" for k, v in strategies.items()) + ".")
        if transient_total:
            recommendations.append("Tijdelijke YouTube/netwerkfouten: belasting teruggebracht naar één worker en kleinere herstelbatch.")
    elif retryable:
        decision = {
            "status": "cooldown",
            "reason": f"{len(retryable)} herstelbare downloads wachten maximaal {COOLDOWN_MINUTES} minuten om herhaalde bronbelasting te voorkomen.",
            "confidence": 0.95,
        }

    if skipped_limit:
        recommendations.append(
            f"{len(skipped_limit)} tracks bereikten de limiet voor dezelfde fout. Bij een gewijzigde fout of na {RECOVERY_RESET_HOURS} uur worden ze automatisch opnieuw toegelaten."
        )
    if skipped_permanent:
        recommendations.append(
            f"{len(skipped_permanent)} fouten lijken permanent of vereisen menselijke actie; die worden niet blind opnieuw belast."
        )

    if stale_downloading and not any(x.get("action") == "retry_failed_downloads" for x in actions):
        restart = _run_safe_action("restart_download")
        actions.append({
            "action": "restart_after_stale_release",
            "released": len(stale_downloading),
            "restart": restart,
            "result": "gelukt" if restart.get("ok") else "gedeeltelijk",
        })

    with connect() as con:
        status_rows = con.execute(
            "SELECT download_status, COUNT(*) c FROM tracks GROUP BY download_status"
        ).fetchall()
        status_after = {str(row["download_status"]): int(row["c"]) for row in status_rows}

    report = {
        "ok": True,
        "generated_at": _utcnow().isoformat(),
        "failure_count": len(failures),
        "retryable_count": len(retryable),
        "permanent_count": len(skipped_permanent),
        "recovery_limit_count": len(skipped_limit),
        "categories": dict(counts),
        "decision": decision,
        "actions": actions,
        "recommendations": recommendations,
        "verification": {
            "status_after": status_after,
            "pending_after": status_after.get("pending", 0),
            "failed_after": status_after.get("failed", 0),
            "downloading_after": status_after.get("downloading", 0),
            "download_service_restart_ok": all(
                item.get("restart", {"ok": True}).get("ok", True) for item in actions
            ) if actions else True,
        },
        "samples": {
            "retryable": [
                {"id": x["id"], "artist": x["artist"], "title": x["title"], "category": x["category"]}
                for x in retryable[:20]
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
        "mode": "adaptive-bounded-autorecovery",
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
