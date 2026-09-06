from __future__ import annotations

import fcntl
from pathlib import Path

from app.db import connect, now_iso
from app.download_manager import _track_context
from app.download_recovery_duration import (
    consensus_for_track,
    save_recovery_duration_evidence,
)


MIN_ATTEMPTS = 3
LOCK_PATH = Path(
    "/var/lib/top40-archiver/.duration-recovery.lock"
)


def candidate_urls(evidence: dict) -> list[str]:
    return sorted(
        {
            str(item.get("url") or "").strip()
            for item in evidence.get("best_items", [])
            if str(item.get("url") or "").strip()
        }
    )


def main() -> None:
    LOCK_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with LOCK_PATH.open("a+") as lock:
        try:
            fcntl.flock(
                lock.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError:
            print(
                "duration-recovery: "
                "andere run is nog actief"
            )
            return

        with connect() as con:
            rows = con.execute(
                """
                SELECT
                    j.*,
                    t.artist,
                    t.title,
                    t.spotify_album,
                    t.spotify_release_date,
                    t.spotify_duration_ms,
                    t.spotify_isrc,
                    t.spotify_artist,
                    t.spotify_title,
                    t.custom_search_query,
                    t.source_track_id
                FROM download_jobs j
                JOIN tracks t
                  ON t.id=j.track_id
                LEFT JOIN
                    download_recovery_duration_evidence e
                  ON e.track_id=t.id
                WHERE t.download_status='pending'
                  AND t.spotify_duration_ms IS NULL
                  AND e.track_id IS NULL
                  AND j.cancel_requested=0
                  AND j.attempts >= ?
                  AND j.status IN (
                      'queued',
                      'waiting_retry'
                  )
                ORDER BY
                    j.attempts DESC,
                    t.id ASC
                """,
                (MIN_ATTEMPTS,),
            ).fetchall()

        print(
            "duration-recovery: "
            f"onderzoeken={len(rows)}"
        )

        selected = []
        errors = 0

        for number, row in enumerate(rows, 1):
            try:
                track = _track_context(dict(row))

                # Consensus moet volledig onafhankelijk
                # van een reeds bekende referentieduur
                # worden vastgesteld.
                track["duration_ms"] = None
                track["duration_seconds"] = None
                track["duration_source"] = None

                evidence = consensus_for_track(track)

                if not evidence:
                    continue

                if evidence.get("strict") is not True:
                    continue

                urls = candidate_urls(evidence)

                if not urls:
                    continue

                track_id = int(track["track_id"])

                save_recovery_duration_evidence(
                    track_id,
                    evidence,
                )

                selected.append(
                    {
                        "track_id": track_id,
                        "artist": track.get("artist"),
                        "title": track.get("title"),
                        "duration": float(
                            evidence["duration_seconds"]
                        ),
                        "url_count": int(
                            evidence["url_count"]
                        ),
                        "source_count": int(
                            evidence["source_count"]
                        ),
                        "urls": urls,
                    }
                )

            except Exception as exc:
                errors += 1
                print(
                    "duration-recovery ERROR "
                    f"track={row['track_id']}: "
                    f"{exc!r}"
                )

            if number % 250 == 0:
                print(
                    "duration-recovery: "
                    f"onderzocht={number} "
                    f"strict={len(selected)} "
                    f"errors={errors}"
                )

        removed = 0
        prioritized = 0

        with connect() as con:
            for item in selected:
                track_id = item["track_id"]
                urls = item["urls"]

                marks = ",".join(
                    "?" for _ in urls
                )

                # Alleen oude matcher-rejections
                # van expliciet goedgekeurde
                # consensus-URL's verwijderen.
                cur = con.execute(
                    f"""
                    DELETE FROM rejected_candidates
                    WHERE track_id=?
                      AND candidate_url IN ({marks})
                      AND (
                           reason LIKE '%low_match%'
                        OR reason LIKE
                           '%try_other_provider%'
                      )
                    """,
                    [track_id, *urls],
                )

                removed += cur.rowcount

                cur = con.execute(
                    """
                    UPDATE download_jobs
                    SET
                        next_attempt_at=?,
                        updated_at=
                          '1970-01-01T00:00:00+00:00'
                    WHERE track_id=?
                      AND cancel_requested=0
                      AND status IN (
                          'queued',
                          'waiting_retry'
                      )
                      AND EXISTS (
                          SELECT 1
                          FROM tracks t
                          WHERE t.id=download_jobs.track_id
                            AND
                            t.download_status='pending'
                      )
                    """,
                    (
                        now_iso(),
                        track_id,
                    ),
                )

                prioritized += cur.rowcount

        print()
        print(
            "duration-recovery RESULT:"
        )
        print(
            " strict_saved=",
            len(selected),
        )
        print(
            " soft_rejections_removed=",
            removed,
        )
        print(
            " jobs_prioritized=",
            prioritized,
        )
        print(
            " errors=",
            errors,
        )

        if selected:
            print()
            print(
                "Nieuwe consensus-tracks:"
            )

            for item in selected[:20]:
                print(
                    item["track_id"],
                    item["artist"],
                    "-",
                    item["title"],
                    "| duration=",
                    item["duration"],
                    "| urls=",
                    item["url_count"],
                    "| sources=",
                    item["source_count"],
                )


if __name__ == "__main__":
    main()
