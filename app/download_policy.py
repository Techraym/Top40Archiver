from __future__ import annotations

from typing import Any

from .db import connect, now_iso
from .download_db import enqueue_track_ids, init_download_db
from .providers import DEFAULT_PROVIDER_CONFIG

PROVIDER_ORDER_POLICY = "youtube_first_v1"
PROVIDER_POLICY_SETTING = "download_provider_order_policy"
FIRST_PROVIDER = "youtube"

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
        # Ze horen niet door te werken na deze expliciete operatorwijziging.
        con.execute(
            "UPDATE download_provider_state SET ai_priority_adjustment=0,updated_at=?",
            (stamp,),
        )

        # De eerste probe na migratie moet actuele YouTube-evidence opleveren en
        # niet worden overgeslagen door een oude cooldown uit de fallbackperiode.
        con.execute(
            """
            UPDATE download_provider_state
            SET status='healthy',consecutive_errors=0,error_window_started_at=NULL,
                cooldown_until=NULL,updated_at=?
            WHERE provider=?
            """,
            (stamp, FIRST_PROVIDER),
        )

        # Maak kandidaten die uitsluitend door een tijdelijke transportfout in het
        # verleden zijn geblokkeerd opnieuw beschikbaar voor normale retries.
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


def _latest_ids(con) -> tuple[int, int]:
    top = con.execute(
        "SELECT id FROM editions ORDER BY year DESC,week DESC LIMIT 1"
    ).fetchone()
    tip = con.execute(
        "SELECT id FROM tipparade_editions ORDER BY year DESC,week DESC LIMIT 1"
    ).fetchone()
    return (
        int(top["id"]) if top else -1,
        int(tip["id"]) if tip else -1,
    )


def enqueue_pending_tracks_current_first(limit: int = 500) -> int:
    """Enqueue fresh Top40 first, then fresh Tipparade, then historical backlog."""
    init_download_db()
    with connect() as con:
        top_id, tip_id = _latest_ids(con)
        rows = con.execute(
            """
            SELECT t.id
            FROM tracks t
            WHERE t.download_status IN ('pending','failed','downloading')
            ORDER BY
              CASE
                WHEN EXISTS(
                  SELECT 1 FROM chart_entries ce
                  WHERE ce.track_id=t.id AND ce.edition_id=?
                ) THEN 0
                WHEN EXISTS(
                  SELECT 1 FROM tipparade_entries te
                  WHERE te.track_id=t.id AND te.edition_id=?
                ) THEN 1
                ELSE 2
              END,
              t.updated_at DESC,
              t.id
            LIMIT ?
            """,
            (top_id, tip_id, max(1, min(int(limit), 5000))),
        ).fetchall()
    return enqueue_track_ids([int(row["id"]) for row in rows])


def claim_jobs_current_first(limit: int) -> list[dict[str, Any]]:
    """Claim worker slots using the same current-chart-first priority."""
    init_download_db()
    claimed: list[dict[str, Any]] = []
    with connect() as con:
        top_id, tip_id = _latest_ids(con)
        rows = con.execute(
            """
            SELECT j.*,t.artist,t.title,t.genre,t.spotify_album,t.spotify_release_date,
                   t.spotify_duration_ms,t.spotify_isrc,t.spotify_artist,t.spotify_title,
                   t.custom_search_query,t.youtube_url,
                   CASE
                     WHEN EXISTS(
                       SELECT 1 FROM chart_entries ce
                       WHERE ce.track_id=t.id AND ce.edition_id=?
                     ) THEN 'current_top40'
                     WHEN EXISTS(
                       SELECT 1 FROM tipparade_entries te
                       WHERE te.track_id=t.id AND te.edition_id=?
                     ) THEN 'current_tipparade'
                     ELSE 'archive'
                   END AS queue_class
            FROM download_jobs j
            JOIN tracks t ON t.id=j.track_id
            WHERE j.cancel_requested=0
              AND (
                j.status='queued'
                OR (
                  j.status='waiting_retry'
                  AND (j.next_attempt_at IS NULL OR datetime(j.next_attempt_at)<=datetime('now'))
                )
              )
            ORDER BY
              CASE
                WHEN EXISTS(
                  SELECT 1 FROM chart_entries ce
                  WHERE ce.track_id=t.id AND ce.edition_id=?
                ) THEN 0
                WHEN EXISTS(
                  SELECT 1 FROM tipparade_entries te
                  WHERE te.track_id=t.id AND te.edition_id=?
                ) THEN 1
                ELSE 2
              END,
              j.updated_at,
              j.id
            LIMIT ?
            """,
            (top_id, tip_id, top_id, tip_id, max(1, min(int(limit), 20))),
        ).fetchall()

        for row in rows:
            stamp = now_iso()
            updated = con.execute(
                """
                UPDATE download_jobs
                SET status='searching',started_at=COALESCE(started_at,?),updated_at=?
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
