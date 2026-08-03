import argparse

from .db import init_db
from .service import (
    history_pause,
    history_start,
    import_latest,
    organize_downloaded_files,
    process_queue,
    run_history_batch,
)
from .spotify import spotify_configured, validate_track


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=[
            "check",
            "retry",
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

    if args.command == "check":
        print(import_latest(args.force))
    elif args.command == "retry":
        print(process_queue(args.limit))
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
