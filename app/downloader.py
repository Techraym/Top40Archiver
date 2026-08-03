from __future__ import annotations

from difflib import SequenceMatcher
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from .config import DATA_DIR
from .metadata import clean_genre, track_relative_path
from .normalize import normalize


class DownloadError(RuntimeError):
    pass


def _copy_completed_file(source: Path, destination: Path) -> None:
    """Copy without preserving timestamps; this is reliable on NTFS media."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with source.open("rb") as src, destination.open("wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def _yt_executable() -> Path:
    yt = Path(sys.executable).with_name("yt-dlp")
    if not yt.exists():
        raise DownloadError(f"yt-dlp niet gevonden: {yt}")
    return yt


def _runtime_args() -> list[str]:
    deno = Path("/usr/local/bin/deno")
    if not deno.exists():
        return []
    return [
        "--js-runtimes",
        f"deno:{deno}",
        "--remote-components",
        "ejs:github",
    ]


def _comparison(value: str) -> str:
    value = re.sub(r"\s+-\s+topic$", "", str(value or ""), flags=re.I)
    value = re.sub(
        r"\s*[\[(](?:official|offici[eë]le|music|video|videoclip|visual(?:iser|izer)?|audio|lyrics?|clip|hd|4k)[^\])]*[\])]",
        " ",
        value,
        flags=re.I,
    )
    return normalize(value)


def _candidate_score(
    artist: str,
    title: str,
    candidate: dict,
    spotify_duration_ms: int | None,
) -> float:
    raw_title = str(candidate.get("title") or "")
    channel = str(candidate.get("channel") or candidate.get("uploader") or "")
    wanted_artist = _comparison(artist)
    wanted_title = _comparison(title)
    found_title = _comparison(raw_title)
    found_channel = _comparison(channel)

    title_score = SequenceMatcher(None, wanted_title, found_title).ratio()
    artist_score = max(
        SequenceMatcher(None, wanted_artist, found_title).ratio(),
        SequenceMatcher(None, wanted_artist, found_channel).ratio(),
    )
    if wanted_title and wanted_title in found_title:
        title_score = max(title_score, 0.96)
    if wanted_artist and (wanted_artist in found_title or wanted_artist in found_channel):
        artist_score = max(artist_score, 0.92)

    score = (title_score * 0.62) + (artist_score * 0.30)
    raw_lower = f"{raw_title} {channel}".casefold()
    if "official audio" in raw_lower or channel.casefold().endswith(" - topic"):
        score += 0.08
    elif "official" in raw_lower:
        score += 0.04

    wanted_flags = set(re.findall(r"\b(live|remix|acoustic|karaoke|instrumental|sped up|slowed)\b", wanted_title))
    found_flags = set(re.findall(r"\b(live|remix|acoustic|karaoke|instrumental|sped up|slowed)\b", found_title))
    if found_flags - wanted_flags:
        score -= 0.22

    duration = candidate.get("duration")
    if spotify_duration_ms and duration:
        expected = spotify_duration_ms / 1000.0
        difference = abs(float(duration) - expected)
        if difference <= 5:
            score += 0.08
        elif difference <= 12:
            score += 0.04
        elif difference > 45:
            score -= 0.18

    return max(0.0, min(1.0, score))


def _search_youtube(
    artist: str,
    title: str,
    query: str,
    spotify_duration_ms: int | None,
    timeout: int,
) -> dict:
    yt = _yt_executable()
    cmd = [
        str(yt),
        "--ignore-config",
        "--skip-download",
        "--dump-single-json",
        "--flat-playlist",
        "--playlist-end",
        "5",
        "--socket-timeout",
        "30",
        *_runtime_args(),
        f"ytsearch5:{query}",
    ]
    process = subprocess.run(cmd, text=True, capture_output=True, timeout=min(timeout, 300))
    if process.returncode != 0:
        raise DownloadError((process.stderr or process.stdout or "YouTube-zoekfout")[-3000:])
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise DownloadError(f"YouTube-zoekresultaten waren geen geldige JSON: {exc}") from exc

    entries = [item for item in payload.get("entries", []) if item]
    if not entries:
        raise DownloadError(f"Geen YouTube-resultaten voor: {query}")
    ranked = sorted(
        (
            (_candidate_score(artist, title, item, spotify_duration_ms), item)
            for item in entries
        ),
        key=lambda pair: pair[0],
        reverse=True,
    )
    score, selected = ranked[0]
    if score < 0.50:
        raise DownloadError(
            f"Geen betrouwbaar YouTube-resultaat gevonden voor '{artist} - {title}' "
            f"(beste score {score:.2f})"
        )
    video_id = str(selected.get("id") or "").strip()
    url = str(selected.get("webpage_url") or selected.get("url") or "").strip()
    if video_id and not url.startswith("http"):
        url = f"https://www.youtube.com/watch?v={video_id}"
    if not url.startswith("http"):
        raise DownloadError("YouTube-resultaat bevat geen bruikbare URL")
    return {
        "url": url,
        "score": round(score, 4),
        "channel": str(selected.get("channel") or selected.get("uploader") or "") or None,
        "duration": int(selected.get("duration")) if selected.get("duration") else None,
    }


def download_track(
    artist: str,
    title: str,
    query: str,
    download_dir: str,
    source_url: str | None = None,
    genre: str | None = None,
    spotify_duration_ms: int | None = None,
    timeout: int = 1200,
) -> dict[str, str | int | float | None]:
    base = Path(download_dir).expanduser()
    base.mkdir(parents=True, exist_ok=True)

    genre_name = clean_genre(genre)
    relative_path = track_relative_path(genre_name, artist, title)
    final = base / relative_path
    final.parent.mkdir(parents=True, exist_ok=True)

    if final.exists() and final.stat().st_size > 0:
        return {
            "url": source_url,
            "filename": relative_path.as_posix(),
            "genre": genre_name,
            "youtube_match_score": None,
            "youtube_channel": None,
            "youtube_duration_seconds": None,
        }

    selected = {
        "url": source_url,
        "score": None,
        "channel": None,
        "duration": None,
    }
    if not source_url:
        selected = _search_youtube(artist, title, query, spotify_duration_ms, timeout)

    yt = _yt_executable()
    temp_root = DATA_DIR / "download-temp"
    temp_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="track-", dir=temp_root) as td:
        temp = Path(td)
        out = str(temp / "audio.%(ext)s")
        cmd = [
            str(yt),
            "--ignore-config",
            "--no-playlist",
            "--no-overwrites",
            "--extract-audio",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
            "--print",
            "after_move:webpage_url",
            "--output",
            out,
            *_runtime_args(),
            str(selected["url"]),
        ]
        process = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
        made = list(temp.glob("*.mp3"))
        if process.returncode != 0 or not made or made[0].stat().st_size == 0:
            raise DownloadError((process.stderr or process.stdout or "Onbekende yt-dlp-fout")[-3000:])

        _copy_completed_file(made[0], final)
        if not final.exists() or final.stat().st_size == 0:
            raise DownloadError("MP3 kon niet naar de downloadmap worden gekopieerd")

        resolved_url = next(
            (
                line.strip()
                for line in reversed(process.stdout.splitlines())
                if line.strip().startswith("http")
            ),
            str(selected["url"]),
        )
        return {
            "url": resolved_url,
            "filename": relative_path.as_posix(),
            "genre": genre_name,
            "youtube_match_score": selected["score"],
            "youtube_channel": selected["channel"],
            "youtube_duration_seconds": selected["duration"],
        }
