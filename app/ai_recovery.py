from __future__ import annotations

import json
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
COOLDOWN_MINUTES = 10
MAX_RECOVERIES_PER_TRACK = 3
BATCH_LIMIT = 100


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
    except ValueError:
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


def _failure_snapshot() -> tuple[list[dict], Counter]:
    with connect() as con:
        rows = con.execute(
            """
            SELECT id, artist, title, download_status, download_attempts,
                   error_message, updated_at
            FROM tracks
            WHERE download_status IN ('failed','unavailable','downloading')
            ORDER BY updated_at ASC
            LIMIT 1000
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


def _release_selected(selected: list[dict]) -> int:
    ids = [int(item["id"]) for item in selected]
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    with connect() as con:
        cursor = con.execute(
            f"""
            UPDATE tracks
            SET download_status='failed', download_attempts=0,
                error_message='AI-herstel: opnieuw ingepland na foutanalyse.',
                updated_at=?
            WHERE id IN ({placeholders})
            """,
            [now_iso(), *ids],
        )
    return int(cursor.rowcount or 0)


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
    for item in failures:
        category = item["category"]
        if item["download_status"] == "downloading":
            continue
        if category in PERMANENT:
            skipped_permanent.append(item)
            continue
        recovery_count = int(state["track_recoveries"].get(str(item["id"]), 0))
        if recovery_count >= MAX_RECOVERIES_PER_TRACK:
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

    if retryable and _cooldown_ready(state, "retry_failed"):
        selected = retryable[:BATCH_LIMIT]
        workers_before = None
        if transient_total:
            with connect() as con:
                settings = get_settings(con)
            workers_before = int(settings.get("download_workers", "1") or 1)
            if workers_before != 1:
                set_settings({"download_workers": "1"})

        released = _release_selected(selected)
        for item in selected:
            key = str(item["id"])
            state["track_recoveries"][key] = int(state["track_recoveries"].get(key, 0)) + 1

        restart = _run_safe_action("restart_download") if released else {"ok": True, "skipped": True}
        action = {
            "action": "retry_failed_downloads",
            "released": released,
            "selected": len(selected),
            "workers_before": workers_before,
            "workers_after": 1 if transient_total else workers_before,
            "restart": restart,
            "result": "gelukt" if released and restart.get("ok") else "gedeeltelijk" if released else "overgeslagen",
            "track_ids": [item["id"] for item in selected[:25]],
        }
        actions.append(action)
        state["actions"]["retry_failed"] = _utcnow().isoformat()
        decision = {
            "status": "recover",
            "reason": f"{released} herstelbare downloads zijn opnieuw ingepland en de downloader is gecontroleerd herstart.",
            "confidence": 0.97 if restart.get("ok") else 0.78,
        }
        recommendations.append("De AI heeft herstelbare downloads opnieuw vrijgegeven voor verwerking.")
        if transient_total:
            recommendations.append("Door tijdelijke YouTube- of netwerkfouten is het aantal workers teruggebracht naar één.")
    elif retryable:
        decision = {
            "status": "cooldown",
            "reason": f"{len(retryable)} herstelbare downloads wachten op het einde van de cooldown om herhaalde belasting te voorkomen.",
            "confidence": 0.95,
        }

    stale_before = (_utcnow() - timedelta(minutes=30)).isoformat()
    with connect() as con:
        cursor = con.execute(
            """
            UPDATE tracks
            SET download_status='failed', error_message='AI-herstel: vastgelopen download opnieuw ingepland.',
                download_attempts=0, updated_at=?
            WHERE download_status='downloading' AND updated_at<?
            """,
            (now_iso(), stale_before),
        )
        stale_released = int(cursor.rowcount or 0)
    if stale_released:
        restart = _run_safe_action("restart_download")
        actions.append({
            "action": "release_stale_downloads",
            "released": stale_released,
            "restart": restart,
            "result": "gelukt" if restart.get("ok") else "gedeeltelijk",
        })

    with connect() as con:
        queued_after = int(con.execute(
            "SELECT COUNT(*) FROM tracks WHERE download_status IN ('pending','failed','downloading')"
        ).fetchone()[0])

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
            "queue_after": queued_after,
            "download_service_restart_ok": all(
                item.get("restart", {"ok": True}).get("ok", False) for item in actions
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
        },
        "mode": "bounded-autorecovery",
        "limits": {
            "batch": BATCH_LIMIT,
            "cooldown_minutes": COOLDOWN_MINUTES,
            "max_recoveries_per_track": MAX_RECOVERIES_PER_TRACK,
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
