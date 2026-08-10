from __future__ import annotations

import argparse
import time

from .cover_art import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_TRANSIENT_RETRY_SECONDS,
    cover_queue_count,
    drain_missing_covers,
    total_without_cover,
)
from .cover_art_state import write_cover_state

DEFAULT_POLL_SECONDS = 60


def watch_missing_covers(
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    poll_seconds: int = DEFAULT_POLL_SECONDS,
    transient_retry_seconds: int = DEFAULT_TRANSIENT_RETRY_SECONDS,
) -> None:
    """Continuously drain new cover work and then remain in low-cost watch mode."""
    poll = max(15, min(900, int(poll_seconds)))
    retry = max(15, min(900, int(transient_retry_seconds)))

    write_cover_state(
        running=True,
        phase="watching",
        queue_remaining=cover_queue_count(),
        total_without_cover=total_without_cover(),
        poll_seconds=poll,
    )

    while True:
        queued = cover_queue_count()
        if queued > 0:
            write_cover_state(
                running=True,
                phase="starting",
                queue_remaining=queued,
                total_without_cover=total_without_cover(),
                poll_seconds=poll,
            )
            # drain_missing_covers handelt tijdelijke bronfouten zelf af en keert
            # alleen terug wanneer de op dat moment verwerkbare queue leeg is.
            drain_missing_covers(
                batch_size=batch_size,
                transient_retry_seconds=retry,
            )

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
