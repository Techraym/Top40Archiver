from __future__ import annotations

from difflib import SequenceMatcher
import fcntl
import re
import time
import unicodedata
from pathlib import Path

import certifi
import requests

from .config import DATA_DIR
from .normalize import normalize, safe_filename

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
ITUNES_REQUEST_INTERVAL = 3.2
UNKNOWN_GENRE = "Onbekend"

_GENRE_ALIASES = {
    "hip-hop/rap": "Hip-Hop & Rap",
    "hip hop/rap": "Hip-Hop & Rap",
    "r&b/soul": "R&B & Soul",
    "r&b / soul": "R&B & Soul",
    "singer/songwriter": "Singer-Songwriter",
    "children's music": "Children's Music",
    "christian & gospel": "Christian & Gospel",
}


def clean_genre(value: str | None) -> str:
    raw = re.sub(r"\s+", " ", str(value or "")).strip()
    if not raw:
        return UNKNOWN_GENRE
    canonical = _GENRE_ALIASES.get(raw.casefold(), raw)
    canonical = canonical.replace("/", " & ")
    canonical = re.sub(r"\s+", " ", canonical).strip()
    cleaned = safe_filename(canonical, max_len=80).strip(" .")
    return cleaned or UNKNOWN_GENRE


def artist_bucket(artist: str) -> str:
    """Return the first sortable letter, digit or safe symbol of an artist name."""
    value = str(artist or "").strip()
    if not value:
        return "TEKEN"

    first = value[0]
    decomposed = unicodedata.normalize("NFKD", first)
    ascii_first = next(
        (
            char
            for char in decomposed
            if ord(char) < 128 and not unicodedata.combining(char)
        ),
        "",
    )
    candidate = ascii_first or first

    if candidate.isalpha():
        return candidate.upper()
    if candidate.isdigit():
        return candidate

    # These symbols are safe as a single NTFS/Linux directory name.
    if candidate in "!#$%&()+,-.;=@[]^_{}~":
        return candidate
    return "TEKEN"


def track_relative_path(genre: str | None, artist: str, title: str) -> Path:
    genre_folder = clean_genre(genre)
    bucket = artist_bucket(artist)
    filename = f"{safe_filename(f'{artist} - {title}')}.mp3"
    return Path(genre_folder) / bucket / filename


def _comparison_title(value: str) -> str:
    value = re.sub(r"\s+-\s+topic$", "", str(value or ""), flags=re.I)
    value = re.sub(
        r"\s*[\[(](?:official|offici[eë]le|video|videoclip|visual(?:iser|izer)?|audio|lyrics?|clip)[^\])]*[\])]",
        " ",
        value,
        flags=re.I,
    )
    return normalize(value)


def _candidate_score(artist: str, title: str, candidate: dict) -> float:
    wanted_artist = normalize(re.sub(r"\s+-\s+topic$", "", artist, flags=re.I))
    wanted_title = _comparison_title(title)
    found_artist = normalize(str(candidate.get("artistName") or ""))
    found_title = _comparison_title(str(candidate.get("trackName") or ""))
    if not found_title:
        return 0.0

    artist_score = SequenceMatcher(None, wanted_artist, found_artist).ratio()
    title_score = SequenceMatcher(None, wanted_title, found_title).ratio()
    if wanted_title and (wanted_title in found_title or found_title in wanted_title):
        title_score = max(title_score, 0.92)
    if wanted_artist and (wanted_artist in found_artist or found_artist in wanted_artist):
        artist_score = max(artist_score, 0.88)
    return (title_score * 0.65) + (artist_score * 0.35)


def _rate_limited_itunes_request(params: dict[str, str | int]) -> requests.Response:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = DATA_DIR / "itunes-search.lock"
    stamp_path = DATA_DIR / "itunes-search.last"

    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        last = 0.0
        try:
            last = float(stamp_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pass
        wait = ITUNES_REQUEST_INTERVAL - (time.time() - last)
        if wait > 0:
            time.sleep(wait)

        try:
            response = requests.get(
                ITUNES_SEARCH_URL,
                params=params,
                timeout=20,
                verify=certifi.where(),
                headers={"User-Agent": "Top40Archiver/1.5 (+personal archive)"},
            )
            return response
        finally:
            stamp_path.write_text(str(time.time()), encoding="utf-8")
            fcntl.flock(lock, fcntl.LOCK_UN)


def resolve_genre(artist: str, title: str) -> str:
    """Resolve a broad store genre. Network failures fall back to Onbekend."""
    try:
        response = _rate_limited_itunes_request(
            {
                "term": f"{artist} {title}",
                "country": "NL",
                "media": "music",
                "entity": "song",
                "limit": 10,
            }
        )
        response.raise_for_status()
        results = response.json().get("results", [])
    except Exception:
        return UNKNOWN_GENRE

    ranked = sorted(
        ((float(_candidate_score(artist, title, item)), item) for item in results),
        key=lambda pair: pair[0],
        reverse=True,
    )
    if not ranked or ranked[0][0] < 0.54:
        return UNKNOWN_GENRE
    return clean_genre(ranked[0][1].get("primaryGenreName"))
