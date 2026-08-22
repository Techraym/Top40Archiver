from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any, Iterable

from .db import connect, now_iso
from .normalize import normalize
from .providers import DEFAULT_PROVIDER_CONFIG


JOB_STATUSES = {
    "queued",
    "searching",
    "downloading",
    "validating",
    "processing",
    "completed",
    "failed",
    "waiting_retry",
    "cancelled",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS download_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  track_id INTEGER NOT NULL UNIQUE REFERENCES tracks(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'queued',
  attempts INTEGER NOT NULL DEFAULT 0,
  providers_tried_json TEXT NOT NULL DEFAULT '[]',
  preferred_provider TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  next_attempt_at TEXT,
  error TEXT,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_download_jobs_status_retry
ON download_jobs(status,next_attempt_at,updated_at);

CREATE TABLE IF NOT EXISTS download_provider_config (
  provider TEXT PRIMARY KEY,
  enabled INTEGER NOT NULL DEFAULT 1,
  priority INTEGER NOT NULL,
  max_concurrent INTEGER NOT NULL,
  requests_per_minute INTEGER NOT NULL,
  min_delay_seconds REAL NOT NULL,
  error_backoff_seconds INTEGER NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS download_provider_state (
  provider TEXT PRIMARY KEY REFERENCES download_provider_config(provider) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'healthy',
  last_request TEXT,
  last_success TEXT,
  last_error TEXT,
  last_error_category TEXT,
  consecutive_errors INTEGER NOT NULL DEFAULT 0,
  error_window_started_at TEXT,
  cooldown_until TEXT,
  circuit_open_count INTEGER NOT NULL DEFAULT 0,
  ai_priority_adjustment INTEGER NOT NULL DEFAULT 0,
  ai_last_decision TEXT,
  health_score REAL NOT NULL DEFAULT 100,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS download_provider_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER NOT NULL REFERENCES download_jobs(id) ON DELETE CASCADE,
  track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  candidate_url TEXT,
  match_score REAL,
  search_ms INTEGER,
  download_ms INTEGER,
  success INTEGER NOT NULL DEFAULT 0,
  error_category TEXT,
  error TEXT,
  source_codec TEXT,
  source_bitrate INTEGER,
  source_sample_rate INTEGER,
  output_codec TEXT,
  output_bitrate INTEGER,
  started_at TEXT NOT NULL,
  completed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_download_provider_attempts_provider_time
ON download_provider_attempts(provider,completed_at);
CREATE INDEX IF NOT EXISTS idx_download_provider_attempts_track
ON download_provider_attempts(track_id,id);

CREATE TABLE IF NOT EXISTS provider_search_cache (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cache_key TEXT NOT NULL,
  provider TEXT NOT NULL,
  result_url TEXT NOT NULL,
  candidate_json TEXT NOT NULL,
  match_score REAL NOT NULL,
  last_verified TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  UNIQUE(cache_key,provider,result_url)
);

CREATE INDEX IF NOT EXISTS idx_provider_search_cache_lookup
ON provider_search_cache(cache_key,provider,expires_at,match_score);

CREATE TABLE IF NOT EXISTS rejected_candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  candidate_url TEXT NOT NULL,
  reason TEXT NOT NULL,
  match_score REAL,
  detail_json TEXT NOT NULL DEFAULT '{}',
  rejected_at TEXT NOT NULL,
  UNIQUE(track_id,provider,candidate_url)
);

CREATE TABLE IF NOT EXISTS download_recovery_ai_state (
  track_id INTEGER PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
  attempted_at TEXT NOT NULL,
  outcome TEXT NOT NULL,
  suggested_query TEXT,
  confidence REAL
);
"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def init_download_db() -> None:
    with connect() as con:
        con.executescript(SCHEMA)
        for provider, defaults in DEFAULT_PROVIDER_CONFIG.items():
            con.execute(
                """
                INSERT OR IGNORE INTO download_provider_config(
                  provider,enabled,priority,max_concurrent,requests_per_minute,
                  min_delay_seconds,error_backoff_seconds,updated_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    provider,
                    1 if defaults["enabled"] else 0,
                    int(defaults["priority"]),
                    int(defaults["max_concurrent"]),
                    int(defaults["requests_per_minute"]),
                    float(defaults["min_delay_seconds"]),
                    int(defaults["error_backoff_seconds"]),
                    now_iso(),
                ),
            )
            con.execute(
                """
                INSERT OR IGNORE INTO download_provider_state(provider,status,health_score,updated_at)
                VALUES(?,?,?,?)
                """,
                (provider, "healthy", 100.0, now_iso()),
            )


def provider_configs(*, enabled_only: bool = False) -> list[dict[str, Any]]:
    init_download_db()
    with connect() as con:
        sql = """
            SELECT c.*,s.status,s.last_request,s.last_success,s.last_error,
                   s.last_error_category,s.consecutive_errors,s.cooldown_until,
                   s.circuit_open_count,s.ai_priority_adjustment,s.ai_last_decision,
                   s.health_score,s.updated_at AS state_updated_at
            FROM download_provider_config c
            JOIN download_provider_state s USING(provider)
        """
        params: list[Any] = []
        if enabled_only:
            sql += " WHERE c.enabled=1"
        sql += " ORDER BY (c.priority+s.ai_priority_adjustment),c.provider"
        return [dict(row) for row in con.execute(sql, params).fetchall()]


def update_provider_config(provider: str, values: dict[str, Any]) -> dict[str, Any]:
    init_download_db()
    allowed = {
        "enabled": lambda value: 1 if bool(value) else 0,
        "priority": lambda value: max(1, min(500, int(value))),
        "max_concurrent": lambda value: max(1, min(4, int(value))),
        "requests_per_minute": lambda value: max(1, min(600, int(value))),
        "min_delay_seconds": lambda value: max(0.0, min(600.0, float(value))),
        "error_backoff_seconds": lambda value: max(10, min(7200, int(value))),
    }
    updates: dict[str, Any] = {}
    for key, value in values.items():
        if key in allowed:
            updates[key] = allowed[key](value)
    if not updates:
        raise ValueError("geen geldige providerinstellingen opgegeven")
    with connect() as con:
        exists = con.execute(
            "SELECT provider FROM download_provider_config WHERE provider=?", (provider,)
        ).fetchone()
        if not exists:
            raise KeyError(provider)
        parts = [f"{key}=?" for key in updates]
        con.execute(
            f"UPDATE download_provider_config SET {','.join(parts)},updated_at=? WHERE provider=?",
            (*updates.values(), now_iso(), provider),
        )
    return next(item for item in provider_configs() if item["provider"] == provider)


def _cache_key(track: dict[str, Any]) -> str:
    return f"{normalize(str(track.get('artist') or ''))}|{normalize(str(track.get('title') or ''))}"


def cached_candidates(track: dict[str, Any], provider: str, *, limit: int = 4) -> list[dict[str, Any]]:
    key = _cache_key(track)
    with connect() as con:
        rows = con.execute(
            """
            SELECT candidate_json,match_score FROM provider_search_cache
            WHERE cache_key=? AND provider=? AND datetime(expires_at)>datetime('now')
            ORDER BY match_score DESC LIMIT ?
            """,
            (key, provider, max(1, min(limit, 10))),
        ).fetchall()
    result = []
    for row in rows:
        try:
            value = json.loads(row["candidate_json"])
            if isinstance(value, dict):
                value["cached_match_score"] = float(row["match_score"])
                result.append(value)
        except Exception:
            continue
    return result


def cache_candidate(
    track: dict[str, Any],
    provider: str,
    url: str,
    candidate: dict[str, Any],
    match_score: float,
    *,
    hours: int = 168,
) -> None:
    stamp = _utcnow()
    with connect() as con:
        con.execute(
            """
            INSERT INTO provider_search_cache(
              cache_key,provider,result_url,candidate_json,match_score,last_verified,expires_at
            ) VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(cache_key,provider,result_url) DO UPDATE SET
              candidate_json=excluded.candidate_json,
              match_score=excluded.match_score,
              last_verified=excluded.last_verified,
              expires_at=excluded.expires_at
            """,
            (
                _cache_key(track),
                provider,
                url,
                json.dumps(candidate, ensure_ascii=False),
                float(match_score),
                stamp.isoformat(),
                (stamp + timedelta(hours=max(1, hours))).isoformat(),
            ),
        )


def rejected_urls(track_id: int, provider: str) -> set[str]:
    with connect() as con:
        return {
            str(row["candidate_url"])
            for row in con.execute(
                "SELECT candidate_url FROM rejected_candidates WHERE track_id=? AND provider=?",
                (int(track_id), provider),
            ).fetchall()
        }


def reject_candidate(
    track_id: int,
    provider: str,
    url: str,
    reason: str,
    match_score: float | None,
    detail: dict[str, Any] | None = None,
) -> None:
    with connect() as con:
        con.execute(
            """
            INSERT INTO rejected_candidates(
              track_id,provider,candidate_url,reason,match_score,detail_json,rejected_at
            ) VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(track_id,provider,candidate_url) DO UPDATE SET
              reason=excluded.reason,match_score=excluded.match_score,
              detail_json=excluded.detail_json,rejected_at=excluded.rejected_at
            """,
            (
                int(track_id),
                provider,
                url,
                reason,
                match_score,
                json.dumps(detail or {}, ensure_ascii=False),
                now_iso(),
            ),
        )


def enqueue_track_ids(track_ids: Iterable[int]) -> int:
    init_download_db()
    ids = sorted({int(value) for value in track_ids if int(value) > 0})
    if not ids:
        return 0
    changed = 0
    with connect() as con:
        for track_id in ids:
            row = con.execute(
                "SELECT id,download_status FROM tracks WHERE id=?", (track_id,)
            ).fetchone()
            if row is None or row["download_status"] in {"downloaded", "unavailable"}:
                continue
            stamp = now_iso()
            con.execute(
                """
                INSERT INTO download_jobs(track_id,status,created_at,updated_at)
                VALUES(?,'queued',?,?)
                ON CONFLICT(track_id) DO UPDATE SET
                  status=CASE WHEN download_jobs.status='completed' THEN 'queued'
                              WHEN download_jobs.status='cancelled' THEN 'queued'
                              ELSE download_jobs.status END,
                  cancel_requested=0,
                  updated_at=excluded.updated_at
                """,
                (track_id, stamp, stamp),
            )
            con.execute(
                "UPDATE tracks SET download_status='pending',updated_at=? WHERE id=? AND download_status!='downloaded'",
                (stamp, track_id),
            )
            changed += 1
    return changed


def enqueue_pending_tracks(limit: int = 500) -> int:
    init_download_db()
    with connect() as con:
        rows = con.execute(
            """
            SELECT id FROM tracks
            WHERE download_status IN ('pending','failed','downloading')
            ORDER BY updated_at,id LIMIT ?
            """,
            (max(1, min(int(limit), 5000)),),
        ).fetchall()
    return enqueue_track_ids([int(row["id"]) for row in rows])


def claim_jobs(limit: int) -> list[dict[str, Any]]:
    init_download_db()
    claimed: list[dict[str, Any]] = []
    with connect() as con:
        rows = con.execute(
            """
            SELECT j.*,t.artist,t.title,t.genre,t.spotify_album,t.spotify_release_date,
                   t.spotify_duration_ms,t.spotify_isrc,t.spotify_artist,t.spotify_title,
                   t.custom_search_query,t.youtube_url,t.source_track_id
            FROM download_jobs j JOIN tracks t ON t.id=j.track_id
            WHERE j.cancel_requested=0
              AND (
                j.status='queued'
                OR (
                    j.status='waiting_retry'
                    AND (
                        j.next_attempt_at IS NULL
                        OR datetime(j.next_attempt_at)<=datetime('now')
                        OR EXISTS (
                            SELECT 1
                            FROM chart_entries ce
                            WHERE ce.track_id=t.id
                              AND ce.edition_id=(
                                SELECT id FROM editions
                                ORDER BY year DESC,week DESC
                                LIMIT 1
                              )
                        )
                        OR EXISTS (
                            SELECT 1
                            FROM tipparade_entries te
                            WHERE te.track_id=t.id
                              AND te.edition_id=(
                                SELECT id FROM tipparade_editions
                                ORDER BY year DESC,week DESC
                                LIMIT 1
                              )
                        )
                    )
                )
              )
            ORDER BY
              CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM chart_entries ce
                    WHERE ce.track_id=t.id
                      AND ce.edition_id=(
                        SELECT id FROM editions
                        ORDER BY year DESC,week DESC
                        LIMIT 1
                      )
                )
                OR EXISTS (
                    SELECT 1
                    FROM tipparade_entries te
                    WHERE te.track_id=t.id
                      AND te.edition_id=(
                        SELECT id FROM tipparade_editions
                        ORDER BY year DESC,week DESC
                        LIMIT 1
                      )
                )
                THEN 0
                ELSE 1
              END,
              COALESCE(
                (
                  SELECT ce.position
                  FROM chart_entries ce
                  WHERE ce.track_id=t.id
                    AND ce.edition_id=(
                      SELECT id FROM editions
                      ORDER BY year DESC,week DESC
                      LIMIT 1
                    )
                ),
                (
                  SELECT te.position
                  FROM tipparade_entries te
                  WHERE te.track_id=t.id
                    AND te.edition_id=(
                      SELECT id FROM tipparade_editions
                      ORDER BY year DESC,week DESC
                      LIMIT 1
                    )
                ),
                999
              ),
              j.updated_at,
              j.id
            LIMIT ?
            """,
            (max(1, min(int(limit), 20)),),
        ).fetchall()
        for row in rows:
            stamp = now_iso()
            updated = con.execute(
                """
                UPDATE download_jobs
                SET status='searching',started_at=COALESCE(started_at,?),updated_at=?
                WHERE id=? AND status IN ('queued','waiting_retry') AND cancel_requested=0
                """,
                (stamp, stamp, row["id"]),
            )
            if updated.rowcount:
                item = dict(row)
                item["status"] = "searching"
                claimed.append(item)
    return claimed


def set_job_state(
    job_id: int,
    status: str,
    *,
    error: str | None = None,
    next_attempt_at: str | None = None,
    preferred_provider: str | None = None,
    providers_tried: list[str] | None = None,
    increment_attempts: bool = False,
) -> None:
    if status not in JOB_STATUSES:
        raise ValueError(status)
    stamp = now_iso()
    with connect() as con:
        con.execute(
            """
            UPDATE download_jobs SET
              status=?,
              error=?,
              next_attempt_at=?,
              preferred_provider=COALESCE(?,preferred_provider),
              providers_tried_json=COALESCE(?,providers_tried_json),
              attempts=attempts+?,
              finished_at=CASE WHEN ? IN ('completed','failed','cancelled') THEN ? ELSE finished_at END,
              updated_at=?
            WHERE id=?
            """,
            (
                status,
                error,
                next_attempt_at,
                preferred_provider,
                json.dumps(providers_tried, ensure_ascii=False) if providers_tried is not None else None,
                1 if increment_attempts else 0,
                status,
                stamp,
                stamp,
                int(job_id),
            ),
        )


def cancel_job(track_id: int) -> bool:
    init_download_db()
    with connect() as con:
        row = con.execute("SELECT id,status FROM download_jobs WHERE track_id=?", (int(track_id),)).fetchone()
        if row is None or row["status"] == "completed":
            return False
        con.execute(
            "UPDATE download_jobs SET cancel_requested=1,status='cancelled',finished_at=?,updated_at=? WHERE id=?",
            (now_iso(), now_iso(), row["id"]),
        )
        con.execute(
            "UPDATE tracks SET download_status='failed',error_message='Download door operator geannuleerd',updated_at=? WHERE id=? AND download_status!='downloaded'",
            (now_iso(), int(track_id)),
        )
        return True


def retry_job(track_id: int) -> bool:
    init_download_db()
    with connect() as con:
        track = con.execute("SELECT id,download_status FROM tracks WHERE id=?", (int(track_id),)).fetchone()
        if track is None or track["download_status"] == "downloaded":
            return False
        stamp = now_iso()
        con.execute(
            """
            INSERT INTO download_jobs(track_id,status,created_at,updated_at)
            VALUES(?,'queued',?,?)
            ON CONFLICT(track_id) DO UPDATE SET
              status='queued',attempts=0,providers_tried_json='[]',preferred_provider=NULL,
              next_attempt_at=NULL,error=NULL,cancel_requested=0,started_at=NULL,finished_at=NULL,updated_at=excluded.updated_at
            """,
            (int(track_id), stamp, stamp),
        )
        con.execute(
            "UPDATE tracks SET download_status='pending',download_attempts=0,error_message=NULL,updated_at=? WHERE id=?",
            (stamp, int(track_id)),
        )
        return True


def job_cancel_requested(job_id: int) -> bool:
    with connect() as con:
        row = con.execute("SELECT cancel_requested FROM download_jobs WHERE id=?", (int(job_id),)).fetchone()
        return bool(row and row["cancel_requested"])


def record_provider_attempt(
    *,
    job_id: int,
    track_id: int,
    provider: str,
    candidate_url: str | None,
    match_score: float | None,
    search_ms: int | None,
    download_ms: int | None,
    success: bool,
    error_category: str | None = None,
    error: str | None = None,
    source_codec: str | None = None,
    source_bitrate: int | None = None,
    source_sample_rate: int | None = None,
    output_codec: str | None = None,
    output_bitrate: int | None = None,
    started_at: str | None = None,
) -> None:
    init_download_db()
    completed_at = now_iso()
    with connect() as con:
        con.execute(
            """
            INSERT INTO download_provider_attempts(
              job_id,track_id,provider,candidate_url,match_score,search_ms,download_ms,
              success,error_category,error,source_codec,source_bitrate,source_sample_rate,
              output_codec,output_bitrate,started_at,completed_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                int(job_id),
                int(track_id),
                provider,
                candidate_url,
                match_score,
                search_ms,
                download_ms,
                1 if success else 0,
                error_category,
                str(error or "")[-3000:] or None,
                source_codec,
                source_bitrate,
                source_sample_rate,
                output_codec,
                output_bitrate,
                started_at or completed_at,
                completed_at,
            ),
        )


def update_provider_runtime(
    provider: str,
    *,
    success: bool,
    error_category: str | None = None,
    base_backoff_seconds: int = 120,
) -> dict[str, Any]:
    init_download_db()
    now = _utcnow()
    with connect() as con:
        state_row = con.execute(
            "SELECT * FROM download_provider_state WHERE provider=?", (provider,)
        ).fetchone()
        state = dict(state_row or {})
        consecutive = int(state.get("consecutive_errors") or 0)
        window_raw = state.get("error_window_started_at")
        window_start = None
        if window_raw:
            try:
                window_start = datetime.fromisoformat(str(window_raw))
                if window_start.tzinfo is None:
                    window_start = window_start.replace(tzinfo=timezone.utc)
            except ValueError:
                window_start = None

        if success:
            status = "healthy"
            consecutive = 0
            cooldown_until = None
            window_start = None
            con.execute(
                """
                UPDATE download_provider_state
                SET status=?,last_success=?,consecutive_errors=0,error_window_started_at=NULL,
                    cooldown_until=NULL,health_score=MIN(100,health_score+3),updated_at=?
                WHERE provider=?
                """,
                (status, now.isoformat(), now.isoformat(), provider),
            )
        else:
            if window_start is None or now - window_start > timedelta(minutes=10):
                window_start = now
                consecutive = 0
            consecutive += 1
            severe = error_category in {"rate_limited", "forbidden", "captcha", "timeout"}
            status = "degraded" if consecutive >= 5 else "limited" if severe else "degraded"
            cooldown_seconds = int(base_backoff_seconds) if severe else 0
            if consecutive >= 8:
                status = "offline"
                cooldown_seconds = max(cooldown_seconds, 7200)
            elif consecutive >= 5:
                cooldown_seconds = max(cooldown_seconds, 1800)
            cooldown_until = now + timedelta(seconds=cooldown_seconds) if cooldown_seconds else None
            con.execute(
                """
                UPDATE download_provider_state
                SET status=?,last_error=?,last_error_category=?,consecutive_errors=?,
                    error_window_started_at=?,cooldown_until=?,
                    circuit_open_count=circuit_open_count+?,
                    health_score=MAX(0,health_score-?),updated_at=?
                WHERE provider=?
                """,
                (
                    status,
                    now.isoformat(),
                    error_category,
                    consecutive,
                    window_start.isoformat(),
                    cooldown_until.isoformat() if cooldown_until else None,
                    1 if cooldown_seconds else 0,
                    12 if severe else 6,
                    now.isoformat(),
                    provider,
                ),
            )
    return next(item for item in provider_configs() if item["provider"] == provider)


def mark_provider_request(provider: str) -> None:
    with connect() as con:
        con.execute(
            "UPDATE download_provider_state SET last_request=?,updated_at=? WHERE provider=?",
            (now_iso(), now_iso(), provider),
        )


def set_ai_provider_adjustment(provider: str, adjustment: int, summary: str) -> None:
    bounded = max(-20, min(20, int(adjustment)))
    with connect() as con:
        con.execute(
            """
            UPDATE download_provider_state
            SET ai_priority_adjustment=?,ai_last_decision=?,updated_at=?
            WHERE provider=?
            """,
            (bounded, str(summary or "")[:1000], now_iso(), provider),
        )


def jobs(limit: int = 100) -> list[dict[str, Any]]:
    init_download_db()
    with connect() as con:
        rows = con.execute(
            """
            SELECT j.*,t.artist,t.title,t.download_status,t.mp3_filename
            FROM download_jobs j JOIN tracks t ON t.id=j.track_id
            ORDER BY j.updated_at DESC,j.id DESC LIMIT ?
            """,
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["providers_tried"] = json.loads(item.pop("providers_tried_json") or "[]")
        except Exception:
            item["providers_tried"] = []
        result.append(item)
    return result


def provider_dashboard() -> dict[str, Any]:
    init_download_db()
    configs = provider_configs()
    with connect() as con:
        stats = {
            row["provider"]: dict(row)
            for row in con.execute(
                """
                SELECT provider,
                       COUNT(*) AS attempts,
                       SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) AS successes,
                       AVG(search_ms) AS avg_search_ms,
                       AVG(download_ms) AS avg_download_ms,
                       AVG(CASE WHEN success=1 THEN match_score END) AS avg_match_score
                FROM download_provider_attempts
                WHERE datetime(completed_at)>=datetime('now','-1 day')
                GROUP BY provider
                """
            ).fetchall()
        }
        totals = con.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN provider IN ('youtube','youtube_music') THEN 1 ELSE 0 END) AS youtube
            FROM download_provider_attempts
            WHERE success=1 AND datetime(completed_at)>=datetime('now','-1 day')
            """
        ).fetchone()
        active = {
            row["preferred_provider"]: int(row["c"])
            for row in con.execute(
                """
                SELECT preferred_provider,COUNT(*) AS c FROM download_jobs
                WHERE status IN ('searching','downloading','validating','processing')
                  AND preferred_provider IS NOT NULL
                GROUP BY preferred_provider
                """
            ).fetchall()
        }
        counts = {
            row["status"]: int(row["c"])
            for row in con.execute("SELECT status,COUNT(*) AS c FROM download_jobs GROUP BY status").fetchall()
        }

    items = []
    for config in configs:
        name = config["provider"]
        stat = stats.get(name, {})
        attempts = int(stat.get("attempts") or 0)
        successes = int(stat.get("successes") or 0)
        success_rate = round(successes / attempts * 100, 1) if attempts else None
        calculated = float(config.get("health_score") or 100)
        if success_rate is not None:
            calculated = max(0.0, min(100.0, calculated * 0.55 + success_rate * 0.45))
        items.append(
            {
                **config,
                "effective_priority": int(config["priority"]) + int(config.get("ai_priority_adjustment") or 0),
                "active_workers": active.get(name, 0),
                "attempts_24h": attempts,
                "successes_24h": successes,
                "success_rate_24h": success_rate,
                "average_search_ms": round(float(stat.get("avg_search_ms") or 0), 1) if attempts else None,
                "average_download_ms": round(float(stat.get("avg_download_ms") or 0), 1) if attempts else None,
                "average_match_score": round(float(stat.get("avg_match_score") or 0), 1) if successes else None,
                "calculated_health_score": round(calculated, 1),
            }
        )
    items.sort(key=lambda item: (item["effective_priority"], item["provider"]))
    total_success = int(totals["total"] or 0)
    youtube_success = int(totals["youtube"] or 0)
    youtube_dependency = round(youtube_success / total_success * 100, 1) if total_success else 0.0
    return {
        "ok": True,
        "providers": items,
        "jobs": counts,
        "downloads_24h": total_success,
        "without_youtube_24h": max(0, total_success - youtube_success),
        "youtube_family_24h": youtube_success,
        "youtube_dependency_percent": youtube_dependency,
        "target_youtube_dependency_percent": 10.0,
        "target_met": youtube_dependency < 10.0 if total_success else None,
    }
