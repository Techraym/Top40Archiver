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
TRANSIENT = {"rate_limit", "forbidden", "timeout", "network", "youtube_bot_check", "database"}
SEARCH_FAILURES = {"no_search_results", "low_match_score", "invalid_source_url"}
COOLDOWN_MINUTES = 20


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
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "ok": False,
            "action": action,
            "returncode": completed.returncode,
            "stderr": completed.stderr[-1000:],
        }


def _failure_snapshot() -> tuple[list[dict], Counter]:
    with connect() as con:
        rows = con.execute(
            """
            SELECT id, artist, title, download_status, download_attempts,
                   error_message, updated_at
            FROM tracks
            WHERE download_status IN ('failed','unavailable','downloading')
            ORDER BY updated_at DESC
            LIMIT 500
            """
        ).fetchall()
    failures = []
    categories: Counter = Counter()
    for row in rows:
        category = classify_rejection(row["error_message"] or "")
        item = dict(row)
        item["category"] = category
        failures.append(item)
        categories[category] += 1
    return failures, categories


def _release_failures(categories: set[str], limit: int = 250) -> int:
    failures, _ = _failure_snapshot()
    selected = [item["id"] for item in failures if item["category"] in categories][:limit]
    if not selected:
        return 0
    placeholders = ",".join("?" for _ in selected)
    with connect() as con:
        con.execute(
            f"""
            UPDATE tracks
            SET download_status='failed', download_attempts=0,
                error_message='AI-herstel: tijdelijke blokkade opgeheven; opnieuw ingepland.',
                updated_at=?
            WHERE id IN ({placeholders})
            """,
            [now_iso(), *selected],
        )
    return len(selected)


def run_cycle() -> dict:
    state = _load_state()
    state.setdefault("actions", {})
    failures, counts = _failure_snapshot()
    actions: list[dict] = []
    recommendations: list[str] = []

    transient_total = sum(counts[name] for name in TRANSIENT)
    search_total = sum(counts[name] for name in SEARCH_FAILURES)

    # YouTube-blokkades worden niet bestreden met meer verkeer. Eerst terug naar
    # één worker, daarna alleen tijdelijk mislukte records opnieuw vrijgeven.
    if transient_total >= 3 and _cooldown_ready(state, "youtube_backoff"):
        settings = get_settings()
        previous_workers = int(settings.get("download_workers", "1") or 1)
        if previous_workers != 1:
            set_settings({"download_workers": "1"})
        released = _release_failures(TRANSIENT)
        restart = _run_safe_action("restart_download")
        actions.append({
            "action": "youtube_backoff",
            "workers_before": previous_workers,
            "workers_after": 1,
            "released": released,
            "restart": restart,
        })
        state["actions"]["youtube_backoff"] = _utcnow().isoformat()
        recommendations.append("YouTube-fouten gedetecteerd: downloader draait tijdelijk met één worker.")

    # Een massale zoekafwijzing wordt één keer per cooldown opnieuw ingepland.
    # De matchdrempel wordt bewust niet automatisch verlaagd: dat kan verkeerde
    # muziek accepteren. Wel worden brede zoekvarianten opnieuw geprobeerd.
    if search_total >= 10 and _cooldown_ready(state, "search_retry"):
        released = _release_failures(SEARCH_FAILURES)
        restart = _run_safe_action("restart_download") if released else {"ok": True, "skipped": True}
        actions.append({"action": "search_retry", "released": released, "restart": restart})
        state["actions"]["search_retry"] = _utcnow().isoformat()
        recommendations.append("Veel zoekafwijzingen opnieuw ingepland; matchveiligheid bleef ongewijzigd.")

    # Een achtergebleven 'downloading'-status na een crash mag veilig terug naar failed.
    stale_before = (_utcnow() - timedelta(minutes=30)).isoformat()
    with connect() as con:
        cursor = con.execute(
            """
            UPDATE tracks
            SET download_status='failed', error_message='AI-herstel: vastgelopen download opnieuw ingepland.',
                updated_at=?
            WHERE download_status='downloading' AND updated_at<?
            """,
            (now_iso(), stale_before),
        )
        stale_released = int(cursor.rowcount or 0)
    if stale_released:
        actions.append({"action": "release_stale_downloads", "released": stale_released})

    report = {
        "ok": True,
        "generated_at": _utcnow().isoformat(),
        "failure_count": len(failures),
        "categories": dict(counts),
        "actions": actions,
        "recommendations": recommendations,
        "mode": "bounded-autorecovery",
    }
    state["last_cycle"] = report["generated_at"]
    _save(STATE_FILE, state)
    _save(REPORT_FILE, report)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return report


if __name__ == "__main__":
    run_cycle()
