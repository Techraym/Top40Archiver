from __future__ import annotations

import argparse
import re
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import quote

import requests

from .db import connect

MUSICBRAINZ_SEARCH = "https://musicbrainz.org/ws/2/recording/"
COVER_ART_RELEASE = "https://coverartarchive.org/release/{release_id}/front-500"
USER_AGENT = "Top40Archiver/1.13 (https://github.com/Techraym/Top40Archiver)"
TRANSIENT = {429, 500, 502, 503, 504}
MIN_INTERVAL = 1.35
_last_request = 0.0
_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    return " ".join(value.split())


def _clean_title(title: str) -> str:
    value = str(title or "")
    value = re.sub(r"\s*[\[(](official|offici[eë]le|lyrics?|visuali[sz]er|video|audio|radio edit|original mix).*?[\])]\s*", " ", value, flags=re.I)
    value = re.sub(r"\s*[-–—]\s*(official|offici[eë]le|lyrics?|visuali[sz]er|video|audio).*$", "", value, flags=re.I)
    return " ".join(value.split()).strip()


def _score(artist: str, title: str, recording: dict) -> float:
    wanted_artist = _norm(artist)
    wanted_title = _norm(_clean_title(title))
    found_title = _norm(recording.get("title") or "")
    credits = recording.get("artist-credit") or []
    found_artist = _norm(" ".join(str(x.get("name") or "") for x in credits if isinstance(x, dict)))
    return (
        SequenceMatcher(None, wanted_title, found_title).ratio() * 0.70
        + SequenceMatcher(None, wanted_artist, found_artist).ratio() * 0.30
    )


def _paced_get(url: str, *, params=None, timeout: int = 25, allow_redirects: bool = True) -> requests.Response:
    global _last_request
    waits = (0, 5, 15, 30, 60)
    last_error: Exception | None = None

    for wait in waits:
        if wait:
            time.sleep(wait)

        elapsed = time.monotonic() - _last_request
        if elapsed < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - elapsed)

        try:
            response = _session.get(url, params=params, timeout=timeout, allow_redirects=allow_redirects)
            _last_request = time.monotonic()

            if response.status_code in TRANSIENT:
                retry_after = response.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    time.sleep(min(int(retry_after), 120))
                last_error = requests.HTTPError(f"HTTP {response.status_code}", response=response)
                continue

            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            _last_request = time.monotonic()
            last_error = exc

    raise last_error or RuntimeError("Onbekende netwerkfout")


def lookup_cover(artist: str, title: str) -> dict[str, str]:
    clean_title = _clean_title(title)
    queries = [
        f'recording:"{clean_title}" AND artist:"{artist}"',
        f'"{clean_title}" AND "{artist}"',
    ]

    best: list[dict] = []
    for query in queries:
        response = _paced_get(
            MUSICBRAINZ_SEARCH,
            params={"query": query, "fmt": "json", "limit": 12},
        )
        recordings = list(response.json().get("recordings") or [])
        recordings.sort(key=lambda item: _score(artist, clean_title, item), reverse=True)
        best.extend(recordings[:6])
        if best and _score(artist, clean_title, best[0]) >= 0.82:
            break

    seen: set[str] = set()
    best.sort(key=lambda item: _score(artist, clean_title, item), reverse=True)

    for recording in best:
        score = _score(artist, clean_title, recording)
        if score < 0.58:
            continue

        releases = recording.get("releases") or []
        releases.sort(key=lambda item: (not bool(item.get("date")), str(item.get("date") or "9999")))

        for release in releases[:8]:
            release_id = str(release.get("id") or "").strip()
            if not release_id or release_id in seen:
                continue
            seen.add(release_id)

            url = COVER_ART_RELEASE.format(release_id=quote(release_id))
            try:
                check = _paced_get(url, timeout=20)
            except requests.HTTPError as exc:
                status = getattr(exc.response, "status_code", None)
                if status == 404:
                    continue
                raise

            content_type = str(check.headers.get("Content-Type") or "")
            if check.status_code == 200 and content_type.startswith("image/"):
                return {
                    "cover_url": url,
                    "cover_source": "cover_art_archive",
                    "musicbrainz_recording_id": str(recording.get("id") or ""),
                    "musicbrainz_release_id": release_id,
                }

    return {}


def _select_rows(limit: int, retry_current: bool) -> list:
    with connect() as con:
        latest_top = con.execute(
            "SELECT id FROM editions ORDER BY year DESC,week DESC LIMIT 1"
        ).fetchone()
        latest_tip = con.execute(
            "SELECT id FROM tipparade_editions ORDER BY year DESC,week DESC LIMIT 1"
        ).fetchone()

        top_id = int(latest_top["id"]) if latest_top else -1
        tip_id = int(latest_tip["id"]) if latest_tip else -1

        if retry_current:
            con.execute(
                """
                UPDATE tracks SET cover_checked_at=NULL
                WHERE cover_url IS NULL AND id IN (
                    SELECT track_id FROM chart_entries WHERE edition_id=?
                    UNION
                    SELECT track_id FROM tipparade_entries WHERE edition_id=?
                )
                """,
                (top_id, tip_id),
            )

        return con.execute(
            """
            SELECT t.id,t.artist,t.title,
                   CASE
                     WHEN t.id IN (SELECT track_id FROM chart_entries WHERE edition_id=?) THEN 0
                     WHEN t.id IN (SELECT track_id FROM tipparade_entries WHERE edition_id=?) THEN 1
                     ELSE 2
                   END AS priority
            FROM tracks t
            WHERE t.cover_url IS NULL
              AND (t.cover_checked_at IS NULL OR t.cover_checked_at < datetime('now','-14 days'))
            ORDER BY priority,t.updated_at DESC,t.id DESC
            LIMIT ?
            """,
            (top_id, tip_id, max(1, min(int(limit), 200))),
        ).fetchall()


def fill_missing_covers(limit: int = 40, retry_current: bool = False) -> dict[str, int]:
    rows = _select_rows(limit, retry_current)
    found = 0
    missing = 0
    transient = 0

    for row in rows:
        try:
            result = lookup_cover(row["artist"], row["title"])
        except requests.RequestException as exc:
            print(f"TIJDELIJK: {row['artist']} - {row['title']}: {exc}", flush=True)
            transient += 1
            continue

        with connect() as con:
            if result:
                con.execute(
                    """
                    UPDATE tracks
                    SET cover_url=?,cover_source=?,musicbrainz_recording_id=?,
                        musicbrainz_release_id=?,cover_checked_at=?
                    WHERE id=?
                    """,
                    (
                        result["cover_url"], result["cover_source"],
                        result["musicbrainz_recording_id"], result["musicbrainz_release_id"],
                        _now(), row["id"],
                    ),
                )
                found += 1
                print(f"GEVONDEN: {row['artist']} - {row['title']}", flush=True)
            else:
                con.execute("UPDATE tracks SET cover_checked_at=? WHERE id=?", (_now(), row["id"]))
                missing += 1
                print(f"GEEN MATCH: {row['artist']} - {row['title']}", flush=True)

    return {"processed": len(rows), "found": found, "missing": missing, "transient": transient}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--retry-current", action="store_true")
    args = parser.parse_args()
    print(fill_missing_covers(args.limit, args.retry_current), flush=True)


if __name__ == "__main__":
    main()
