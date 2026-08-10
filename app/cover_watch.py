from __future__ import annotations

import argparse
import threading
import time

from .cover_art import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_TRANSIENT_RETRY_SECONDS,
    cover_queue_count,
    drain_missing_covers,
    total_without_cover,
)
from .cover_art_state import write_cover_state
from .db import connect

DEFAULT_POLL_SECONDS = 60
PROGRESS_REPORT_SECONDS = 2


def _current_chart_signature() -> tuple[int, int]:
    with connect() as con:
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


def _requeue_current_chart_covers(signature: tuple[int, int]) -> int:
    """Give missing covers in the newest Top40/Tipparade an immediate fresh lookup."""
    top_id, tip_id = signature
    with connect() as con:
        cursor = con.execute(
            """
            UPDATE tracks
            SET cover_checked_at=NULL
            WHERE cover_url IS NULL
              AND id IN (
                SELECT track_id FROM chart_entries WHERE edition_id=?
                UNION
                SELECT track_id FROM tipparade_entries WHERE edition_id=?
              )
            """,
            (top_id, tip_id),
        )
        return int(cursor.rowcount or 0)


def _cover_progress_counts() -> dict[str, int]:
    with connect() as con:
        row = con.execute(
            """
            SELECT
              SUM(CASE WHEN cover_url IS NOT NULL THEN 1 ELSE 0 END) AS found,
              SUM(CASE WHEN cover_checked_at IS NOT NULL THEN 1 ELSE 0 END) AS checked
            FROM tracks
            """
        ).fetchone()
    return {
        "found": int(row["found"] or 0) if row else 0,
        "checked": int(row["checked"] or 0) if row else 0,
    }


def _run_drain_with_live_progress(*, batch_size: int, retry: int) -> None:
    """Keep cover_state counters live while cover_art is inside a 40-track batch."""
    baseline = _cover_progress_counts()
    started = time.monotonic()
    stop = threading.Event()

    def reporter() -> None:
        while not stop.wait(PROGRESS_REPORT_SECONDS):
            try:
                current = _cover_progress_counts()
                found = max(0, current["found"] - baseline["found"])
                processed = max(found, current["checked"] - baseline["checked"])
                missing = max(0, processed - found)
                elapsed = max(0.001, time.monotonic() - started)
                write_cover_state(
                    running=True,
                    phase="processing",
                    processed_total=processed,
                    found_total=found,
                    missing_total=missing,
                    queue_remaining=cover_queue_count(),
                    total_without_cover=total_without_cover(),
                    per_minute=round(processed / elapsed * 60, 2),
                )
            except Exception:
                # Progress telemetry may never stop the actual cover worker.
                pass

    thread = threading.Thread(
        target=reporter,
        name="cover-progress-reporter",
        daemon=True,
    )
    thread.start()
    try:
        drain_missing_covers(
            batch_size=batch_size,
            transient_retry_seconds=retry,
        )
    finally:
        stop.set()
        thread.join(timeout=3)


def watch_missing_covers(
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    poll_seconds: int = DEFAULT_POLL_SECONDS,
    transient_retry_seconds: int = DEFAULT_TRANSIENT_RETRY_SECONDS,
) -> None:
    """Continuously drain new cover work and then remain in low-cost watch mode."""
    poll = max(15, min(900, int(poll_seconds)))
    retry = max(15, min(900, int(transient_retry_seconds)))
    last_chart_signature: tuple[int, int] | None = None

    write_cover_state(
        running=True,
        phase="watching",
        queue_remaining=cover_queue_count(),
        total_without_cover=total_without_cover(),
        poll_seconds=poll,
    )

    while True:
        signature = _current_chart_signature()
        if signature != last_chart_signature:
            requeued = _requeue_current_chart_covers(signature)
            last_chart_signature = signature
            write_cover_state(
                current_chart_signature=list(signature),
                current_chart_requeued=requeued,
            )

        queued = cover_queue_count()
        if queued > 0:
            write_cover_state(
                running=True,
                phase="starting",
                queue_remaining=queued,
                total_without_cover=total_without_cover(),
                processed_total=0,
                found_total=0,
                missing_total=0,
                transient_total=0,
                batches=0,
                per_minute=0.0,
                poll_seconds=poll,
            )
            _run_drain_with_live_progress(batch_size=batch_size, retry=retry)

        write_cover_state(
            running=True,
            phase="watching",
            current_id=None,
            current_artist=None,
            current_title=None,
            queue_remaining=cover_queue_count(),
            total_without_cover=total_without_cover(),
            retry_in_seconds=None,
            poll_seconds=poll,
            current_chart_signature=list(last_chart_signature or (-1, -1)),
        )
        time.sleep(poll)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS)
    parser.add_argument(
        "--transient-retry-seconds",
        type=int,
        default=DEFAULT_TRANSIENT_RETRY_SECONDS,
    )
    args = parser.parse_args()
    watch_missing_covers(
        batch_size=max(1, min(200, int(args.limit))),
        poll_seconds=args.poll_seconds,
        transient_retry_seconds=args.transient_retry_seconds,
    )


if __name__ == "__main__":
    main()
