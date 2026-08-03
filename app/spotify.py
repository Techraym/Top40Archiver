from __future__ import annotations

import base64
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
import os
import re
import threading
import time

import certifi
import requests

from .normalize import normalize

TOKEN_URL = "https://accounts.spotify.com/api/token"
SEARCH_URL = "https://api.spotify.com/v1/search"

_TOKEN_LOCK = threading.Lock()
_TOKEN_VALUE = ""
_TOKEN_EXPIRES_AT = 0.0


@dataclass
class SpotifyValidation:
    status: str
    configured: bool
    match_score: float | None = None
    spotify_id: str | None = None
    spotify_url: str | None = None
    artist: str | None = None
    title: str | None = None
    album: str | None = None
    release_date: str | None = None
    duration_ms: int | None = None
    isrc: str | None = None
    error: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def spotify_configured() -> bool:
    return bool(os.getenv("SPOTIFY_CLIENT_ID", "").strip() and os.getenv("SPOTIFY_CLIENT_SECRET", "").strip())


def _comparison(value: str) -> str:
    value = re.sub(r"\s+-\s+topic$", "", str(value or ""), flags=re.I)
    value = re.sub(
        r"\s*[\[(](?:official|offici[eë]le|video|videoclip|visual(?:iser|izer)?|audio|lyrics?|clip)[^\])]*[\])]",
        " ",
        value,
        flags=re.I,
    )
    return normalize(value)


def score_spotify_candidate(artist: str, title: str, candidate: dict) -> float:
    wanted_artist = _comparison(artist)
    wanted_title = _comparison(title)
    candidate_artists = " ".join(
        str(item.get("name") or "") for item in candidate.get("artists", []) if isinstance(item, dict)
    )
    found_artist = _comparison(candidate_artists)
    found_title = _comparison(str(candidate.get("name") or ""))
    if not found_title:
        return 0.0

    title_score = SequenceMatcher(None, wanted_title, found_title).ratio()
    artist_score = SequenceMatcher(None, wanted_artist, found_artist).ratio()
    if wanted_title and (wanted_title in found_title or found_title in wanted_title):
        title_score = max(title_score, 0.94)
    if wanted_artist and (wanted_artist in found_artist or found_artist in wanted_artist):
        artist_score = max(artist_score, 0.90)

    # Een ongevraagde live-, karaoke- of remixversie is meestal niet de hitnotering.
    wanted_flags = set(re.findall(r"\b(live|remix|acoustic|karaoke|instrumental)\b", wanted_title))
    found_flags = set(re.findall(r"\b(live|remix|acoustic|karaoke|instrumental)\b", found_title))
    penalty = 0.15 if found_flags - wanted_flags else 0.0
    return max(0.0, min(1.0, (title_score * 0.65) + (artist_score * 0.35) - penalty))


def _access_token() -> str:
    global _TOKEN_VALUE, _TOKEN_EXPIRES_AT
    now = time.time()
    with _TOKEN_LOCK:
        if _TOKEN_VALUE and now < _TOKEN_EXPIRES_AT - 30:
            return _TOKEN_VALUE

        client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
        client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            raise RuntimeError("Spotify Client ID/Secret zijn niet ingesteld")

        credentials = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
        response = requests.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "Top40Archiver/1.6",
            },
            timeout=20,
            verify=certifi.where(),
        )
        response.raise_for_status()
        payload = response.json()
        _TOKEN_VALUE = str(payload["access_token"])
        _TOKEN_EXPIRES_AT = now + int(payload.get("expires_in", 3600))
        return _TOKEN_VALUE


def _search_once(query: str, limit: int = 10) -> list[dict]:
    token = _access_token()
    response = requests.get(
        SEARCH_URL,
        params={
            "q": query,
            "type": "track",
            "market": os.getenv("SPOTIFY_MARKET", "NL").strip() or "NL",
            "limit": max(1, min(limit, 50)),
        },
        headers={"Authorization": f"Bearer {token}", "User-Agent": "Top40Archiver/1.6"},
        timeout=20,
        verify=certifi.where(),
    )
    response.raise_for_status()
    return list((response.json().get("tracks") or {}).get("items") or [])


def validate_track(artist: str, title: str, minimum_score: float = 0.70) -> SpotifyValidation:
    if not spotify_configured():
        return SpotifyValidation(status="not_configured", configured=False)

    try:
        candidates = _search_once(f'track:"{title}" artist:"{artist}"', 10)
        if not candidates:
            candidates = _search_once(f"{artist} {title}", 10)
    except Exception as exc:
        return SpotifyValidation(status="error", configured=True, error=str(exc)[-1000:])

    ranked = sorted(
        ((score_spotify_candidate(artist, title, candidate), candidate) for candidate in candidates),
        key=lambda pair: pair[0],
        reverse=True,
    )
    if not ranked:
        return SpotifyValidation(status="not_found", configured=True)

    score, item = ranked[0]
    album = item.get("album") or {}
    artists = ", ".join(
        str(value.get("name") or "") for value in item.get("artists", []) if isinstance(value, dict)
    ).strip(", ")
    external_ids = item.get("external_ids") or {}
    external_urls = item.get("external_urls") or {}
    status = "matched" if score >= minimum_score else "low_confidence"

    return SpotifyValidation(
        status=status,
        configured=True,
        match_score=round(score, 4),
        spotify_id=str(item.get("id") or "") or None,
        spotify_url=str(external_urls.get("spotify") or "") or None,
        artist=artists or None,
        title=str(item.get("name") or "") or None,
        album=str(album.get("name") or "") or None,
        release_date=str(album.get("release_date") or "") or None,
        duration_ms=int(item.get("duration_ms")) if item.get("duration_ms") is not None else None,
        isrc=str(external_ids.get("isrc") or "") or None,
    )
