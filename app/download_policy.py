from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .db import connect, now_iso
from .download_db import enqueue_track_ids, init_download_db
from .providers import DEFAULT_PROVIDER_CONFIG

PROVIDER_ORDER_POLICY = "youtube_first_v1"
PROVIDER_POLICY_SETTING = "download_provider_order_policy"
FIRST_PROVIDER = "youtube"
CURRENT_TOP40_FAST_RETRY_SECONDS = 20
CURRENT_TIPPARADE_FAST_RETRY_SECONDS = 30
CURRENT_CHART_FAST_RETRY_ATTEMPTS = 5

# Deze fouten zijn transport-/broncondities die later vanzelf kunnen verdwijnen.
# Ze mogen een inhoudelijk goede kandidaat daarom niet permanent uit de retryroute
# verwijderen. DRM en unavailable blijven juist harde kandidaatafwijzingen.
TRANSIENT_CANDIDATE_ERRORS = {
    "network",
    "forbidden",
    "rate_limited",
    "captcha",
    "timeout",
    "error",
    "configuration",
    "invalid_response",
}


def ensure_provider_order_policy() -> None:
    """Migrate existing production provider rows to the fixed YouTube-first policy."""
    init_download_db()
    with connect() as con:
        row = con.execute(
            "SELECT value FROM settings WHERE key=?",
            (PROVIDER_POLICY_SETTING,),
        ).fetchone()
        if row is not None and str(row["value"]) == PROVIDER_ORDER_POLICY:
            return

        stamp = now_iso()
        for provider, defaults in DEFAULT_PROVIDER_CONFIG.items():
            con.execute(
                """
                UPDATE download_provider_config
                SET priority=?,
                    enabled=CASE WHEN provider=? THEN 1 ELSE enabled END,
                    updated_at=?
                WHERE provider=?
                """,
                (int(defaults["priority"]), FIRST_PROVIDER, stamp, provider),
            )

        # Oude AI-prioriteitsadviezen zijn gemaakt onder de vorige fallbackpolicy.
        con.execute(
            "UPDATE download_provider_state SET ai_priority_adjustment=0,updated_at=?",
            (stamp,),
        )

        # De eerste probe na migratie moet actuele YouTube-evidence opleveren.
        con.execute(
            """
            UPDATE download_provider_state
            SET status='healthy',consecutive_errors=0,error_window_started_at=NULL,
                cooldown_until=NULL,updated_at=?
            WHERE provider=?
            """,
            (stamp, FIRST_PROVIDER),
        )

        placeholders = ",".join("?" for _ in TRANSIENT_CANDIDATE_ERRORS)
        con.execute(
            f"DELETE FROM rejected_candidates WHERE reason IN ({placeholders})",
            tuple(sorted(TRANSIENT_CANDIDATE_ERRORS)),
        )

        con.execute(
            """
            INSERT INTO settings(key,value) VALUES(?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (PROVIDER_POLICY_SETTING, PROVIDER_ORDER_POLICY),
        )


def _quote_identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _current_chart_sources(con) -> list[dict[str, Any]]:
    """Vind automatisch alle huidige hitlijst/edition-combinaties."""
    tables = {
        str(row["name"])
        for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    sources: list[dict[str, Any]] = []

    for entries_table in sorted(tables):
        if entries_table.startswith("sqlite_"):
            continue

        if entries_table != "chart_entries" and not entries_table.endswith("_entries"):
            continue

        q_entries = _quote_identifier(entries_table)

        columns = {
            str(row["name"])
            for row in con.execute(
                f"PRAGMA table_info({q_entries})"
            ).fetchall()
        }

        if not {"track_id", "edition_id"}.issubset(columns):
            continue

        edition_table = None

        for fk in con.execute(
            f"PRAGMA foreign_key_list({q_entries})"
        ).fetchall():
            if str(fk["from"]) == "edition_id":
                edition_table = str(fk["table"])
                break

        if not edition_table or edition_table not in tables:
            continue

        q_edition = _quote_identifier(edition_table)

        edition_columns = {
            str(row["name"])
            for row in con.execute(
                f"PRAGMA table_info({q_edition})"
            ).fetchall()
        }

        if "id" not in edition_columns:
            continue

        if {"year", "week"}.issubset(edition_columns):
            order_sql = "year DESC, week DESC, id DESC"
        elif "chart_date" in edition_columns:
            order_sql = "chart_date DESC, id DESC"
        else:
            continue

        latest = con.execute(
            f"SELECT id FROM {q_edition} ORDER BY {order_sql} LIMIT 1"
        ).fetchone()

        if latest is None:
            continue

        if entries_table == "chart_entries":
            name = "top40"
        else:
            name = entries_table[:-8]

        sources.append({
            "name": name,
            "entries_table": entries_table,
            "edition_table": edition_table,
            "edition_id": int(latest["id"]),
        })

    return sources


def _prepare_current_track_table(con) -> list[dict[str, Any]]:
    """Maak tijdelijke set met tracks uit de nieuwste editie van ALLE lijsten."""
    sources = _current_chart_sources(con)

    con.execute("DROP TABLE IF EXISTS temp.current_download_tracks")

    con.execute(
        """
        CREATE TEMP TABLE current_download_tracks(
            track_id INTEGER PRIMARY KEY
        )
        """
    )

    for source in sources:
        table = _quote_identifier(source["entries_table"])
        edition_id = int(source["edition_id"])

        con.execute(
            f"""
            INSERT OR IGNORE INTO current_download_tracks(track_id)
            SELECT track_id
            FROM {table}
            WHERE edition_id=?
            """,
            (edition_id,),
        )

    return sources


def enqueue_pending_tracks_current_first(limit: int = 500) -> int:
    """Zet alle actuele lijsten vóór de historische backlog."""
    init_download_db()

    with connect() as con:
        _prepare_current_track_table(con)

        rows = con.execute(
            """
            SELECT t.id
            FROM tracks t
            WHERE t.download_status IN ('pending','failed','downloading')
            ORDER BY
              CASE
                WHEN EXISTS(
                  SELECT 1
                  FROM current_download_tracks c
                  WHERE c.track_id=t.id
                ) THEN 0
                ELSE 1
              END,
              t.updated_at DESC,
              t.id
            LIMIT ?
            """,
            (max(1, min(int(limit), 5000)),),
        ).fetchall()

    return enqueue_track_ids([int(row["id"]) for row in rows])


def claim_jobs_current_first(limit: int) -> list[dict[str, Any]]:
    """Claim alle actuele hitlijsten vóór ieder historisch nummer."""
    init_download_db()
    claimed: list[dict[str, Any]] = []
    wanted = max(1, min(int(limit), 20))

    with connect() as con:
        _prepare_current_track_table(con)

        rows = con.execute(
            """
            SELECT
                j.*,
                t.artist,
                t.title,
                t.genre,
                t.spotify_album,
                t.spotify_release_date,
                t.spotify_duration_ms,
                t.spotify_isrc,
                t.spotify_artist,
                t.spotify_title,
                t.custom_search_query,
                t.youtube_url,
                t.source_track_id,
                CASE
                  WHEN EXISTS(
                    SELECT 1
                    FROM current_download_tracks c
                    WHERE c.track_id=t.id
                  ) THEN 'current'
                  ELSE 'archive'
                END AS queue_class
            FROM download_jobs j
            JOIN tracks t ON t.id=j.track_id
            WHERE j.cancel_requested=0
              AND (
                j.status='queued'
                OR (
                  j.status='waiting_retry'
                  AND (
                    j.next_attempt_at IS NULL
                    OR datetime(j.next_attempt_at)<=datetime('now')
                  )
                )
              )
            ORDER BY
              CASE
                WHEN EXISTS(
                  SELECT 1
                  FROM current_download_tracks c
                  WHERE c.track_id=t.id
                ) THEN 0
                ELSE 1
              END,
              j.updated_at,
              j.id
            LIMIT 20
            """
        ).fetchall()

        if rows:
            selected_class = str(rows[0]["queue_class"])
            rows = [
                row for row in rows
                if str(row["queue_class"]) == selected_class
            ][:wanted]

        for row in rows:
            stamp = now_iso()

            updated = con.execute(
                """
                UPDATE download_jobs
                SET status='searching',
                    started_at=COALESCE(started_at,?),
                    updated_at=?
                WHERE id=?
                  AND status IN ('queued','waiting_retry')
                  AND cancel_requested=0
                """,
                (stamp, stamp, row["id"]),
            )

            if updated.rowcount:
                item = dict(row)
                item["status"] = "searching"
                claimed.append(item)

    return claimed


def apply_current_chart_fast_retry(job: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Geef iedere actuele hitlijst de snelle retryroute."""
    if str(result.get("status") or "") != "waiting_retry":
        return result

    queue_class = str(job.get("queue_class") or "archive")

    if queue_class != "current":
        return result

    with connect() as con:
        row = con.execute(
            "SELECT attempts FROM download_jobs WHERE id=?",
            (int(job["id"]),),
        ).fetchone()

        attempts = (
            int(row["attempts"] or 0)
            if row
            else int(job.get("attempts") or 0) + 1
        )

        if attempts > CURRENT_CHART_FAST_RETRY_ATTEMPTS:
            return result

        seconds = min(
            CURRENT_TOP40_FAST_RETRY_SECONDS,
            CURRENT_TIPPARADE_FAST_RETRY_SECONDS,
        )

        next_attempt = (
            datetime.now(timezone.utc)
            + timedelta(seconds=seconds)
        ).isoformat()

        con.execute(
            """
            UPDATE download_jobs
            SET next_attempt_at=?,updated_at=?
            WHERE id=?
              AND status='waiting_retry'
            """,
            (next_attempt, now_iso(), int(job["id"])),
        )

        con.execute(
            """
            UPDATE tracks
            SET download_status='pending',updated_at=?
            WHERE id=?
              AND download_status='failed'
            """,
            (now_iso(), int(job["track_id"])),
        )

    updated = dict(result)
    updated["retry_seconds"] = seconds
    updated["fast_retry"] = True
    updated["queue_class"] = queue_class

    return updated
