from __future__ import annotations

import fcntl
from pathlib import Path
import shutil
from typing import Iterable

from .config import DATA_DIR
from .db import connect, get_settings, now_iso
from .downloader import download_track
from .metadata import UNKNOWN_GENRE, clean_genre, resolve_genre, track_relative_path
from .spotify import spotify_configured, validate_track

LOCK = DATA_DIR / "worker.lock"


def _save_spotify_validation(track_id: int, result: dict) -> None:
    with connect() as con:
        con.execute(
            """
            UPDATE tracks
            SET spotify_status=?,spotify_match_score=?,spotify_id=?,spotify_url=?,
                spotify_artist=?,spotify_title=?,spotify_album=?,spotify_release_date=?,
                spotify_duration_ms=?,spotify_isrc=?,spotify_checked_at=?,updated_at=?
            WHERE id=?
            """,
            (
                result.get("status") or "error",
                result.get("match_score"),
                result.get("spotify_id"),
                result.get("spotify_url"),
                result.get("artist"),
                result.get("title"),
                result.get("album"),
                result.get("release_date"),
                result.get("duration_ms"),
                result.get("isrc"),
                now_iso(),
                now_iso(),
                track_id,
            ),
        )


def process_queue(limit: int | None = None, track_ids: Iterable[int] | None = None):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return [{"busy": True}]

        requested_ids = sorted({int(value) for value in track_ids or [] if int(value) > 0})
        with connect() as con:
            settings = get_settings(con)
            max_attempts = int(settings["max_download_attempts"])
            sql = (
                "SELECT * FROM tracks WHERE download_status!='downloaded' "
                "AND download_attempts<?"
            )
            params: list[object] = [max_attempts]
            if track_ids is not None:
                if not requested_ids:
                    return []
                placeholders = ",".join("?" for _ in requested_ids)
                sql += f" AND id IN ({placeholders})"
                params.extend(requested_ids)
            sql += " ORDER BY id"
            rows = con.execute(sql, params).fetchall()

        if limit is not None:
            rows = rows[: max(0, int(limit))]

        results = []
        spotify_enabled = (
            settings.get("spotify_validation_enabled", "1") == "1" and spotify_configured()
        )
        minimum_score = float(settings.get("spotify_min_match_score", "0.70"))

        for row in rows:
            query = row["custom_search_query"] or settings["search_template"].format(
                artist=row["artist"], title=row["title"]
            )
            with connect() as con:
                con.execute(
                    """
                    UPDATE tracks
                    SET download_status='downloading',download_attempts=download_attempts+1,
                        error_message=NULL,updated_at=?
                    WHERE id=?
                    """,
                    (now_iso(), row["id"]),
                )

            try:
                spotify_duration_ms = row["spotify_duration_ms"]
                if spotify_enabled and row["spotify_status"] in {
                    None,
                    "",
                    "unchecked",
                    "error",
                    "not_configured",
                }:
                    validation = validate_track(row["artist"], row["title"], minimum_score)
                    validation_dict = validation.as_dict()
                    _save_spotify_validation(int(row["id"]), validation_dict)
                    spotify_duration_ms = validation.duration_ms
                elif not spotify_configured() and row["spotify_status"] == "unchecked":
                    _save_spotify_validation(
                        int(row["id"]),
                        {"status": "not_configured"},
                    )

                genre = (
                    clean_genre(row["genre"])
                    if row["genre"] and clean_genre(row["genre"]) != UNKNOWN_GENRE
                    else resolve_genre(row["artist"], row["title"])
                )
                with connect() as con:
                    con.execute(
                        "UPDATE tracks SET genre=?,updated_at=? WHERE id=?",
                        (genre, now_iso(), row["id"]),
                    )

                result = download_track(
                    row["artist"],
                    row["title"],
                    query,
                    settings["download_dir"],
                    None if row["custom_search_query"] else row["youtube_url"],
                    genre=genre,
                    spotify_duration_ms=spotify_duration_ms,
                )
                with connect() as con:
                    con.execute(
                        """
                        UPDATE tracks
                        SET download_status='downloaded',youtube_url=COALESCE(?,youtube_url),
                            genre=?,mp3_filename=?,error_message=NULL,processed_at=?,updated_at=?,
                            youtube_match_score=?,youtube_channel=?,youtube_duration_seconds=?
                        WHERE id=?
                        """,
                        (
                            result["url"],
                            result["genre"],
                            result["filename"],
                            now_iso(),
                            now_iso(),
                            result.get("youtube_match_score"),
                            result.get("youtube_channel"),
                            result.get("youtube_duration_seconds"),
                            row["id"],
                        ),
                    )
                results.append((row["id"], "downloaded"))
            except Exception as exc:
                with connect() as con:
                    con.execute(
                        """
                        UPDATE tracks
                        SET download_status='failed',error_message=?,updated_at=?
                        WHERE id=?
                        """,
                        (str(exc)[-3000:], now_iso(), row["id"]),
                    )
                results.append((row["id"], "failed"))
        return results


def organize_downloaded_files(limit=None):
    """Move existing local MP3 files into Genre/initial/ without changing status."""
    with connect() as con:
        settings = get_settings(con)
        rows = con.execute(
            """
            SELECT * FROM tracks
            WHERE download_status='downloaded' AND mp3_filename IS NOT NULL
            ORDER BY id
            """
        ).fetchall()
    if limit is not None:
        rows = rows[: max(0, int(limit))]

    base = Path(settings["download_dir"]).expanduser()
    moved = already = missing = failed = 0

    for row in rows:
        try:
            genre = (
                clean_genre(row["genre"])
                if row["genre"] and clean_genre(row["genre"]) != UNKNOWN_GENRE
                else resolve_genre(row["artist"], row["title"])
            )
            relative = track_relative_path(genre, row["artist"], row["title"])
            destination = base / relative
            stored = Path(str(row["mp3_filename"]))
            candidates = [base / stored]
            flat_candidate = base / stored.name
            if flat_candidate not in candidates:
                candidates.append(flat_candidate)
            source = next((item for item in candidates if item.exists() and item.is_file()), None)

            if destination.exists() and destination.stat().st_size > 0:
                already += 1
            elif source is None:
                missing += 1
                with connect() as con:
                    con.execute(
                        "UPDATE tracks SET genre=?,updated_at=? WHERE id=?",
                        (genre, now_iso(), row["id"]),
                    )
                continue
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                if source.resolve() != destination.resolve():
                    shutil.copyfile(source, destination)
                    if not destination.exists() or destination.stat().st_size == 0:
                        destination.unlink(missing_ok=True)
                        raise RuntimeError("Verplaatsen naar de genre-map is mislukt")
                    source.unlink()
                moved += 1

            with connect() as con:
                con.execute(
                    "UPDATE tracks SET genre=?,mp3_filename=?,updated_at=? WHERE id=?",
                    (genre, relative.as_posix(), now_iso(), row["id"]),
                )
        except Exception:
            failed += 1

    return {"moved": moved, "already": already, "missing": missing, "failed": failed}
