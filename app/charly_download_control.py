from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from typing import Any

import requests

from .ai_model_runtime import ModelBusy, model_slot
from .db import connect, now_iso
from . import download_policy

MIN_PREVIOUS_FAILURES = 2
MAX_AI_ROUNDS_PER_CYCLE = 5
MAX_NO_PROGRESS_ROUNDS = 3
MAX_CYCLE_WALL_SECONDS = 2 * 60 * 60
MAX_RECOVERY_SLOTS = 1
MIN_RETRY_SECONDS = 20
MAX_ACTIVE_RETRY_SECONDS = 2 * 60 * 60
MAX_PARK_SECONDS = 24 * 60 * 60
MODEL_TIMEOUT_SECONDS = 30
MIN_QUERY_CONFIDENCE = 0.55
MAX_QUERY_LENGTH = 180

_STATE_SQL = """
CREATE TABLE IF NOT EXISTS charly_download_recovery_state (
    track_id INTEGER PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
    cycle_started_at TEXT NOT NULL,
    last_attempt_at TEXT,
    next_review_at TEXT,
    ai_rounds INTEGER NOT NULL DEFAULT 0,
    no_progress_rounds INTEGER NOT NULL DEFAULT 0,
    cycles INTEGER NOT NULL DEFAULT 0,
    best_score REAL NOT NULL DEFAULT 0,
    last_signature TEXT,
    queries_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    last_action TEXT,
    updated_at TEXT NOT NULL
)
"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _init_state() -> None:
    with connect() as con:
        con.execute(_STATE_SQL)


def _queries(value: object) -> list[str]:
    try:
        data = json.loads(str(value or "[]"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    result: list[str] = []
    for item in data:
        text = " ".join(str(item or "").split()).strip()
        if text and text.casefold() not in {q.casefold() for q in result}:
            result.append(text)
    return result[-12:]


def _snapshot(track_id: int) -> dict[str, Any]:
    with connect() as con:
        rejected = con.execute(
            """
            SELECT
                COUNT(DISTINCT candidate_url) AS unique_candidates,
                MAX(COALESCE(match_score,0)) AS best_score
            FROM rejected_candidates
            WHERE track_id=?
            """,
            (int(track_id),),
        ).fetchone()
        attempts = con.execute(
            """
            SELECT COUNT(DISTINCT provider) AS providers
            FROM download_provider_attempts
            WHERE track_id=?
            """,
            (int(track_id),),
        ).fetchone()

    return {
        "unique_candidates": int((rejected or {})["unique_candidates"] or 0),
        "best_score": float((rejected or {})["best_score"] or 0.0),
        "providers": int((attempts or {})["providers"] or 0),
    }


def _signature(snapshot: dict[str, Any]) -> str:
    return json.dumps(
        {
            "unique_candidates": int(snapshot.get("unique_candidates") or 0),
            "best_score": round(float(snapshot.get("best_score") or 0.0), 2),
            "providers": int(snapshot.get("providers") or 0),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _load_state(track_id: int, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    _init_state()
    snap = snapshot or _snapshot(track_id)
    stamp = now_iso()

    with connect() as con:
        row = con.execute(
            "SELECT * FROM charly_download_recovery_state WHERE track_id=?",
            (int(track_id),),
        ).fetchone()
        if row is None:
            con.execute(
                """
                INSERT INTO charly_download_recovery_state(
                    track_id,cycle_started_at,best_score,last_signature,status,updated_at
                ) VALUES(?,?,?,?,?,?)
                """,
                (int(track_id), stamp, float(snap["best_score"]), None, "active", stamp),
            )
            row = con.execute(
                "SELECT * FROM charly_download_recovery_state WHERE track_id=?",
                (int(track_id),),
            ).fetchone()

    return dict(row)


def _save_state(track_id: int, **changes: Any) -> dict[str, Any]:
    _init_state()
    allowed = {
        "cycle_started_at","last_attempt_at","next_review_at","ai_rounds",
        "no_progress_rounds","cycles","best_score","last_signature",
        "queries_json","status","last_action",
    }
    clean = {key: value for key, value in changes.items() if key in allowed}
    clean["updated_at"] = now_iso()
    parts = [f"{key}=?" for key in clean]
    with connect() as con:
        con.execute(
            f"UPDATE charly_download_recovery_state SET {','.join(parts)} WHERE track_id=?",
            (*clean.values(), int(track_id)),
        )
        row = con.execute(
            "SELECT * FROM charly_download_recovery_state WHERE track_id=?",
            (int(track_id),),
        ).fetchone()
    return dict(row)


def _refresh_progress(track_id: int, state: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    snap = _snapshot(track_id)
    sig = _signature(snap)
    old_sig = str(state.get("last_signature") or "")
    best_before = float(state.get("best_score") or 0.0)
    best_now = float(snap.get("best_score") or 0.0)
    progress = bool(old_sig and sig != old_sig) or best_now > best_before + 0.5
    if not old_sig:
        no_progress = 0
    else:
        no_progress = 0 if progress else int(state.get("no_progress_rounds") or 0) + 1
    state = _save_state(
        track_id,
        best_score=max(best_before, best_now),
        last_signature=sig,
        no_progress_rounds=no_progress,
    )
    return state, progress


def _park_seconds(cycles: int, no_progress_rounds: int) -> int:
    base = 60 * 60
    exponent = min(max(0, int(cycles) - 1), 4)
    penalty = min(max(0, int(no_progress_rounds)), 3) * 15 * 60
    return min(MAX_PARK_SECONDS, base * (2**exponent) + penalty)


def _cycle_exhausted(state: dict[str, Any], now: datetime | None = None) -> bool:
    current = now or _utcnow()
    started = _parse_time(state.get("cycle_started_at")) or current
    age = max(0.0, (current - started).total_seconds())
    return (
        int(state.get("ai_rounds") or 0) >= MAX_AI_ROUNDS_PER_CYCLE
        or int(state.get("no_progress_rounds") or 0) >= MAX_NO_PROGRESS_ROUNDS
        or age >= MAX_CYCLE_WALL_SECONDS
    )


def _begin_new_cycle(track_id: int, state: dict[str, Any]) -> dict[str, Any]:
    return _save_state(
        track_id,
        cycle_started_at=now_iso(),
        next_review_at=None,
        ai_rounds=0,
        no_progress_rounds=0,
        status="active",
        last_action="cycle_reopened",
    )


def _park_cycle(track_id: int, state: dict[str, Any]) -> dict[str, Any]:
    cycles = int(state.get("cycles") or 0) + 1
    seconds = _park_seconds(cycles, int(state.get("no_progress_rounds") or 0))
    next_review = (_utcnow() + timedelta(seconds=seconds)).isoformat()
    history = _queries(state.get("queries_json"))
    if history:
        with connect() as con:
            row = con.execute(
                "SELECT custom_search_query FROM tracks WHERE id=?",
                (int(track_id),),
            ).fetchone()
            current = str(row["custom_search_query"] or "").strip() if row else ""
            if current and current.casefold() == history[-1].casefold():
                con.execute(
                    "UPDATE tracks SET custom_search_query=NULL,updated_at=? WHERE id=?",
                    (now_iso(), int(track_id)),
                )
    return _save_state(
        track_id,
        cycles=cycles,
        status="parked",
        next_review_at=next_review,
        last_action="parked_budget_exhausted",
    )


def _clean_query(value: object) -> str | None:
    query = " ".join(str(value or "").split()).strip()
    if len(query) < 4 or len(query) > MAX_QUERY_LENGTH:
        return None
    lowered = query.casefold()
    if "http://" in lowered or "https://" in lowered:
        return None
    return query


def _recent_rejections(track_id: int) -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute(
            """
            SELECT provider,reason,match_score
            FROM rejected_candidates
            WHERE track_id=?
            ORDER BY id DESC
            LIMIT 10
            """,
            (int(track_id),),
        ).fetchall()
    return [dict(row) for row in rows]


def _ask_charly(job: dict[str, Any], track: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    history = _queries(state.get("queries_json"))
    round_no = int(state.get("ai_rounds") or 0) + 1
    compact = {
        "artist": track.get("artist"),"title": track.get("title"),
        "album": track.get("album"),"year": track.get("year"),
        "recovery_round": round_no,"previous_queries": history[-6:],
        "rejected": _recent_rejections(int(job["track_id"])),
    }
    prompt = (
        "Je bent de machine-recoverylaag voor Top40Archiver. Maak exact één NIEUWE, "
        "veilige zoektekst voor hetzelfde muzieknummer. De eerdere zoekteksten hebben "
        "geen betrouwbare match opgeleverd; herhaal ze niet. Vereenvoudig artiestcredits, "
        "feat/ft/featuring, haakjes en chart-notatie wanneer nuttig. Gebruik album of jaar "
        "alleen wanneer dat de identiteit versterkt. Verzin geen remix/live/cover/karaoke/"
        "instrumental/sped-up/slowed variant als die niet in de titel staat. Geen URL en "
        "geen uitleg. Antwoord uitsluitend als JSON: "
        '{"search_query":"artiest titel","confidence":0.90}. '
        + json.dumps(compact, ensure_ascii=False)
    )
    with model_slot("charly-download-recovery", priority="background", wait_seconds=0.3):
        response = requests.post(
            os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate"),
            json={
                "model": os.getenv("TOP40_AI_MODEL", "qwen3:4b"),"prompt": prompt,
                "stream": False,"format": "json","keep_alive": "2h","think": False,
                "options": {"temperature": 0.12,"num_predict": 96,"charly_priority": "BATCH"},
            },
            timeout=MODEL_TIMEOUT_SECONDS,
        )
    response.raise_for_status()
    payload = json.loads(str(response.json().get("response") or "{}"))
    if not isinstance(payload, dict):
        raise ValueError("CHARLY/Qwen recovery-resultaat is geen JSON-object")
    return payload


def prepare_recovery_query(job: dict[str, Any], track: dict[str, Any]) -> dict[str, Any]:
    if os.getenv("TOP40_DOWNLOAD_RECOVERY_AI", "1") == "0":
        return {"prepared": False, "action": "disabled"}
    previous_failures = int(job.get("attempts") or 0)
    if previous_failures < MIN_PREVIOUS_FAILURES:
        return {"prepared": False, "action": "normal_retry", "progress": False}

    track_id = int(job["track_id"])
    state = _load_state(track_id)
    if str(state.get("status") or "") == "parked":
        review_at = _parse_time(state.get("next_review_at"))
        if review_at and review_at > _utcnow():
            return {"prepared": False,"action": "parked","next_review_at": review_at.isoformat(),"progress": False}
        state = _begin_new_cycle(track_id, state)

    state, progress = _refresh_progress(track_id, state)
    if _cycle_exhausted(state):
        state = _park_cycle(track_id, state)
        return {
            "prepared": False,"action": "parked_budget_exhausted",
            "next_review_at": state.get("next_review_at"),"progress": progress,
            "ai_rounds": int(state.get("ai_rounds") or 0),"cycles": int(state.get("cycles") or 0),
        }

    try:
        suggestion = _ask_charly(job, track, state)
    except ModelBusy as exc:
        _save_state(track_id, last_attempt_at=now_iso(), last_action="model_busy")
        return {"prepared": False,"action": "model_busy","reason": str(exc),"progress": progress}
    except Exception as exc:
        _save_state(track_id, last_attempt_at=now_iso(), last_action="model_unavailable")
        return {"prepared": False,"action": "model_unavailable","reason": str(exc)[-500:],"progress": progress}

    query = _clean_query(suggestion.get("search_query"))
    try:
        confidence = float(suggestion.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    rounds = int(state.get("ai_rounds") or 0) + 1
    history = _queries(state.get("queries_json"))
    normal_query = " ".join([str(track.get("artist") or "").strip(),str(track.get("title") or "").strip()]).strip()

    if not query:
        _save_state(track_id,ai_rounds=rounds,last_attempt_at=now_iso(),
                    no_progress_rounds=int(state.get("no_progress_rounds") or 0) + 1,last_action="no_safe_query")
        return {"prepared": False,"action": "no_safe_query","progress": progress}

    duplicate = query.casefold() in {item.casefold() for item in history}
    same_as_normal = query.casefold() == normal_query.casefold()
    if confidence < MIN_QUERY_CONFIDENCE or duplicate or same_as_normal:
        action = "low_confidence" if confidence < MIN_QUERY_CONFIDENCE else "duplicate_query"
        _save_state(track_id,ai_rounds=rounds,last_attempt_at=now_iso(),
                    no_progress_rounds=int(state.get("no_progress_rounds") or 0) + 1,last_action=action)
        return {"prepared": False,"action": action,"query": query,
                "confidence": round(confidence, 3),"progress": progress}

    history.append(query)
    with connect() as con:
        con.execute(
            "UPDATE tracks SET custom_search_query=?,updated_at=? WHERE id=? AND download_status!='downloaded'",
            (query, now_iso(), track_id),
        )
    state = _save_state(
        track_id,ai_rounds=rounds,last_attempt_at=now_iso(),
        queries_json=json.dumps(history[-12:], ensure_ascii=False),status="active",next_review_at=None,
        no_progress_rounds=0 if progress else int(state.get("no_progress_rounds") or 0),last_action="prepared",
    )
    return {"prepared": True,"action": "charly_autonomous_search_recovery","query": query,
            "confidence": round(confidence, 3),"progress": progress,
            "ai_rounds": int(state.get("ai_rounds") or 0),"cycles": int(state.get("cycles") or 0),
            "model": os.getenv("TOP40_AI_MODEL", "qwen3:4b")}


def retry_delay_seconds(*, attempts: int, queue_class: str, state: dict[str, Any] | None) -> int:
    current = state or {}
    action = str(current.get("last_action") or "")
    no_progress = int(current.get("no_progress_rounds") or 0)
    rounds = int(current.get("ai_rounds") or 0)
    if str(current.get("status") or "") == "parked":
        review_at = _parse_time(current.get("next_review_at"))
        if review_at:
            remaining = int(max(MIN_RETRY_SECONDS, (review_at - _utcnow()).total_seconds()))
            return min(MAX_PARK_SECONDS, remaining)
        return min(MAX_PARK_SECONDS, _park_seconds(int(current.get("cycles") or 1), no_progress))
    if action == "prepared":
        return min(120, max(MIN_RETRY_SECONDS, 20 + rounds * 10 + no_progress * 15))
    if action in {"model_busy", "model_unavailable"}:
        return min(900, max(60, 60 * (2 ** min(no_progress, 3))))
    if queue_class == "current" and attempts <= 5:
        return min(180, max(MIN_RETRY_SECONDS, 15 + attempts * 15 + no_progress * 10))
    exponent = min(max(0, attempts - MIN_PREVIOUS_FAILURES), 5)
    return min(MAX_ACTIVE_RETRY_SECONDS,max(90, 90 * (2**exponent) + no_progress * 60))


def _state_for_track(track_id: int) -> dict[str, Any] | None:
    _init_state()
    with connect() as con:
        row = con.execute("SELECT * FROM charly_download_recovery_state WHERE track_id=?",(int(track_id),)).fetchone()
    return dict(row) if row else None


def apply_retry_policy(job: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    if str(result.get("status") or "") != "waiting_retry":
        return result
    track_id = int(job["track_id"])
    state = _state_for_track(track_id)
    with connect() as con:
        row = con.execute("SELECT attempts FROM download_jobs WHERE id=?",(int(job["id"]),)).fetchone()
    attempts = int(row["attempts"] or 0) if row else int(job.get("attempts") or 0) + 1
    queue_class = str(job.get("queue_class") or "archive")
    seconds = retry_delay_seconds(attempts=attempts, queue_class=queue_class, state=state)
    next_attempt = (_utcnow() + timedelta(seconds=seconds)).isoformat()
    with connect() as con:
        con.execute("UPDATE download_jobs SET next_attempt_at=?,updated_at=? WHERE id=? AND status='waiting_retry'",
                    (next_attempt, now_iso(), int(job["id"])))
    updated = dict(result)
    updated["retry_seconds"] = seconds
    updated["queue_class"] = queue_class
    updated["charly_autonomous_recovery"] = attempts >= MIN_PREVIOUS_FAILURES
    if state:
        updated["charly_recovery_status"] = state.get("status")
        updated["charly_recovery_round"] = int(state.get("ai_rounds") or 0)
        updated["charly_recovery_cycles"] = int(state.get("cycles") or 0)
    return updated


def claim_jobs_background_safe(limit: int) -> list[dict[str, Any]]:
    from .download_db import init_download_db
    init_download_db()
    wanted = max(1, min(int(limit), 20))
    selected: list[Any] = []
    with connect() as con:
        download_policy._prepare_current_track_table(con)
        rows = con.execute(
            """
            SELECT j.*,t.artist,t.title,t.genre,t.spotify_album,t.spotify_release_date,
                   t.spotify_duration_ms,t.spotify_isrc,t.spotify_artist,t.spotify_title,
                   t.custom_search_query,t.youtube_url,t.source_track_id,
                   CASE WHEN EXISTS(SELECT 1 FROM current_download_tracks c WHERE c.track_id=t.id)
                        THEN 'current' ELSE 'archive' END AS queue_class
            FROM download_jobs j JOIN tracks t ON t.id=j.track_id
            WHERE j.cancel_requested=0 AND (
                j.status='queued' OR (
                    j.status='waiting_retry' AND
                    (j.next_attempt_at IS NULL OR datetime(j.next_attempt_at)<=datetime('now'))
                )
            )
            ORDER BY CASE WHEN EXISTS(SELECT 1 FROM current_download_tracks c WHERE c.track_id=t.id)
                          THEN 0 ELSE 1 END,j.updated_at,j.id
            LIMIT 5000
            """
        ).fetchall()
        fresh_current = [r for r in rows if str(r["queue_class"]) == "current" and int(r["attempts"] or 0) < MIN_PREVIOUS_FAILURES]
        fresh_archive = [r for r in rows if str(r["queue_class"]) == "archive" and int(r["attempts"] or 0) < MIN_PREVIOUS_FAILURES]
        recovery = [r for r in rows if int(r["attempts"] or 0) >= MIN_PREVIOUS_FAILURES]
        selected.extend(fresh_current[:wanted])
        remaining = wanted - len(selected)
        if remaining > 0 and recovery:
            selected.extend(recovery[: min(MAX_RECOVERY_SLOTS, remaining)])
            remaining = wanted - len(selected)
        if remaining > 0:
            selected.extend(fresh_archive[:remaining])
        claimed_ids: list[int] = []
        for row in selected:
            stamp = now_iso()
            updated = con.execute(
                "UPDATE download_jobs SET status='searching',started_at=COALESCE(started_at,?),updated_at=? "
                "WHERE id=? AND status IN ('queued','waiting_retry') AND cancel_requested=0",
                (stamp, stamp, row["id"]),
            )
            if updated.rowcount:
                claimed_ids.append(int(row["id"]))
        claimed_rows = []
        for job_id in claimed_ids:
            refreshed = con.execute(
                """
                SELECT j.*,t.artist,t.title,t.genre,t.spotify_album,t.spotify_release_date,
                       t.spotify_duration_ms,t.spotify_isrc,t.spotify_artist,t.spotify_title,
                       t.custom_search_query,t.youtube_url,t.source_track_id,
                       CASE WHEN EXISTS(SELECT 1 FROM current_download_tracks c WHERE c.track_id=t.id)
                            THEN 'current' ELSE 'archive' END AS queue_class
                FROM download_jobs j JOIN tracks t ON t.id=j.track_id
                WHERE j.id=? AND j.status='searching'
                """,
                (job_id,),
            ).fetchone()
            if refreshed:
                item = dict(refreshed)
                item["charly_recovery"] = int(item.get("attempts") or 0) >= MIN_PREVIOUS_FAILURES
                claimed_rows.append(item)
    return claimed_rows


def control_state_summary() -> dict[str, Any]:
    _init_state()
    with connect() as con:
        rows = con.execute("SELECT status,COUNT(*) AS amount FROM charly_download_recovery_state GROUP BY status").fetchall()
    return {
        "enabled": True,"max_background_slots": MAX_RECOVERY_SLOTS,
        "max_ai_rounds_per_cycle": MAX_AI_ROUNDS_PER_CYCLE,
        "max_no_progress_rounds": MAX_NO_PROGRESS_ROUNDS,
        "max_cycle_wall_seconds": MAX_CYCLE_WALL_SECONDS,
        "states": {str(row["status"]): int(row["amount"] or 0) for row in rows},
    }
