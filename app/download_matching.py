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

# Zonder een referentieduur mogen provider-previews nooit als volledig nummer
# worden gearchiveerd. Productiedata liet meerdere officiële SoundCloud-items
# met exact 30 seconden zien. Een charttrack korter dan 60 seconden wordt daarom
# niet autonoom geaccepteerd wanneer er geen onafhankelijke referentieduur is.
MIN_FULL_TRACK_SECONDS_WITHOUT_REFERENCE = 60.0
MAX_FULL_TRACK_SECONDS_WITHOUT_REFERENCE = 15.0 * 60.0


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


def _collaboration_clean(value: object) -> str:
    text = _clean(value)
    # Provider-titels gebruiken voor samenwerkingen door elkaar &, with, feat. en
    # featuring. normalize() zet & al om naar 'and'; maak de overige vormen gelijk.
    text = re.sub(r"\b(?:with|featuring|feat|ft)\b", "and", text)
    return " ".join(text.split())


def _ratio(wanted: object, found: object) -> float:
    left = _clean(wanted)
    right = _clean(found)
    if not left or not right:
        return 0.0
    score = SequenceMatcher(None, left, right).ratio()
    if left in right or right in left:
        score = max(score, 0.94)
    return max(0.0, min(1.0, score))


def _artist_ratio(wanted_artist: object, found_artist: object, found_title: object) -> float:
    best = _ratio(wanted_artist, found_artist)
    wanted = _collaboration_clean(wanted_artist)
    title = _collaboration_clean(found_title)
    if wanted and title and (title == wanted or title.startswith(wanted + " ")):
        # Veel yt-dlp flat-searchresultaten leveren geen artist/uploader maar wel
        # 'ARTIST - TITLE'. Dat is positief artiestbewijs en geen reden om 30
        # artiestpunten kwijt te raken.
        best = max(best, 1.0)
    return best


def _title_ratio(wanted_artist: object, wanted_title: object, found_title: object) -> float:
    best = _ratio(wanted_title, found_title)
    wanted_artist_clean = _collaboration_clean(wanted_artist)
    found = _collaboration_clean(found_title)
    if wanted_artist_clean and found.startswith(wanted_artist_clean + " "):
        stripped = found[len(wanted_artist_clean) :].strip()
        best = max(best, _ratio(wanted_title, stripped))
    return best


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

    artist_ratio = _artist_ratio(wanted_artist, found_artist, found_title)
    title_ratio = _title_ratio(wanted_artist, wanted_title, found_title)
    artist_points = 30.0 * artist_ratio
    title_points = 35.0 * title_ratio

    expected_duration = track.get("duration_seconds")
    if not expected_duration and track.get("duration_ms"):
        expected_duration = float(track["duration_ms"]) / 1000.0
    found_duration = candidate.get("duration") or candidate.get("duration_seconds")
    try:
        found_duration = float(found_duration) if found_duration is not None else None
    except (TypeError, ValueError):
        found_duration = None
    duration_points, duration_difference = _duration_points(expected_duration, found_duration)

    album_points = 0.0
    album_available = bool(track.get("album") and candidate.get("album"))
    if album_available:
        album_points = 5.0 * _ratio(track.get("album"), candidate.get("album"))

    year_available = bool(track.get("year") and (candidate.get("year") or candidate.get("release_year")))
    year_points = _year_points(track.get("year"), candidate.get("year") or candidate.get("release_year"))

    isrc_points = 0.0
    wanted_isrc = re.sub(r"\W", "", str(track.get("isrc") or "")).casefold()
    found_isrc = re.sub(r"\W", "", str(candidate.get("isrc") or "")).casefold()
    isrc_available = bool(wanted_isrc and found_isrc)
    if isrc_available and wanted_isrc == found_isrc:
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

    # Providers verschillen sterk in metadata. Ontbrekende duur/album/jaar/ISRC
    # is geen negatief bewijs en mag een exacte artiest+titel niet automatisch
    # onhaalbaar maken. Daarom normaliseren we uitsluitend over bewijsvelden die
    # beide kanten werkelijk aanleveren. Strafpunten blijven absoluut.
    available_max = 65.0
    if expected_duration and found_duration:
        available_max += 20.0
    if album_available:
        available_max += 5.0
    if year_available:
        available_max += 5.0
    if isrc_available:
        available_max += 5.0

    positive_points = artist_points + title_points + duration_points + album_points + year_points + isrc_points
    normalized_positive = 100.0 * positive_points / max(1.0, available_max)
    total = max(0.0, min(100.0, normalized_positive - penalty_points))

    components = {
        "artist": round(artist_points, 2),
        "title": round(title_points, 2),
        "duration": round(duration_points, 2),
        "album": round(album_points, 2),
        "year": round(year_points, 2),
        "isrc": round(isrc_points, 2),
        "penalty": float(-penalty_points),
        "available_max": round(available_max, 2),
        "raw_positive": round(positive_points, 2),
    }

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

    if not expected_duration and found_duration is not None:
        if found_duration < MIN_FULL_TRACK_SECONDS_WITHOUT_REFERENCE:
            return MatchDecision(
                score=round(total, 2),
                accepted=False,
                excellent=False,
                reason="preview_duration",
                duration_difference=None,
                penalties=penalties,
                components=components,
            )
        if found_duration > MAX_FULL_TRACK_SECONDS_WITHOUT_REFERENCE:
            return MatchDecision(
                score=round(total, 2),
                accepted=False,
                excellent=False,
                reason="implausible_long_duration",
                duration_difference=None,
                penalties=penalties,
                components=components,
            )

    # Als de provider geen duur meldt maar Top40Archiver wel een referentieduur
    # kent, mag alleen een zeer sterke identiteit door naar de downloadfase. De
    # echte audio wordt daarna verplicht met FFprobe tegen die duur gecontroleerd.
    strong_identity_without_provider_duration = (
        duration_difference is None
        and bool(expected_duration)
        and not penalties
        and artist_ratio >= 0.90
        and title_ratio >= 0.94
        and total >= 92
    )

    # Veel oudere Top40-records hebben helemaal geen Spotify-/referentieduur.
    # Zonder die duur accepteren we uitsluitend zeer sterke identiteit en nul
    # versie-strafpunten. ARTIST - TITLE wordt hierboven eerst provider-neutraal
    # genormaliseerd, zodat officiële YouTube-resultaten niet kunstmatig op 94%
    # titelgelijkheid blijven hangen.
    strong_identity_without_reference_duration = (
        not expected_duration
        and not penalties
        and artist_ratio >= 0.94
        and title_ratio >= 0.97
        and total >= 96
    )

    if total >= 92 and duration_difference is not None and duration_difference <= 7:
        accepted = True
        excellent = True
        reason = "excellent_match"
    elif total >= 85 and duration_difference is not None and duration_difference <= 7:
        accepted = True
        excellent = False
        reason = "good_match_duration_confirmed"
    elif strong_identity_without_provider_duration:
        accepted = True
        excellent = False
        reason = "strong_identity_verify_after_download"
    elif strong_identity_without_reference_duration:
        accepted = True
        excellent = False
        reason = "strong_identity_without_reference_duration"
    elif total >= 75:
        accepted = False
        excellent = False
        reason = "try_other_provider"
    else:
        accepted = False
        excellent = False
        reason = "low_match"

    return MatchDecision(
        score=round(total, 2),
        accepted=accepted,
        excellent=excellent,
        reason=reason,
        duration_difference=round(duration_difference, 2) if duration_difference is not None else None,
        penalties=penalties,
        components=components,
    )
