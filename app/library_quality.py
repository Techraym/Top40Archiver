from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import io
import json
import math
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import requests

from .config import DATA_DIR
from .db import connect, get_settings, now_iso

try:
    from .cover_art import lookup_cover
except Exception:  # pragma: no cover - keep scanner usable when cover service is unavailable
    lookup_cover = None

try:
    from .top40_cover_backfill import process_edition as top40_process_edition
except Exception:  # pragma: no cover - old installs remain usable without the backfill module
    top40_process_edition = None

try:
    from .metadata import UNKNOWN_GENRE, clean_genre, resolve_genre
except Exception:  # pragma: no cover - defensive compatibility
    UNKNOWN_GENRE = "Other"

    def clean_genre(value: str | None) -> str:
        return str(value or "Other").strip() or "Other"

    def resolve_genre(artist: str, title: str) -> str:
        return "Other"


SUPPORTED_SUFFIXES = {".mp3", ".flac", ".m4a", ".mp4", ".aac", ".ogg", ".opus", ".wav"}
LOCK_PATH = DATA_DIR / "library-quality.lock"
STATE_PATH = DATA_DIR / "library-quality-state.json"

METADATA_VERSION = 3
COVER_VERSION = 6
AUDIO_VERSION = 2
RADIO_VERSION = 3

RADIO_WRITE_CONFIDENCE = float(os.getenv("TOP40_LIBRARY_RADIO_WRITE_CONFIDENCE", "0.84"))
DEFAULT_HEAVY_LIMIT = int(os.getenv("TOP40_LIBRARY_HEAVY_LIMIT", "80"))
DEFAULT_ENRICH_LIMIT = int(os.getenv("TOP40_LIBRARY_ENRICH_LIMIT", "25"))
DEFAULT_COVER_LIMIT = int(os.getenv("TOP40_LIBRARY_COVER_LIMIT", "25"))

# Coververrijking mag nooit de bibliotheekscan minutenlang blokkeren.
# De totale online coverketen per track is standaard maximaal 12 seconden.
COVER_TRACK_BUDGET = float(os.getenv("TOP40_LIBRARY_COVER_TRACK_BUDGET", "12"))
COVER_HTTP_CONNECT_TIMEOUT = float(os.getenv("TOP40_LIBRARY_COVER_CONNECT_TIMEOUT", "2"))
COVER_HTTP_READ_TIMEOUT = float(os.getenv("TOP40_LIBRARY_COVER_READ_TIMEOUT", "4"))
COVER_LOOKUP_TIMEOUT = float(os.getenv("TOP40_LIBRARY_COVER_LOOKUP_TIMEOUT", "7"))
TOP40_BACKFILL_TIMEOUT = float(os.getenv("TOP40_LIBRARY_TOP40_BACKFILL_TIMEOUT", "6"))
TOP40_BACKFILL_MAX_EDITIONS = max(1, int(os.getenv("TOP40_LIBRARY_TOP40_BACKFILL_MAX_EDITIONS", "1")))

class AudioReadError(RuntimeError):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS library_quality (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id INTEGER REFERENCES tracks(id) ON DELETE SET NULL,
    file_path TEXT NOT NULL UNIQUE,
    file_size INTEGER,
    file_mtime_ns INTEGER,
    source_signature TEXT,
    scan_status TEXT NOT NULL DEFAULT 'pending',
    quality_score REAL NOT NULL DEFAULT 0,
    missing_fields TEXT NOT NULL DEFAULT '[]',
    warning_fields TEXT NOT NULL DEFAULT '[]',
    artist TEXT,
    title TEXT,
    album TEXT,
    release_date TEXT,
    genre TEXT,
    duration REAL,
    codec TEXT,
    bitrate INTEGER,
    sample_rate INTEGER,
    channels INTEGER,
    cover_present INTEGER NOT NULL DEFAULT 0,
    cover_width INTEGER,
    cover_height INTEGER,
    cover_mime TEXT,
    cover_hash TEXT,
    bpm REAL,
    musical_key TEXT,
    lufs REAL,
    true_peak REAL,
    fingerprint TEXT,
    fingerprint_duration INTEGER,
    intro_end REAL,
    first_vocal REAL,
    safe_talkover_end REAL,
    outro_start REAL,
    last_vocal REAL,
    fade_out_start REAL,
    safe_mixout_start REAL,
    cold_start INTEGER,
    cold_end INTEGER,
    radio_confidence REAL,
    provenance_json TEXT NOT NULL DEFAULT '{}',
    confidence_json TEXT NOT NULL DEFAULT '{}',
    metadata_version INTEGER NOT NULL DEFAULT 0,
    cover_version INTEGER NOT NULL DEFAULT 0,
    audio_version INTEGER NOT NULL DEFAULT 0,
    radio_version INTEGER NOT NULL DEFAULT 0,
    audio_hash TEXT,
    last_scanned_at TEXT,
    last_changed_at TEXT,
    last_error TEXT,
    failure_count INTEGER NOT NULL DEFAULT 0,
    cover_retry_count INTEGER NOT NULL DEFAULT 0,
    metadata_retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_library_quality_status ON library_quality(scan_status);
CREATE INDEX IF NOT EXISTS idx_library_quality_track ON library_quality(track_id);
CREATE INDEX IF NOT EXISTS idx_library_quality_retry ON library_quality(next_retry_at);

CREATE TABLE IF NOT EXISTS library_quality_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quality_id INTEGER REFERENCES library_quality(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    event_type TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_library_quality_events_created ON library_quality_events(created_at DESC);

CREATE TABLE IF NOT EXISTS library_quality_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    total_files INTEGER NOT NULL DEFAULT 0,
    processed INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    repaired INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    current_file TEXT,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_library_quality_runs_started ON library_quality_runs(started_at DESC);
"""


@dataclass
class Budget:
    heavy: int = DEFAULT_HEAVY_LIMIT
    enrich: int = DEFAULT_ENRICH_LIMIT
    cover: int = DEFAULT_COVER_LIMIT

    def take_heavy(self) -> bool:
        if self.heavy == 0:
            return False
        if self.heavy > 0:
            self.heavy -= 1
        return True

    def take_enrich(self) -> bool:
        if self.enrich == 0:
            return False
        if self.enrich > 0:
            self.enrich -= 1
        return True

    def take_cover(self) -> bool:
        if self.cover == 0:
            return False
        if self.cover > 0:
            self.cover -= 1
        return True


def init_library_quality_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as con:
        con.executescript(SCHEMA)
        existing = {str(row["name"]) for row in con.execute("PRAGMA table_info(library_quality)")}
        if "source_signature" not in existing:
            con.execute("ALTER TABLE library_quality ADD COLUMN source_signature TEXT")
        if "cover_retry_count" not in existing:
            con.execute("ALTER TABLE library_quality ADD COLUMN cover_retry_count INTEGER NOT NULL DEFAULT 0")
        if "metadata_retry_count" not in existing:
            con.execute("ALTER TABLE library_quality ADD COLUMN metadata_retry_count INTEGER NOT NULL DEFAULT 0")
        # v2 gebruikte failure_count ook voor ontbrekende verrijking. Vanaf v3 telt
        # failure_count uitsluitend echte scan/audiofouten.
        con.execute(
            "UPDATE library_quality SET failure_count=0 "
            "WHERE last_error IS NULL AND failure_count>0 AND (metadata_version<3 OR cover_version<3)"
        )


def _event(con: sqlite3.Connection, quality_id: int | None, file_path: str, event_type: str, detail: str = "") -> None:
    con.execute(
        "INSERT INTO library_quality_events(quality_id,file_path,event_type,detail,created_at) VALUES(?,?,?,?,?)",
        (quality_id, file_path, event_type, detail[-2000:], now_iso()),
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_iso(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed
    except (TypeError, ValueError):
        return None


def _versions_current(row: sqlite3.Row | dict[str, Any] | None) -> bool:
    if row is None:
        return False
    return (
        int(row["metadata_version"] or 0) >= METADATA_VERSION
        and int(row["cover_version"] or 0) >= COVER_VERSION
        and int(row["audio_version"] or 0) >= AUDIO_VERSION
        and int(row["radio_version"] or 0) >= RADIO_VERSION
    )


def _retry_due(row: sqlite3.Row | dict[str, Any] | None) -> bool:
    if row is None or not row["next_retry_at"]:
        return False
    parsed = _parse_iso(row["next_retry_at"])
    return bool(parsed and parsed <= datetime.now().astimezone())


def _next_retry(failure_count: int) -> str | None:
    # Eerste mislukking: morgen. Tweede: over 7 dagen. Daarna geen automatische lus.
    if failure_count <= 1:
        delta = timedelta(days=1)
    elif failure_count == 2:
        delta = timedelta(days=7)
    else:
        return None
    return (datetime.now().astimezone() + delta).isoformat(timespec="seconds")


def _ffprobe(path: Path) -> dict[str, Any]:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration,format_name,bit_rate:stream=index,codec_type,codec_name,sample_rate,bit_rate,channels",
        "-of", "json", str(path),
    ]
    cp = subprocess.run(cmd, capture_output=True, text=True, timeout=45, check=False)
    if cp.returncode != 0:
        raise AudioReadError((cp.stderr or "FFprobe kon bestand niet lezen")[-2000:])
    payload = json.loads(cp.stdout or "{}")
    streams = [s for s in payload.get("streams", []) if s.get("codec_type") == "audio"]
    if not streams:
        raise AudioReadError("Bestand bevat geen audiostream")
    audio = streams[0]
    fmt = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    return {
        "duration": float(fmt["duration"]) if fmt.get("duration") else None,
        "codec": str(audio.get("codec_name") or "") or None,
        "bitrate": int(audio.get("bit_rate") or fmt.get("bit_rate") or 0) or None,
        "sample_rate": int(audio.get("sample_rate") or 0) or None,
        "channels": int(audio.get("channels") or 0) or None,
        "format_name": str(fmt.get("format_name") or "") or None,
    }


def _audio_hash(path: Path) -> str | None:
    cp = subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(path),
         "-map", "0:a:0", "-c", "copy", "-f", "hash", "-hash", "sha256", "-"],
        capture_output=True, text=True, timeout=120, check=False,
    )
    if cp.returncode != 0:
        return None
    match = re.search(r"SHA256=([0-9a-fA-F]{64})", cp.stdout or "")
    return match.group(1).lower() if match else None


def _fpcalc(path: Path) -> tuple[str | None, int | None]:
    if not shutil.which("fpcalc"):
        return None, None
    cp = subprocess.run(["fpcalc", "-json", str(path)], capture_output=True, text=True, timeout=90, check=False)
    if cp.returncode != 0:
        return None, None
    try:
        payload = json.loads(cp.stdout)
    except json.JSONDecodeError:
        return None, None
    return str(payload.get("fingerprint") or "") or None, int(payload.get("duration") or 0) or None


def _loudness(path: Path) -> tuple[float | None, float | None]:
    cp = subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-i", str(path),
         "-af", "loudnorm=I=-23:TP=-2:LRA=7:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, timeout=180, check=False,
    )
    text = cp.stderr or ""
    match = re.search(r"\{\s*\"input_i\".*?\}", text, flags=re.S)
    if not match:
        return None, None
    try:
        payload = json.loads(match.group(0))
        return float(payload.get("input_i")), float(payload.get("input_tp"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None, None


def _key_name(chroma: Any) -> str | None:
    try:
        import numpy as np
    except ImportError:
        return None
    major = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
    profile = np.mean(chroma, axis=1)
    if not np.any(profile):
        return None
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    scores: list[tuple[float, str]] = []
    for i, name in enumerate(names):
        scores.append((float(np.corrcoef(profile, np.roll(major, i))[0, 1]), f"{name} major"))
        scores.append((float(np.corrcoef(profile, np.roll(minor, i))[0, 1]), f"{name} minor"))
    scores = [s for s in scores if math.isfinite(s[0])]
    return max(scores, default=(0.0, None), key=lambda item: item[0])[1]


def _first_sustained(mask: Any, frames: int) -> int | None:
    import numpy as np
    if len(mask) < frames:
        return None
    conv = np.convolve(mask.astype(float), np.ones(frames), mode="valid") / frames
    hits = np.flatnonzero(conv >= 0.68)
    return int(hits[0]) if hits.size else None


def _last_sustained(mask: Any, frames: int) -> int | None:
    import numpy as np
    if len(mask) < frames:
        return None
    conv = np.convolve(mask.astype(float), np.ones(frames), mode="valid") / frames
    hits = np.flatnonzero(conv >= 0.68)
    return int(hits[-1] + frames - 1) if hits.size else None


def _analyze_music(path: Path, duration: float | None) -> dict[str, Any]:
    """Conservatieve muziekanalyse. Vocal-punten blijven heuristisch + confidence-gebonden."""
    try:
        import librosa
        import numpy as np
    except ImportError:
        return {"analysis_available": False}

    y, sr = librosa.load(str(path), sr=22050, mono=True)
    if y.size < sr:
        return {"analysis_available": True, "radio_confidence": 0.0}

    hop = 512
    frame_seconds = hop / sr
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    rms_db = librosa.amplitude_to_db(np.maximum(rms, 1e-8), ref=np.max)
    active = rms_db > -38.0
    active_idx = np.flatnonzero(active)
    first_active = float(librosa.frames_to_time(active_idx[0], sr=sr, hop_length=hop)) if active_idx.size else 0.0
    last_active = float(librosa.frames_to_time(active_idx[-1], sr=sr, hop_length=hop)) if active_idx.size else float(duration or len(y)/sr)

    centroid = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=hop)[0]
    flatness = librosa.feature.spectral_flatness(y=y, hop_length=hop)[0]
    zcr = librosa.feature.zero_crossing_rate(y, hop_length=hop)[0]
    harmonic, percussive = librosa.effects.hpss(y)
    hrms = librosa.feature.rms(y=harmonic, hop_length=hop)[0]
    prms = librosa.feature.rms(y=percussive, hop_length=hop)[0]
    harmonic_ratio = hrms / np.maximum(hrms + prms, 1e-8)

    n = min(len(active), len(centroid), len(flatness), len(zcr), len(harmonic_ratio))
    voice_like = (
        active[:n]
        & (centroid[:n] >= 450)
        & (centroid[:n] <= 5200)
        & (flatness[:n] <= 0.32)
        & (zcr[:n] >= 0.008)
        & (zcr[:n] <= 0.28)
        & (harmonic_ratio[:n] >= 0.34)
    )
    window_frames = max(3, int(1.5 / frame_seconds))
    first_idx = _first_sustained(voice_like, window_frames)
    last_idx = _last_sustained(voice_like, window_frames)
    first_vocal = float(librosa.frames_to_time(first_idx, sr=sr, hop_length=hop)) if first_idx is not None else None
    last_vocal = float(librosa.frames_to_time(last_idx, sr=sr, hop_length=hop)) if last_idx is not None else None

    # Confidence is deliberately bounded: this is signal analysis, not a semantic singing-voice model.
    coverage = float(np.mean(voice_like)) if voice_like.size else 0.0
    confidence = 0.0
    if first_vocal is not None and last_vocal is not None and last_vocal > first_vocal:
        confidence = min(0.86, 0.58 + min(0.18, coverage * 0.9) + (0.08 if first_vocal > first_active else 0.0))

    total_duration = float(duration or len(y) / sr)
    fade_start = None
    tail_frames = max(10, int(30.0 / frame_seconds))
    tail = rms_db[-tail_frames:] if len(rms_db) > tail_frames else rms_db
    if len(tail) >= 20:
        x = np.arange(len(tail), dtype=float)
        slope = float(np.polyfit(x, tail, 1)[0])
        first_third = float(np.mean(tail[: max(1, len(tail)//3)]))
        last_third = float(np.mean(tail[-max(1, len(tail)//3):]))
        if slope < -0.025 and last_third < first_third - 5.0:
            threshold = first_third - 3.0
            candidates = np.flatnonzero(tail < threshold)
            if candidates.size:
                fade_start = max(0.0, total_duration - len(tail) * frame_seconds + candidates[0] * frame_seconds)

    cold_start = bool(first_vocal is not None and first_vocal <= 1.2)
    cold_end = bool(fade_start is None and total_duration - last_active < 0.8)
    intro_end = first_vocal
    safe_talkover = max(0.0, first_vocal - 0.45) if first_vocal is not None else None
    outro_start = last_vocal
    safe_mixout = fade_start if fade_start is not None else (max(outro_start or 0.0, total_duration - 8.0) if total_duration else None)

    try:
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr, hop_length=hop)
        bpm = float(np.asarray(tempo).reshape(-1)[0]) if np.size(tempo) else None
        if bpm and (bpm < 45 or bpm > 240):
            bpm = None
    except Exception:
        bpm = None

    try:
        chroma = librosa.feature.chroma_cqt(y=harmonic, sr=sr, hop_length=hop)
        key = _key_name(chroma)
    except Exception:
        key = None

    return {
        "analysis_available": True,
        "bpm": round(bpm, 2) if bpm else None,
        "musical_key": key,
        "intro_end": round(intro_end, 3) if intro_end is not None else None,
        "first_vocal": round(first_vocal, 3) if first_vocal is not None else None,
        "safe_talkover_end": round(safe_talkover, 3) if safe_talkover is not None else None,
        "outro_start": round(outro_start, 3) if outro_start is not None else None,
        "last_vocal": round(last_vocal, 3) if last_vocal is not None else None,
        "fade_out_start": round(fade_start, 3) if fade_start is not None else None,
        "safe_mixout_start": round(safe_mixout, 3) if safe_mixout is not None else None,
        "cold_start": int(cold_start),
        "cold_end": int(cold_end),
        "radio_confidence": round(confidence, 3),
    }


def _cover_info_from_bytes(data: bytes, mime: str | None = None) -> dict[str, Any]:
    if not data:
        return {"present": False}
    digest = hashlib.sha256(data).hexdigest()
    width = height = None
    detected_mime = mime
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            if not detected_mime:
                detected_mime = Image.MIME.get(image.format)
    except Exception:
        pass
    return {"present": True, "width": width, "height": height, "mime": detected_mime, "hash": digest}


def _read_tags(path: Path) -> dict[str, Any]:
    from mutagen import File
    data: dict[str, Any] = {"artist": None, "title": None, "album": None, "release_date": None, "genre": None, "bpm": None, "musical_key": None, "cover": {"present": False}}
    audio = File(path, easy=False)
    if audio is None:
        return data
    suffix = path.suffix.lower()

    def text_value(value: Any) -> str | None:
        if value is None:
            return None
        if hasattr(value, "text"):
            value = value.text
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        if value is None:
            return None
        result = str(value).strip()
        return result or None

    if suffix == ".mp3":
        try:
            from mutagen.id3 import ID3
            tags = ID3(path)
            data.update({
                "artist": text_value(tags.get("TPE1")), "title": text_value(tags.get("TIT2")),
                "album": text_value(tags.get("TALB")), "release_date": text_value(tags.get("TDRC")),
                "genre": text_value(tags.get("TCON")), "bpm": text_value(tags.get("TBPM")),
                "musical_key": text_value(tags.get("TKEY")),
            })
            apics = [v for k, v in tags.items() if k.startswith("APIC")]
            if apics:
                data["cover"] = _cover_info_from_bytes(apics[0].data, getattr(apics[0], "mime", None))
        except Exception:
            pass
    elif suffix == ".flac":
        tags = audio.tags or {}
        data.update({k: text_value(tags.get(key)) for k, key in {
            "artist": "artist", "title": "title", "album": "album", "release_date": "date", "genre": "genre", "bpm": "bpm", "musical_key": "key"
        }.items()})
        pictures = getattr(audio, "pictures", [])
        if pictures:
            data["cover"] = _cover_info_from_bytes(pictures[0].data, getattr(pictures[0], "mime", None))
    elif suffix in {".m4a", ".mp4", ".aac"}:
        tags = audio.tags or {}
        data.update({
            "artist": text_value(tags.get("\xa9ART")), "title": text_value(tags.get("\xa9nam")),
            "album": text_value(tags.get("\xa9alb")), "release_date": text_value(tags.get("\xa9day")),
            "genre": text_value(tags.get("\xa9gen")), "bpm": text_value(tags.get("tmpo")),
            "musical_key": text_value(tags.get("----:com.apple.iTunes:initialkey")),
        })
        covers = tags.get("covr") or []
        if covers:
            data["cover"] = _cover_info_from_bytes(bytes(covers[0]))
    else:
        tags = audio.tags or {}
        for out, key in {"artist": "artist", "title": "title", "album": "album", "release_date": "date", "genre": "genre", "bpm": "bpm", "musical_key": "key"}.items():
            try:
                data[out] = text_value(tags.get(key))
            except Exception:
                pass
    return data


_COVER_DOWNLOAD_FAILURE_CACHE: set[str] = set()
_COVER_LOOKUP_CACHE: dict[tuple[str, str], dict[str, str]] = {}
_LAST_COVER_LOOKUP_STARTED = 0.0


def _cover_remaining(deadline: float | None) -> float:
    if deadline is None:
        return COVER_TRACK_BUDGET
    return max(0.0, deadline - time.monotonic())


def _download_cover(url: str, deadline: float | None = None) -> tuple[bytes, str] | None:
    url = str(url or "").strip()
    from .cover_validation import is_placeholder_url
    if not url or is_placeholder_url(url) or url in _COVER_DOWNLOAD_FAILURE_CACHE:
        return None
    remaining = _cover_remaining(deadline)
    if remaining < 0.75:
        return None
    connect_timeout = max(0.5, min(COVER_HTTP_CONNECT_TIMEOUT, remaining / 2.0))
    read_timeout = max(0.5, min(COVER_HTTP_READ_TIMEOUT, max(0.5, remaining - connect_timeout)))
    try:
        response = requests.get(
            url,
            timeout=(connect_timeout, read_timeout),
            headers={"User-Agent": "Top40Archiver LibraryQuality/1.16.23.5"},
        )
        response.raise_for_status()
        if is_placeholder_url(response.url):
            return None
        if not response.content or len(response.content) > 6 * 1024 * 1024:
            _COVER_DOWNLOAD_FAILURE_CACHE.add(url)
            return None
        mime = (response.headers.get("Content-Type") or "image/jpeg").split(";", 1)[0].strip()
        if not mime.startswith("image/"):
            mime = "image/jpeg"
        return response.content, mime
    except Exception:
        _COVER_DOWNLOAD_FAILURE_CACHE.add(url)
        return None


def _lookup_cover_bounded(artist: str, title: str, deadline: float | None = None) -> dict[str, str]:
    """Draai de bestaande MusicBrainz/CAA-resolver geïsoleerd met een harde timeout.

    cover_art.lookup_cover behoudt zijn normale retrygedrag voor de gewone coverworker.
    Alleen Library Quality begrenst die resolver, zodat een slechte externe bron de
    bibliotheekscan niet meer 1-2 minuten per track kan vasthouden.
    """
    global _LAST_COVER_LOOKUP_STARTED
    if lookup_cover is None:
        return {}
    key = (" ".join(str(artist or "").casefold().split()), " ".join(str(title or "").casefold().split()))
    if key in _COVER_LOOKUP_CACHE:
        return dict(_COVER_LOOKUP_CACHE[key])
    remaining = _cover_remaining(deadline)
    if remaining < 0.75:
        return {}

    # MusicBrainz vraagt beleefde request-pacing. Ook losse helperprocessen worden
    # daarom vanuit de scanner minimaal ~1 seconde uit elkaar gestart.
    wait = 1.05 - (time.monotonic() - _LAST_COVER_LOOKUP_STARTED)
    if wait > 0:
        time.sleep(min(wait, max(0.0, _cover_remaining(deadline) - 0.75)))
    remaining = _cover_remaining(deadline)
    if remaining < 0.75:
        return {}

    timeout = max(0.75, min(COVER_LOOKUP_TIMEOUT, remaining))
    app_root = str(Path(__file__).resolve().parent.parent)
    env = os.environ.copy()
    env["PYTHONPATH"] = app_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    code = (
        "import json,sys; "
        "from app.cover_art import lookup_cover; "
        "print(json.dumps(lookup_cover(sys.argv[1], sys.argv[2]) or {}))"
    )
    _LAST_COVER_LOOKUP_STARTED = time.monotonic()
    try:
        proc = subprocess.run(
            [os.sys.executable, "-c", code, str(artist), str(title)],
            text=True,
            capture_output=True,
            timeout=timeout,
            env=env,
        )
        if proc.returncode != 0:
            result: dict[str, str] = {}
        else:
            payload = json.loads((proc.stdout or "{}").strip().splitlines()[-1])
            result = {str(k): str(v) for k, v in payload.items() if v not in (None, "")} if isinstance(payload, dict) else {}
    except (subprocess.TimeoutExpired, json.JSONDecodeError, IndexError, OSError):
        result = {}
    _COVER_LOOKUP_CACHE[key] = dict(result)
    return result


def _write_metadata_to_copy(path: Path, desired: dict[str, Any], radio: dict[str, Any], cover: tuple[bytes, str] | None) -> bool:
    """Schrijf ontbrekende of aantoonbaar vervuilde metadata naar een kopie."""
    suffix = path.suffix.lower()
    changed = False
    replace_fields = set(desired.get("_replace_fields") or [])
    refresh_radio = bool(radio.get("_refresh_radio_tags"))
    write_radio = float(radio.get("radio_confidence") or 0) >= RADIO_WRITE_CONFIDENCE

    if suffix == ".mp3":
        from mutagen.id3 import APIC, ID3, ID3NoHeaderError, TALB, TBPM, TCON, TDRC, TIT2, TKEY, TPE1, TXXX
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
        standard = {
            "artist": ("TPE1", TPE1), "title": ("TIT2", TIT2), "album": ("TALB", TALB),
            "release_date": ("TDRC", TDRC), "genre": ("TCON", TCON), "bpm": ("TBPM", TBPM), "musical_key": ("TKEY", TKEY),
        }
        for field, (key, cls) in standard.items():
            value = desired.get(field)
            if value in (None, ""):
                continue
            if key not in tags or field in replace_fields:
                if key in tags:
                    tags.delall(key)
                tags.add(cls(encoding=3, text=[str(value)]))
                changed = True
        if cover and not any(k.startswith("APIC") for k in tags.keys()):
            tags.add(APIC(encoding=3, mime=cover[1], type=3, desc="Cover", data=cover[0]))
            changed = True

        radio_descs = {
            "TOP40_INTRO_END", "TOP40_FIRST_VOCAL", "TOP40_SAFE_TALKOVER_END", "TOP40_OUTRO_START",
            "TOP40_LAST_VOCAL", "TOP40_FADE_OUT_START", "TOP40_SAFE_MIXOUT_START", "TOP40_COLD_START",
            "TOP40_COLD_END", "TOP40_RADIO_CONFIDENCE", "TOP40_ANALYSIS_VERSION",
        }
        if refresh_radio:
            for key, frame in list(tags.items()):
                if key.startswith("TXXX") and getattr(frame, "desc", "") in radio_descs:
                    del tags[key]
                    changed = True
        if write_radio:
            custom = {
                "INTRO_END": radio.get("intro_end"), "FIRST_VOCAL": radio.get("first_vocal"),
                "SAFE_TALKOVER_END": radio.get("safe_talkover_end"), "OUTRO_START": radio.get("outro_start"),
                "LAST_VOCAL": radio.get("last_vocal"), "FADE_OUT_START": radio.get("fade_out_start"),
                "SAFE_MIXOUT_START": radio.get("safe_mixout_start"), "COLD_START": radio.get("cold_start"),
                "COLD_END": radio.get("cold_end"), "RADIO_CONFIDENCE": radio.get("radio_confidence"),
                "ANALYSIS_VERSION": RADIO_VERSION,
            }
            existing_desc = {getattr(frame, "desc", "") for frame in tags.getall("TXXX")}
            for name, value in custom.items():
                desc = f"TOP40_{name}"
                if value is not None and desc not in existing_desc:
                    tags.add(TXXX(encoding=3, desc=desc, text=[str(value)]))
                    changed = True
        if changed:
            tags.save(path, v2_version=3)
        return changed

    from mutagen import File
    audio = File(path, easy=False)
    if audio is None:
        return False
    if audio.tags is None:
        try:
            audio.add_tags()
        except Exception:
            pass

    if suffix == ".flac":
        tags = audio.tags
        mapping = {"artist": "artist", "title": "title", "album": "album", "release_date": "date", "genre": "genre", "bpm": "bpm", "musical_key": "key"}
        for field, key in mapping.items():
            if desired.get(field) not in (None, "") and (not tags.get(key) or field in replace_fields):
                tags[key] = [str(desired[field])]
                changed = True
        if cover and not getattr(audio, "pictures", []):
            from mutagen.flac import Picture
            pic = Picture(); pic.type = 3; pic.mime = cover[1]; pic.data = cover[0]; pic.desc = "Cover"
            try:
                from PIL import Image
                with Image.open(io.BytesIO(cover[0])) as img:
                    pic.width, pic.height = img.size
            except Exception:
                pass
            audio.add_picture(pic); changed = True
        radio_keys = ["TOP40_INTRO_END", "TOP40_FIRST_VOCAL", "TOP40_SAFE_TALKOVER_END", "TOP40_OUTRO_START", "TOP40_LAST_VOCAL", "TOP40_FADE_OUT_START", "TOP40_SAFE_MIXOUT_START", "TOP40_RADIO_CONFIDENCE", "TOP40_ANALYSIS_VERSION"]
        if refresh_radio:
            for key in radio_keys:
                if tags.get(key):
                    del tags[key]; changed = True
        if write_radio:
            for key, value in {
                "TOP40_INTRO_END": radio.get("intro_end"), "TOP40_FIRST_VOCAL": radio.get("first_vocal"),
                "TOP40_SAFE_TALKOVER_END": radio.get("safe_talkover_end"), "TOP40_OUTRO_START": radio.get("outro_start"),
                "TOP40_LAST_VOCAL": radio.get("last_vocal"), "TOP40_FADE_OUT_START": radio.get("fade_out_start"),
                "TOP40_SAFE_MIXOUT_START": radio.get("safe_mixout_start"), "TOP40_RADIO_CONFIDENCE": radio.get("radio_confidence"),
                "TOP40_ANALYSIS_VERSION": RADIO_VERSION,
            }.items():
                if value is not None:
                    tags[key] = [str(value)]; changed = True
        if changed: audio.save()
        return changed

    if suffix in {".m4a", ".mp4", ".aac"}:
        tags = audio.tags
        mapping = {"artist": "\xa9ART", "title": "\xa9nam", "album": "\xa9alb", "release_date": "\xa9day", "genre": "\xa9gen"}
        for field, key in mapping.items():
            if desired.get(field) not in (None, "") and (not tags.get(key) or field in replace_fields):
                tags[key] = [str(desired[field])]; changed = True
        if desired.get("bpm") and (not tags.get("tmpo") or "bpm" in replace_fields):
            tags["tmpo"] = [int(round(float(desired["bpm"])))]; changed = True
        if cover and not tags.get("covr"):
            from mutagen.mp4 import MP4Cover
            fmt = MP4Cover.FORMAT_PNG if "png" in cover[1].lower() else MP4Cover.FORMAT_JPEG
            tags["covr"] = [MP4Cover(cover[0], imageformat=fmt)]; changed = True
        radio_keys = [f"----:com.top40archiver:TOP40_{name}" for name in ["INTRO_END", "FIRST_VOCAL", "SAFE_TALKOVER_END", "OUTRO_START", "LAST_VOCAL", "FADE_OUT_START", "SAFE_MIXOUT_START", "RADIO_CONFIDENCE", "ANALYSIS_VERSION"]]
        if refresh_radio:
            for key in radio_keys:
                if tags.get(key):
                    del tags[key]; changed = True
        if write_radio:
            for name, value in {"INTRO_END": radio.get("intro_end"), "FIRST_VOCAL": radio.get("first_vocal"), "SAFE_TALKOVER_END": radio.get("safe_talkover_end"), "OUTRO_START": radio.get("outro_start"), "LAST_VOCAL": radio.get("last_vocal"), "FADE_OUT_START": radio.get("fade_out_start"), "SAFE_MIXOUT_START": radio.get("safe_mixout_start"), "RADIO_CONFIDENCE": radio.get("radio_confidence"), "ANALYSIS_VERSION": RADIO_VERSION}.items():
                if value is not None:
                    tags[f"----:com.top40archiver:TOP40_{name}"] = [str(value).encode("utf-8")]; changed = True
        if changed: audio.save()
        return changed

    tags = audio.tags
    if tags is None:
        return False
    mapping = {"artist": "artist", "title": "title", "album": "album", "release_date": "date", "genre": "genre", "bpm": "bpm", "musical_key": "key"}
    for field, key in mapping.items():
        try:
            if desired.get(field) not in (None, "") and (not tags.get(key) or field in replace_fields):
                tags[key] = [str(desired[field])]; changed = True
        except Exception:
            pass
    radio_keys = [f"TOP40_{name}" for name in ["INTRO_END", "FIRST_VOCAL", "SAFE_TALKOVER_END", "OUTRO_START", "LAST_VOCAL", "FADE_OUT_START", "SAFE_MIXOUT_START", "RADIO_CONFIDENCE", "ANALYSIS_VERSION"]]
    if refresh_radio:
        for key in radio_keys:
            try:
                if tags.get(key): del tags[key]; changed = True
            except Exception:
                pass
    if write_radio:
        for name, value in {"INTRO_END": radio.get("intro_end"), "FIRST_VOCAL": radio.get("first_vocal"), "SAFE_TALKOVER_END": radio.get("safe_talkover_end"), "OUTRO_START": radio.get("outro_start"), "LAST_VOCAL": radio.get("last_vocal"), "FADE_OUT_START": radio.get("fade_out_start"), "SAFE_MIXOUT_START": radio.get("safe_mixout_start"), "RADIO_CONFIDENCE": radio.get("radio_confidence"), "ANALYSIS_VERSION": RADIO_VERSION}.items():
            key = f"TOP40_{name}"
            try:
                if value is not None: tags[key] = [str(value)]; changed = True
            except Exception:
                pass
    if changed: audio.save()
    return changed

def _atomic_metadata_update(path: Path, desired: dict[str, Any], radio: dict[str, Any], cover: tuple[bytes, str] | None) -> bool:
    before_hash = _audio_hash(path)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.quality-", suffix=path.suffix, dir=str(path.parent))
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        shutil.copy2(path, tmp)
        changed = _write_metadata_to_copy(tmp, desired, radio, cover)
        if not changed:
            return False
        _ffprobe(tmp)
        after_hash = _audio_hash(tmp)
        if before_hash and after_hash and before_hash != after_hash:
            raise RuntimeError("Audiohash wijzigde tijdens metadata-update; wijziging geweigerd")
        os.replace(tmp, path)
        return True
    finally:
        tmp.unlink(missing_ok=True)


def _track_columns(con: sqlite3.Connection) -> set[str]:
    return {str(row["name"]) for row in con.execute("PRAGMA table_info(tracks)")}


def _track_map(download_dir: Path) -> dict[str, dict[str, Any]]:
    with connect() as con:
        cols = _track_columns(con)
        wanted = ["id", "artist", "title", "genre", "mp3_filename", "spotify_album", "spotify_release_date", "cover_url", "cover_source"]
        selected = [name if name in cols else f"NULL AS {name}" for name in wanted]
        rows = con.execute(
            f"SELECT {','.join(selected)} FROM tracks WHERE download_status='downloaded' AND mp3_filename IS NOT NULL"
        ).fetchall()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        filename = str(row["mp3_filename"] or "").strip()
        if not filename:
            continue
        p = Path(filename)
        absolute = p if p.is_absolute() else download_dir / p
        record = {key: row[key] for key in row.keys()}
        result[str(absolute.resolve(strict=False)).casefold()] = record
        result[p.as_posix().casefold()] = record
    return result


def discover_files(download_dir: Path) -> list[Path]:
    if not download_dir.exists():
        return []
    return sorted(
        (p for p in download_dir.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES),
        key=lambda p: p.as_posix().casefold(),
    )



def _source_signature(track: dict[str, Any] | None) -> str:
    if not track:
        return hashlib.sha256(b"{}").hexdigest()
    payload = {
        key: track.get(key)
        for key in ["id", "artist", "title", "genre", "spotify_album", "spotify_release_date", "cover_url", "cover_source"]
    }
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _quality_score(values: dict[str, Any], missing: set[str], warnings: set[str]) -> float:
    score = 100.0
    penalties = {
        "artist": 15, "title": 15, "genre": 8, "cover": 12, "duration": 10,
        "fingerprint": 5, "loudness": 5, "bpm": 3, "key": 2, "radio": 10,
        "album": 3, "release_date": 2,
    }
    for name in missing:
        score -= penalties.get(name, 2)
    score -= min(10.0, len(warnings) * 2.0)
    return round(max(0.0, score), 1)


def _status(missing: set[str], warnings: set[str], radio_confidence: float | None, fatal: bool = False) -> str:
    if fatal:
        return "audio_corrupt"
    if "artist" in missing or "title" in missing:
        return "needs_metadata"
    if "cover" in missing:
        return "needs_cover"
    if "genre" in missing:
        return "needs_genre"
    if "radio" in missing:
        return "pending_analysis"
    if radio_confidence is not None and radio_confidence < RADIO_WRITE_CONFIDENCE:
        return "low_confidence"
    if warnings:
        return "warning"
    return "complete"


_NOISY_TAG_RE = re.compile(
    r"(?:\b(?:official\s*(?:music\s*)?video|official\s*audio|lyrics?|lyric\s*video|visuali[sz]er|"
    r"youtube|1080p|720p|2160p|4k|hd\s*video|vevo)\b|\[(?:hd|hq|official)\])",
    re.I,
)


def _metadata_value_is_suspicious(field: str, value: Any) -> bool:
    text = " ".join(str(value or "").split())
    if not text:
        return False
    if _NOISY_TAG_RE.search(text):
        return True
    lowered = text.casefold()
    if field == "album" and lowered in {"unknown", "unknown album", "youtube", "video", "single track"}:
        return True
    if field == "artist" and lowered.endswith(" - topic"):
        return True
    return False


_TOP40_BACKFILL_EDITION_CACHE: set[tuple[str, int]] = set()
_ACTIVE_COVER_DEADLINE: float | None = None


def _top40_backfill_cover(track: dict[str, Any]) -> dict[str, str]:
    """Gebruik de bestaande Top40.nl backfill voor een track voordat MusicBrainz wordt geprobeerd.

    De gewone Top40Archiver-backfill haalt cover_url uit historische Top40/Tipparade-edities.
    Library Quality hergebruikt die bron en matcher; het bouwt hier dus geen tweede
    Top40.nl-coverzoeker. Per run wordt een editie maximaal één keer opgehaald.
    """
    if top40_process_edition is None:
        return {}
    try:
        track_id = int(track.get("id") or 0)
    except (TypeError, ValueError):
        return {}
    if track_id <= 0:
        return {}

    candidates: list[dict[str, Any]] = []
    try:
        with connect() as con:
            for chart_type, edition_table, entry_table in (
                ("top40", "editions", "chart_entries"),
                ("tipparade", "tipparade_editions", "tipparade_entries"),
            ):
                rows = con.execute(
                    f"""
                    SELECT e.id,e.year,e.week,e.edition_key
                    FROM {edition_table} e
                    JOIN {entry_table} ce ON ce.edition_id=e.id
                    WHERE ce.track_id=?
                    ORDER BY e.year DESC,e.week DESC
                    LIMIT 4
                    """,
                    (track_id,),
                ).fetchall()
                for row in rows:
                    candidates.append({
                        "chart_type": chart_type,
                        "entry_table": entry_table,
                        "id": int(row["id"]),
                        "year": int(row["year"]),
                        "week": int(row["week"]),
                        "edition_key": str(row["edition_key"]),
                    })
    except Exception:
        return {}

    candidates.sort(key=lambda item: (item["year"], item["week"]), reverse=True)

    for info in candidates[:TOP40_BACKFILL_MAX_EDITIONS]:
        cache_key = (str(info["chart_type"]), int(info["id"]))
        if cache_key not in _TOP40_BACKFILL_EDITION_CACHE:
            # process_edition wordt in een apart proces uitgevoerd. Daardoor kan een
            # trage/onbereikbare Top40.nl-pagina hard worden afgebroken zonder de
            # 8085-worker te laten hangen. De gewone backfillmodule blijft ongewijzigd.
            app_root = str(Path(__file__).resolve().parent.parent)
            env = os.environ.copy()
            env["PYTHONPATH"] = app_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
            code = (
                "import json,sys; "
                "from app.top40_cover_backfill import process_edition; "
                "process_edition(json.loads(sys.argv[1])); print('OK')"
            )
            timeout = max(0.75, min(TOP40_BACKFILL_TIMEOUT, _cover_remaining(_ACTIVE_COVER_DEADLINE)))
            try:
                if _cover_remaining(_ACTIVE_COVER_DEADLINE) < 0.75:
                    return {}
                subprocess.run(
                    [os.sys.executable, "-c", code, json.dumps(info)],
                    text=True,
                    capture_output=True,
                    timeout=timeout,
                    env=env,
                    check=False,
                )
            except (subprocess.TimeoutExpired, OSError):
                pass
            _TOP40_BACKFILL_EDITION_CACHE.add(cache_key)

        try:
            with connect() as con:
                row = con.execute(
                    "SELECT cover_url,cover_source FROM tracks WHERE id=?",
                    (track_id,),
                ).fetchone()
        except Exception:
            row = None

        cover_url = str(row["cover_url"] or "").strip() if row else ""
        if cover_url:
            cover_source = str(row["cover_source"] or "top40.nl").strip() if row else "top40.nl"
            track["cover_url"] = cover_url
            return {"cover_url": cover_url, "cover_source": cover_source or "top40.nl"}

    return {}


def _save_cover_lookup(track: dict[str, Any], result: dict[str, str]) -> None:
    track_id = track.get("id") if track else None
    cover_url = str(result.get("cover_url") or "").strip()
    if not track_id or not cover_url:
        return
    try:
        with connect() as con:
            cols = _track_columns(con)
            updates: dict[str, Any] = {}
            for col in ["cover_url", "cover_source", "musicbrainz_recording_id", "musicbrainz_release_id"]:
                if col in cols and result.get(col):
                    updates[col] = result[col]
            if "cover_checked_at" in cols:
                updates["cover_checked_at"] = now_iso()
            if updates:
                con.execute(
                    f"UPDATE tracks SET {','.join(f'{k}=?' for k in updates)} WHERE id=?",
                    (*updates.values(), track_id),
                )
        track["cover_url"] = cover_url
    except Exception:
        # Cover in het audiobestand is belangrijker dan het bijwerken van de broncache.
        pass


def _desired_metadata(tags: dict[str, Any], track: dict[str, Any] | None, budget: Budget) -> tuple[dict[str, Any], dict[str, str], dict[str, bool]]:
    desired = dict(tags)
    replace_fields: set[str] = set()
    provenance: dict[str, str] = {
        field: "embedded_tag"
        for field in ["artist", "title", "album", "release_date", "genre", "bpm", "musical_key"]
        if desired.get(field) not in (None, "")
    }
    attempts = {"genre": False}
    if track:
        sources = [
            ("artist", "artist", "top40_sqlite"),
            ("title", "title", "top40_sqlite"),
            ("album", "spotify_album", "spotify_metadata"),
            ("release_date", "spotify_release_date", "spotify_metadata"),
        ]
        for field, source, source_name in sources:
            db_value = str(track.get(source) or "").strip()
            current = desired.get(field)
            if not db_value:
                continue
            if not current:
                desired[field] = db_value
                provenance[field] = source_name
            elif _metadata_value_is_suspicious(field, current) and not _metadata_value_is_suspicious(field, db_value):
                desired[field] = db_value
                provenance[field] = f"{source_name}_cleaned"
                replace_fields.add(field)

        current_genre = clean_genre(desired.get("genre")) if desired.get("genre") else UNKNOWN_GENRE
        db_genre = clean_genre(track.get("genre")) if track.get("genre") else UNKNOWN_GENRE
        if current_genre == UNKNOWN_GENRE and db_genre != UNKNOWN_GENRE:
            desired["genre"] = db_genre
            provenance["genre"] = "top40_sqlite"
        elif current_genre == UNKNOWN_GENRE and track.get("artist") and track.get("title"):
            if budget.take_enrich():
                attempts["genre"] = True
                resolved = clean_genre(resolve_genre(str(track["artist"]), str(track["title"])))
                if resolved != UNKNOWN_GENRE:
                    desired["genre"] = resolved
                    provenance["genre"] = "itunes_genre_resolver"
    desired["_replace_fields"] = sorted(replace_fields)
    return desired, provenance, attempts

def _cover_quality(cover: dict[str, Any]) -> set[str]:
    warnings: set[str] = set()
    if cover.get("present"):
        w, h = cover.get("width"), cover.get("height")
        if w and h:
            if min(int(w), int(h)) < 300:
                warnings.add("cover_low_resolution")
            ratio = max(w, h) / max(1, min(w, h))
            if ratio > 1.25:
                warnings.add("cover_not_square")
    return warnings


def _should_skip(row: sqlite3.Row | None, stat: os.stat_result, force: bool, source_signature: str) -> bool:
    if force or row is None:
        return False
    unchanged = int(row["file_size"] or -1) == stat.st_size and int(row["file_mtime_ns"] or -1) == stat.st_mtime_ns
    source_unchanged = str(row["source_signature"] or "") == source_signature
    if not unchanged or not source_unchanged or not _versions_current(row):
        return False
    status = str(row["scan_status"] or "")
    if status in {"complete", "low_confidence", "warning"}:
        return True
    if row["next_retry_at"]:
        return not _retry_due(row)
    # Zonder geplande retry is er geen nieuwe automatische bron/actie beschikbaar.
    # Het bestand wordt pas opnieuw bekeken bij een gewijzigde bron-signature,
    # bestandswijziging, analyzer-versie of een expliciete force-scan.
    if status in {"needs_metadata", "needs_cover", "needs_genre", "pending_analysis"}:
        return True
    return int(row["failure_count"] or 0) >= 3


def _upsert_result(con: sqlite3.Connection, path: Path, track: dict[str, Any] | None, stat: os.stat_result, values: dict[str, Any]) -> int:
    file_path = str(path)
    existing = con.execute("SELECT id FROM library_quality WHERE file_path=?", (file_path,)).fetchone()
    fields = {
        "track_id": track.get("id") if track else None,
        "file_size": stat.st_size, "file_mtime_ns": stat.st_mtime_ns, "source_signature": _source_signature(track),
        "scan_status": values.get("scan_status", "pending"), "quality_score": values.get("quality_score", 0),
        "missing_fields": _json(sorted(values.get("missing_fields", []))), "warning_fields": _json(sorted(values.get("warning_fields", []))),
        "artist": values.get("artist"), "title": values.get("title"), "album": values.get("album"), "release_date": values.get("release_date"), "genre": values.get("genre"),
        "duration": values.get("duration"), "codec": values.get("codec"), "bitrate": values.get("bitrate"), "sample_rate": values.get("sample_rate"), "channels": values.get("channels"),
        "cover_present": int(bool(values.get("cover_present"))), "cover_width": values.get("cover_width"), "cover_height": values.get("cover_height"), "cover_mime": values.get("cover_mime"), "cover_hash": values.get("cover_hash"),
        "bpm": values.get("bpm"), "musical_key": values.get("musical_key"), "lufs": values.get("lufs"), "true_peak": values.get("true_peak"),
        "fingerprint": values.get("fingerprint"), "fingerprint_duration": values.get("fingerprint_duration"),
        "intro_end": values.get("intro_end"), "first_vocal": values.get("first_vocal"), "safe_talkover_end": values.get("safe_talkover_end"),
        "outro_start": values.get("outro_start"), "last_vocal": values.get("last_vocal"), "fade_out_start": values.get("fade_out_start"), "safe_mixout_start": values.get("safe_mixout_start"),
        "cold_start": values.get("cold_start"), "cold_end": values.get("cold_end"), "radio_confidence": values.get("radio_confidence"),
        "provenance_json": _json(values.get("provenance", {})), "confidence_json": _json(values.get("confidence", {})),
        "metadata_version": METADATA_VERSION, "cover_version": COVER_VERSION, "audio_version": AUDIO_VERSION, "radio_version": RADIO_VERSION,
        "audio_hash": values.get("audio_hash"), "last_scanned_at": now_iso(), "last_changed_at": values.get("last_changed_at") or now_iso(),
        "last_error": values.get("last_error"), "failure_count": int(values.get("failure_count", 0)),
        "cover_retry_count": int(values.get("cover_retry_count", 0)), "metadata_retry_count": int(values.get("metadata_retry_count", 0)),
        "next_retry_at": values.get("next_retry_at"), "updated_at": now_iso(),
    }
    if existing:
        assignments = ",".join(f"{k}=?" for k in fields)
        con.execute(f"UPDATE library_quality SET {assignments} WHERE id=?", (*fields.values(), existing["id"]))
        return int(existing["id"])
    cols = ["file_path", *fields.keys()]
    placeholders = ",".join("?" for _ in cols)
    cur = con.execute(f"INSERT INTO library_quality({','.join(cols)}) VALUES({placeholders})", (file_path, *fields.values()))
    return int(cur.lastrowid)


def analyze_one(path: Path, track: dict[str, Any] | None, budget: Budget, previous: sqlite3.Row | None = None) -> tuple[dict[str, Any], bool]:
    stat_before = path.stat()
    technical = _ffprobe(path)
    tags = _read_tags(path)
    desired, provenance, attempts = _desired_metadata(tags, track, budget)
    repaired = False
    cover_download: tuple[bytes, str] | None = None
    cover_attempted = False
    cover_deferred = False

    cover = tags.get("cover") or {"present": False}
    if cover.get("present"):
        provenance.setdefault("cover", "embedded_cover")
    elif track:
        if budget.take_cover():
            cover_attempted = True
            global _ACTIVE_COVER_DEADLINE
            cover_deadline = time.monotonic() + max(2.0, COVER_TRACK_BUDGET)
            _ACTIVE_COVER_DEADLINE = cover_deadline
            tried_cover_urls: set[str] = set()
            cover_url = str(track.get("cover_url") or "").strip()

            # 1. Een bestaande tracks.cover_url is de goedkoopste bron, maar alleen
            #    bruikbaar als het beeld nu werkelijk kan worden opgehaald. Een oude
            #    of verlopen URL mag de verdere coverketen niet blokkeren.
            if cover_url:
                tried_cover_urls.add(cover_url)
                cover_download = _download_cover(cover_url, cover_deadline)
                if cover_download:
                    provenance["cover"] = str(track.get("cover_source") or "tracks_cover_url")

            # 2. Als er nog geen URL bestond, gebruik eerst de gewone historische
            #    Top40.nl/Tipparade-backfill. Die vult de centrale tracks-tabel.
            if not cover_download and not cover_url:
                found_cover = _top40_backfill_cover(track)
                candidate_url = str(found_cover.get("cover_url") or "").strip()
                if candidate_url and candidate_url not in tried_cover_urls:
                    tried_cover_urls.add(candidate_url)
                    candidate_download = _download_cover(candidate_url, cover_deadline)
                    if candidate_download:
                        cover_download = candidate_download
                        cover_url = candidate_url
                        provenance["cover"] = str(found_cover.get("cover_source") or "top40.nl_backfill")

            # 3. Als een bestaande/Top40.nl URL niet downloadbaar is, mag die niet
            #    verhinderen dat de reeds bestaande MusicBrainz/CAA-resolver een
            #    verse fallback zoekt. Sla een nieuwe URL pas op als de afbeelding
            #    daadwerkelijk is gedownload en valide genoeg is voor embedding.
            if not cover_download and lookup_cover and track.get("artist") and track.get("title"):
                found_cover = _lookup_cover_bounded(
                    str(track["artist"]),
                    str(track["title"]),
                    cover_deadline,
                )
                candidate_url = str(found_cover.get("cover_url") or "").strip()
                if candidate_url and candidate_url not in tried_cover_urls:
                    tried_cover_urls.add(candidate_url)
                    candidate_download = _download_cover(candidate_url, cover_deadline)
                    if candidate_download:
                        cover_download = candidate_download
                        cover_url = candidate_url
                        _save_cover_lookup(track, found_cover)
                        provenance["cover"] = str(found_cover.get("cover_source") or "cover_art_lookup")
            _ACTIVE_COVER_DEADLINE = None
        else:
            cover_deferred = True

    heavy: dict[str, Any] = {}
    heavy_attempted = False
    heavy_deferred = False
    need_heavy = previous is None or int(previous["audio_version"] or 0) < AUDIO_VERSION or int(previous["radio_version"] or 0) < RADIO_VERSION or not previous["fingerprint"]
    if need_heavy and budget.take_heavy():
        heavy_attempted = True
        heavy = _analyze_music(path, technical.get("duration"))
        lufs, true_peak = _loudness(path)
        fingerprint, fp_duration = _fpcalc(path)
        heavy.update({"lufs": lufs, "true_peak": true_peak, "fingerprint": fingerprint, "fingerprint_duration": fp_duration})
        provenance.update({"bpm": "librosa", "musical_key": "librosa", "radio": "signal_analysis", "loudness": "ffmpeg_loudnorm", "fingerprint": "chromaprint"})
    elif previous:
        heavy_deferred = need_heavy
        for key in ["bpm", "musical_key", "lufs", "true_peak", "fingerprint", "fingerprint_duration", "intro_end", "first_vocal", "safe_talkover_end", "outro_start", "last_vocal", "fade_out_start", "safe_mixout_start", "cold_start", "cold_end", "radio_confidence"]:
            heavy[key] = previous[key]
    elif need_heavy:
        heavy_deferred = True

    if not desired.get("bpm") and heavy.get("bpm"):
        desired["bpm"] = heavy["bpm"]
    if not desired.get("musical_key") and heavy.get("musical_key"):
        desired["musical_key"] = heavy["musical_key"]

    # Only write changes to a copy and validate the encoded audio hash before atomic replace.
    heavy["_refresh_radio_tags"] = bool(heavy_attempted)
    replace_fields = set(desired.get("_replace_fields") or [])
    if any(desired.get(k) and (not tags.get(k) or k in replace_fields) for k in ["artist", "title", "album", "release_date", "genre", "bpm", "musical_key"]) or cover_download or heavy_attempted:
        repaired = _atomic_metadata_update(path, desired, heavy, cover_download)
        if repaired:
            tags = _read_tags(path)
            desired = {**desired, **{k: tags.get(k) or desired.get(k) for k in ["artist", "title", "album", "release_date", "genre", "bpm", "musical_key"]}}
            cover = tags.get("cover") or cover

    stat_after = path.stat()
    missing: set[str] = set()
    warnings = _cover_quality(cover)
    for field in ["artist", "title", "album", "release_date", "genre"]:
        val = desired.get(field)
        if not val or (field == "genre" and clean_genre(str(val)) == UNKNOWN_GENRE):
            missing.add(field)
    if not technical.get("duration"):
        missing.add("duration")
    if not cover.get("present"):
        missing.add("cover")
    if not heavy.get("fingerprint"):
        missing.add("fingerprint")
    if heavy.get("lufs") is None:
        missing.add("loudness")
    if not desired.get("bpm"):
        missing.add("bpm")
    if not desired.get("musical_key"):
        missing.add("key")
    if heavy.get("radio_confidence") is None:
        missing.add("radio")
    elif float(heavy.get("radio_confidence") or 0) < RADIO_WRITE_CONFIDENCE:
        warnings.add("radio_low_confidence")

    if technical.get("bitrate") and int(technical["bitrate"]) < 128000:
        warnings.add("low_bitrate")
    if technical.get("sample_rate") and int(technical["sample_rate"]) < 32000:
        warnings.add("low_sample_rate")
    if heavy.get("true_peak") is not None and float(heavy["true_peak"]) > 0.0:
        warnings.add("true_peak_over_0dbtp")

    status = _status(missing, warnings, heavy.get("radio_confidence"))
    # failure_count is vanaf v3 uitsluitend voor echte uitzonderingen. Ontbrekende
    # cover/genre zijn verrijkingsstatussen, geen scanfouten.
    failure_count = 0 if not (previous and previous["last_error"]) else int(previous["failure_count"] or 0)
    cover_retry_count = int(previous["cover_retry_count"] or 0) if previous and "cover_retry_count" in previous.keys() else 0
    # Een nieuwe cover-analyzer/bronketen krijgt altijd een verse retrycyclus.
    # Anders kan een oude unresolved-status uit een vorige versie de nieuwe
    # resolver direct op retry 2/3 zetten zonder eerlijke nieuwe kans.
    if previous and int(previous["cover_version"] or 0) < COVER_VERSION:
        cover_retry_count = 0
    metadata_retry_count = int(previous["metadata_retry_count"] or 0) if previous and "metadata_retry_count" in previous.keys() else 0
    next_retry_at = None
    if status == "needs_cover":
        if cover_attempted:
            cover_retry_count += 1
            next_retry_at = _next_retry(cover_retry_count)
        elif cover_deferred:
            next_retry_at = (datetime.now().astimezone() + timedelta(days=1)).isoformat(timespec="seconds")
    elif status == "needs_genre":
        if attempts.get("genre", False):
            metadata_retry_count += 1
            next_retry_at = _next_retry(metadata_retry_count)
        else:
            next_retry_at = (datetime.now().astimezone() + timedelta(days=1)).isoformat(timespec="seconds")
    elif status == "pending_analysis" and heavy_deferred:
        next_retry_at = (datetime.now().astimezone() + timedelta(days=1)).isoformat(timespec="seconds")
    elif status in {"complete", "warning", "low_confidence"}:
        cover_retry_count = 0 if "cover" not in missing else cover_retry_count
        metadata_retry_count = 0 if "genre" not in missing else metadata_retry_count

    values = {
        **technical,
        "artist": desired.get("artist"), "title": desired.get("title"), "album": desired.get("album"), "release_date": desired.get("release_date"), "genre": desired.get("genre"),
        "cover_present": bool(cover.get("present")), "cover_width": cover.get("width"), "cover_height": cover.get("height"), "cover_mime": cover.get("mime"), "cover_hash": cover.get("hash"),
        "bpm": desired.get("bpm") or heavy.get("bpm"), "musical_key": desired.get("musical_key") or heavy.get("musical_key"),
        "lufs": heavy.get("lufs"), "true_peak": heavy.get("true_peak"), "fingerprint": heavy.get("fingerprint"), "fingerprint_duration": heavy.get("fingerprint_duration"),
        "intro_end": heavy.get("intro_end"), "first_vocal": heavy.get("first_vocal"), "safe_talkover_end": heavy.get("safe_talkover_end"),
        "outro_start": heavy.get("outro_start"), "last_vocal": heavy.get("last_vocal"), "fade_out_start": heavy.get("fade_out_start"), "safe_mixout_start": heavy.get("safe_mixout_start"),
        "cold_start": heavy.get("cold_start"), "cold_end": heavy.get("cold_end"), "radio_confidence": heavy.get("radio_confidence"),
        "provenance": provenance,
        "confidence": {"radio": heavy.get("radio_confidence")},
        "missing_fields": missing, "warning_fields": warnings, "scan_status": status,
        "quality_score": _quality_score({**desired, **heavy, **technical}, missing, warnings),
        "audio_hash": _audio_hash(path),
        "failure_count": failure_count, "cover_retry_count": cover_retry_count, "metadata_retry_count": metadata_retry_count, "next_retry_at": next_retry_at,
        "last_changed_at": now_iso() if stat_after.st_mtime_ns != stat_before.st_mtime_ns else (previous["last_changed_at"] if previous else now_iso()),
    }
    return values, repaired


def _write_state(payload: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_PATH)


def current_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"running": False}


def _mark_run_interrupted(run_id: int, trigger: str, total: int, counts: dict[str, int]) -> dict[str, Any]:
    """Sluit een door SIGINT/SIGTERM afgebroken scan atomair af."""
    finished = now_iso()
    previous_state = current_state()
    with connect() as con:
        con.execute(
            """
            UPDATE library_quality_runs
            SET status='interrupted',finished_at=?,processed=?,skipped=?,repaired=?,failed=?,current_file=NULL
            WHERE id=? AND status='running'
            """,
            (finished, counts["processed"], counts["skipped"], counts["repaired"], counts["failed"], run_id),
        )
    result = {
        "ok": False,
        "running": False,
        "interrupted": True,
        "run_id": run_id,
        "trigger": trigger,
        "total": total,
        **counts,
        "current": previous_state.get("current"),
        "current_file": None,
        "started_at": previous_state.get("started_at"),
        "finished_at": finished,
    }
    _write_state(result)
    return result


def scan_library(trigger: str = "manual", force: bool = False, heavy_limit: int = DEFAULT_HEAVY_LIMIT, enrich_limit: int = DEFAULT_ENRICH_LIMIT, cover_limit: int = DEFAULT_COVER_LIMIT, max_files: int = -1) -> dict[str, Any]:
    init_library_quality_db()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lock_file = LOCK_PATH.open("a+")
    run_id: int | None = None
    files: list[Path] = []
    counts = {"processed": 0, "skipped": 0, "repaired": 0, "failed": 0}
    try:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"ok": False, "locked": True, "message": "Er draait al een bibliotheekcontrole."}

        settings = get_settings()
        download_dir = Path(settings.get("download_dir") or DATA_DIR / "downloads").expanduser()
        files = discover_files(download_dir)
        if max_files >= 0:
            files = files[:max_files]
        tracks = _track_map(download_dir)
        budget = Budget(heavy=heavy_limit, enrich=enrich_limit, cover=cover_limit)
        with connect() as con:
            cur = con.execute("INSERT INTO library_quality_runs(trigger,status,started_at,total_files) VALUES(?,?,?,?)", (trigger, "running", now_iso(), len(files)))
            run_id = int(cur.lastrowid)

        _write_state({"running": True, "run_id": run_id, "trigger": trigger, "total": len(files), **counts, "current_file": None, "started_at": now_iso()})

        for index, path in enumerate(files, start=1):
            key = str(path.resolve(strict=False)).casefold()
            track = tracks.get(key)
            if track is None:
                try:
                    track = tracks.get(path.relative_to(download_dir).as_posix().casefold())
                except ValueError:
                    pass
            stat = path.stat()
            with connect() as con:
                previous = con.execute("SELECT * FROM library_quality WHERE file_path=?", (str(path),)).fetchone()
            if _should_skip(previous, stat, force, _source_signature(track)):
                counts["skipped"] += 1
                continue

            state = {"running": True, "run_id": run_id, "trigger": trigger, "total": len(files), **counts, "current": index, "current_file": str(path), "started_at": current_state().get("started_at") or now_iso()}
            _write_state(state)
            label = f"{track.get('artist')} - {track.get('title')}" if track and track.get("artist") and track.get("title") else path.name
            started_one = time.monotonic()
            print(f"[{index}/{len(files)}] {label} ...", flush=True)
            try:
                values, repaired = analyze_one(path, track, budget, previous)
                counts["processed"] += 1
                counts["repaired"] += int(repaired)
                with connect() as con:
                    qid = _upsert_result(con, path, track, path.stat(), values)
                    _event(con, qid, str(path), "repaired" if repaired else "scanned", f"status={values['scan_status']} score={values['quality_score']}")
                print(f"[{index}/{len(files)}] klaar · {values['scan_status']} · score {values['quality_score']:.1f} · {time.monotonic()-started_one:.1f}s", flush=True)
            except Exception as exc:
                counts["processed"] += 1; counts["failed"] += 1
                failure_count = (int(previous["failure_count"] or 0) if previous else 0) + 1
                error_status = "audio_corrupt" if isinstance(exc, AudioReadError) else "scan_error"
                missing_error = {"audio"} if error_status == "audio_corrupt" else {"scan"}
                values = {
                    "scan_status": error_status, "quality_score": 0, "missing_fields": missing_error, "warning_fields": set(),
                    "last_error": str(exc)[-2000:], "failure_count": failure_count,
                    "cover_retry_count": int(previous["cover_retry_count"] or 0) if previous and "cover_retry_count" in previous.keys() else 0,
                    "metadata_retry_count": int(previous["metadata_retry_count"] or 0) if previous and "metadata_retry_count" in previous.keys() else 0,
                    "next_retry_at": _next_retry(failure_count),
                    "provenance": {}, "confidence": {},
                }
                with connect() as con:
                    qid = _upsert_result(con, path, track, stat, values)
                    _event(con, qid, str(path), "error", str(exc))
                print(f"[{index}/{len(files)}] FOUT · {type(exc).__name__}: {exc} · {time.monotonic()-started_one:.1f}s", flush=True)

            # Houd UI/status en run-tabel na elk bestand actueel.
            _write_state({"running": True, "run_id": run_id, "trigger": trigger, "total": len(files), **counts, "current": index, "current_file": str(path), "started_at": current_state().get("started_at") or now_iso()})
            if index % 1 == 0:
                with connect() as con:
                    con.execute("UPDATE library_quality_runs SET processed=?,skipped=?,repaired=?,failed=?,current_file=? WHERE id=?", (counts["processed"], counts["skipped"], counts["repaired"], counts["failed"], str(path), run_id))

        finished = now_iso()
        with connect() as con:
            con.execute("UPDATE library_quality_runs SET status='completed',finished_at=?,processed=?,skipped=?,repaired=?,failed=?,current_file=NULL WHERE id=?", (finished, counts["processed"], counts["skipped"], counts["repaired"], counts["failed"], run_id))
        result = {"ok": True, "running": False, "run_id": run_id, "trigger": trigger, "total": len(files), **counts, "finished_at": finished}
        _write_state(result)
        return result
    except KeyboardInterrupt:
        if run_id is not None:
            with contextlib.suppress(Exception):
                _mark_run_interrupted(run_id, trigger, len(files), counts)
        raise
    finally:
        with contextlib.suppress(Exception):
            fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()


def summary() -> dict[str, Any]:
    init_library_quality_db()
    with connect() as con:
        total = int(con.execute("SELECT COUNT(*) FROM library_quality").fetchone()[0])
        by_status = {str(row["scan_status"]): int(row["n"]) for row in con.execute("SELECT scan_status,COUNT(*) n FROM library_quality GROUP BY scan_status")}
        avg = float(con.execute("SELECT COALESCE(AVG(quality_score),0) FROM library_quality").fetchone()[0] or 0)
        missing_cover = int(con.execute("SELECT COUNT(*) FROM library_quality WHERE cover_present=0").fetchone()[0])
        missing_genre = int(con.execute("SELECT COUNT(*) FROM library_quality WHERE genre IS NULL OR trim(genre)='' OR lower(genre)='other'").fetchone()[0])
        missing_radio = int(con.execute("SELECT COUNT(*) FROM library_quality WHERE radio_confidence IS NULL").fetchone()[0])
        low_confidence = int(con.execute("SELECT COUNT(*) FROM library_quality WHERE radio_confidence IS NOT NULL AND radio_confidence<?", (RADIO_WRITE_CONFIDENCE,)).fetchone()[0])
        corrupt = int(con.execute("SELECT COUNT(*) FROM library_quality WHERE scan_status='audio_corrupt'").fetchone()[0])
        duplicate_groups = int(con.execute("SELECT COUNT(*) FROM (SELECT fingerprint FROM library_quality WHERE fingerprint IS NOT NULL GROUP BY fingerprint HAVING COUNT(*)>1)").fetchone()[0])
        run = con.execute("SELECT * FROM library_quality_runs ORDER BY id DESC LIMIT 1").fetchone()
    return {
        "total": total, "average_score": round(avg, 1), "by_status": by_status,
        "missing_cover": missing_cover, "missing_genre": missing_genre, "missing_radio": missing_radio,
        "low_confidence": low_confidence, "audio_corrupt": corrupt, "duplicate_groups": duplicate_groups,
        "radio_write_confidence": RADIO_WRITE_CONFIDENCE,
        "versions": {"metadata": METADATA_VERSION, "cover": COVER_VERSION, "audio": AUDIO_VERSION, "radio": RADIO_VERSION},
        "last_run": dict(run) if run else None, "state": current_state(),
    }


def list_tracks(status: str | None = None, query: str | None = None, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
    init_library_quality_db()
    where: list[str] = []; args: list[Any] = []
    if status:
        where.append("scan_status=?"); args.append(status)
    if query:
        where.append("(lower(COALESCE(artist,'')) LIKE ? OR lower(COALESCE(title,'')) LIKE ? OR lower(file_path) LIKE ?)")
        needle = f"%{query.casefold()}%"; args.extend([needle, needle, needle])
    clause = " WHERE " + " AND ".join(where) if where else ""
    args.extend([max(1, min(int(limit), 1000)), max(0, int(offset))])
    with connect() as con:
        rows = con.execute(
            f"SELECT * FROM library_quality{clause} ORDER BY CASE scan_status WHEN 'audio_corrupt' THEN 0 WHEN 'needs_metadata' THEN 1 WHEN 'needs_cover' THEN 2 WHEN 'needs_genre' THEN 3 WHEN 'low_confidence' THEN 4 ELSE 5 END, updated_at DESC LIMIT ? OFFSET ?",
            args,
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        for key in ["missing_fields", "warning_fields", "provenance_json", "confidence_json"]:
            try: item[key] = json.loads(item[key] or "[]" if key.endswith("fields") else item[key] or "{}")
            except Exception: pass
        result.append(item)
    return result


def recent_events(limit: int = 100) -> list[dict[str, Any]]:
    init_library_quality_db()
    with connect() as con:
        return [dict(row) for row in con.execute("SELECT * FROM library_quality_events ORDER BY id DESC LIMIT ?", (max(1, min(int(limit), 500)),)).fetchall()]


def _interrupt_signal_handler(signum: int, frame: Any) -> None:
    raise KeyboardInterrupt


def main() -> None:
    parser = argparse.ArgumentParser(description="Top40Archiver Library Quality Engine")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("init")
    scan = sub.add_parser("scan")
    scan.add_argument("--trigger", default="cli")
    scan.add_argument("--force", action="store_true")
    scan.add_argument("--heavy-limit", type=int, default=DEFAULT_HEAVY_LIMIT, help="-1 = onbeperkt")
    scan.add_argument("--enrich-limit", type=int, default=DEFAULT_ENRICH_LIMIT, help="-1 = onbeperkt")
    scan.add_argument("--cover-limit", type=int, default=DEFAULT_COVER_LIMIT, help="-1 = onbeperkt")
    scan.add_argument("--max-files", type=int, default=-1, help="maximaal aantal audiobestanden voor deze run; -1 = onbeperkt")
    args = parser.parse_args()
    if args.cmd == "init":
        init_library_quality_db(); print("library-quality database gereed")
    elif args.cmd == "scan":
        previous_term_handler = signal.signal(signal.SIGTERM, _interrupt_signal_handler)
        try:
            result = scan_library(args.trigger, args.force, args.heavy_limit, args.enrich_limit, args.cover_limit, args.max_files)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except KeyboardInterrupt:
            print("\nBibliotheekcontrole onderbroken; status veilig opgeslagen.", flush=True)
            raise SystemExit(130)
        finally:
            signal.signal(signal.SIGTERM, previous_term_handler)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
