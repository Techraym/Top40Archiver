import argparse

from .chart_freshness import run_freshness_check
from .db import init_db
from .download_db import init_download_db
from .download_manager import run_download_manager
from .service import (
    history_pause,
    history_start,
    import_latest,
    organize_downloaded_files,
    process_queue,
    run_download_daemon,
    run_history_batch,
)
from .spotify import spotify_configured, validate_track


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=[
            "check",
            "freshness",
            "retry",
            "download-daemon",
            "download-manager",
            "init",
            "history",
            "history-start",
            "history-pause",
            "organize",
            "spotify-test",
        ],
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--artist", default="ABBA")
    parser.add_argument("--title", default="Dancing Queen")
    args = parser.parse_args()
    init_db()
    init_download_db()

    if args.command == "check":
        print(import_latest(args.force))
    elif args.command == "freshness":
        print(run_freshness_check(args.force))
    elif args.command == "retry":
        print(process_queue(args.limit))
    elif args.command == "download-daemon":
        run_download_daemon(args.limit or 20)
    elif args.command == "download-manager":
        run_download_manager(args.limit or 20)
    elif args.command == "history":
        print(run_history_batch())
    elif args.command == "history-start":
        print(history_start(args.force))
    elif args.command == "history-pause":
        print(history_pause())
    elif args.command == "organize":
        print(organize_downloaded_files(args.limit))
    elif args.command == "spotify-test":
        print({"configured": spotify_configured(), **validate_track(args.artist, args.title).as_dict()})
    else:
        print("Database initialized")


if __name__ == "__main__":
    main()
