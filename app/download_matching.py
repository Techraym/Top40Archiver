from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import Any

from .normalize import normalize


VERSION_PENALTIES: tuple[tuple[str, int], ...] = (
    ("karaoke", 50),
    ("cover", 40),
    ("tribute", 40),
    ("nightcore", 40),
    ("sped up", 35),
    ("sped-up", 35),
    ("slowed", 35),
    ("instrumental", 30),
    ("live", 25),
    ("remix", 20),
    ("radio edit", 10),
)


@dataclass(frozen=True)
class MatchDecision:
    score: float
    accepted: bool
    excellent: bool
    reason: str
    duration_difference: float | None
    penalties: list[dict[str, Any]]
    components: dict[str, float]


def _clean(value: object) -> str:
    text = str(value or "")
    text = re.sub(r"\s+-\s+topic$", "", text, flags=re.I)
    text = re.sub(
        r"\s*[\[(](?:official|offici[eë]le|music|video|videoclip|visual(?:iser|izer)?|audio|lyrics?|clip|hd|4k)[^\])]*[\])]",
        " ",
        text,
        flags=re.I,
    )
    return normalize(text)


def _ratio(wanted: object, found: object) -> float:
    left = _clean(wanted)
    right = _clean(found)
    if not left or not right:
        return 0.0
    score = SequenceMatcher(None, left, right).ratio()
    if left in right or right in left:
        score = max(score, 0.94)
    return max(0.0, min(1.0, score))


def _duration_points(expected_seconds: float | None, found_seconds: float | None) -> tuple[float, float | None]:
    if not expected_seconds or not found_seconds:
        return 0.0, None
    difference = abs(float(found_seconds) - float(expected_seconds))
    if difference <= 3:
        return 20.0, difference
    if difference <= 7:
        return 16.0, difference
    if difference <= 15:
        return 8.0, difference
    return 0.0, difference


def _year_points(expected: int | None, found: int | None) -> float:
    if not expected or not found:
        return 0.0
    difference = abs(int(expected) - int(found))
    if difference == 0:
        return 5.0
    if difference == 1:
        return 3.0
    return 0.0


def score_candidate(track: dict[str, Any], candidate: dict[str, Any]) -> MatchDecision:
    wanted_artist = track.get("artist")
    wanted_title = track.get("title")
    found_artist = candidate.get("artist") or candidate.get("uploader") or candidate.get("channel")
    found_title = candidate.get("title") or candidate.get("track")

    artist_points = 30.0 * _ratio(wanted_artist, found_artist or f"{found_artist or ''} {found_title or ''}")
    title_points = 35.0 * _ratio(wanted_title, found_title)

    expected_duration = track.get("duration_seconds")
    if not expected_duration and track.get("duration_ms"):
        expected_duration = float(track["duration_ms"]) / 1000.0
    found_duration = candidate.get("duration") or candidate.get("duration_seconds")
    duration_points, duration_difference = _duration_points(expected_duration, found_duration)

    album_points = 0.0
    if track.get("album") and candidate.get("album"):
        album_points = 5.0 * _ratio(track.get("album"), candidate.get("album"))

    year_points = _year_points(track.get("year"), candidate.get("year") or candidate.get("release_year"))

    isrc_points = 0.0
    wanted_isrc = re.sub(r"\W", "", str(track.get("isrc") or "")).casefold()
    found_isrc = re.sub(r"\W", "", str(candidate.get("isrc") or "")).casefold()
    if wanted_isrc and found_isrc and wanted_isrc == found_isrc:
        isrc_points = 5.0

    raw = " ".join(
        str(candidate.get(key) or "")
        for key in ("title", "artist", "album", "description", "uploader", "channel")
    ).casefold()
    wanted_raw = f"{wanted_artist or ''} {wanted_title or ''} {track.get('album') or ''}".casefold()
    penalties: list[dict[str, Any]] = []
    penalty_points = 0
    for marker, value in VERSION_PENALTIES:
        if marker in raw and marker not in wanted_raw:
            penalty_points += value
            penalties.append({"marker": marker, "points": -value})

    components = {
        "artist": round(artist_points, 2),
        "title": round(title_points, 2),
        "duration": round(duration_points, 2),
        "album": round(album_points, 2),
        "year": round(year_points, 2),
        "isrc": round(isrc_points, 2),
        "penalty": float(-penalty_points),
    }
    total = max(0.0, min(100.0, sum(components.values())))

    if duration_difference is not None and duration_difference > 15:
        return MatchDecision(
            score=round(total, 2),
            accepted=False,
            excellent=False,
            reason="wrong_duration",
            duration_difference=round(duration_difference, 2),
            penalties=penalties,
            components=components,
        )

    if total >= 92:
        accepted = True
        reason = "excellent_match"
    elif total >= 85 and duration_difference is not None and duration_difference <= 7:
        accepted = True
        reason = "good_match_duration_confirmed"
    elif total >= 75:
        accepted = False
        reason = "try_other_provider"
    else:
        accepted = False
        reason = "low_match"

    return MatchDecision(
        score=round(total, 2),
        accepted=accepted,
        excellent=total >= 92,
        reason=reason,
        duration_difference=round(duration_difference, 2) if duration_difference is not None else None,
        penalties=penalties,
        components=components,
    )
