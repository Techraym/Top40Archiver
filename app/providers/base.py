from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, category: str = "error", status_code: int | None = None):
        super().__init__(message)
        self.category = category
        self.status_code = status_code


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    enabled: bool
    priority: int
    max_concurrent: int
    requests_per_minute: int
    min_delay_seconds: float
    error_backoff_seconds: int


@dataclass
class ProviderCandidate:
    provider: str
    url: str
    title: str
    artist: str | None = None
    duration: float | None = None
    album: str | None = None
    year: int | None = None
    isrc: str | None = None
    source_id: str | None = None
    uploader: str | None = None
    channel: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_match_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "artist": self.artist,
            "duration": self.duration,
            "album": self.album,
            "year": self.year,
            "isrc": self.isrc,
            "uploader": self.uploader,
            "channel": self.channel,
            "description": self.description,
        }


class AudioProvider(ABC):
    name: str

    def __init__(self, config: ProviderConfig):
        self.config = config

    @abstractmethod
    def search(self, track: dict[str, Any], *, limit: int = 8) -> list[ProviderCandidate]:
        raise NotImplementedError

    def health_probe(self) -> dict[str, Any]:
        return {"ok": True, "provider": self.name}

    def download(self, candidate: ProviderCandidate, destination_dir: Path, *, timeout: int = 600) -> Path:
        return ytdlp_download_original(candidate.url, destination_dir, timeout=timeout, provider=self.name)


def yt_dlp_executable() -> Path:
    binary = Path(sys.executable).with_name("yt-dlp")
    if not binary.exists():
        raise ProviderError(f"yt-dlp niet gevonden: {binary}", category="configuration")
    return binary


def ytdlp_runtime_args() -> list[str]:
    deno = Path("/usr/local/bin/deno")
    if not deno.exists():
        return []
    return ["--js-runtimes", f"deno:{deno}", "--remote-components", "ejs:github"]


def _category_from_output(text: str) -> str:
    lowered = str(text or "").casefold()
    # Lokale DNS/routingproblemen zijn geen bewijs dat een provider ongezond is.
    # Houd transportfouten daarom los van provider-specifieke circuit breakers.
    if any(
        marker in lowered
        for marker in (
            "temporary failure in name resolution",
            "failed to resolve",
            "name or service not known",
            "network is unreachable",
            "no route to host",
        )
    ):
        return "network"
    # DRM is een eigenschap van deze kandidaat, niet een storing van de hele
    # provider. Houd deze categorie apart zodat de circuit breaker niet onnodig
    # de bron als geheel degradeert.
    if "drm protected" in lowered or "drm-protected" in lowered or "this video is drm" in lowered:
        return "drm"
    if "429" in lowered or "too many requests" in lowered or "rate limit" in lowered:
        return "rate_limited"
    if "captcha" in lowered:
        return "captcha"
    if "403" in lowered or "forbidden" in lowered:
        return "forbidden"
    if "timeout" in lowered or "timed out" in lowered:
        return "timeout"
    if "unavailable" in lowered or "not available" in lowered or "private" in lowered:
        return "unavailable"
    return "error"


def run_ytdlp_json(target: str, *, timeout: int = 75, extra_args: list[str] | None = None) -> dict[str, Any]:
    cmd = [
        str(yt_dlp_executable()),
        "--ignore-config",
        "--skip-download",
        "--dump-single-json",
        "--socket-timeout",
        "20",
        "--retries",
        "1",
        "--extractor-retries",
        "1",
        *ytdlp_runtime_args(),
        *(extra_args or []),
        target,
    ]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ProviderError(f"yt-dlp timeout voor {target}", category="timeout") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "yt-dlp fout")[-3000:]
        raise ProviderError(detail, category=_category_from_output(detail))
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ProviderError("yt-dlp gaf geen geldige JSON terug", category="invalid_response") from exc
    if not isinstance(payload, dict):
        raise ProviderError("yt-dlp resultaat is geen object", category="invalid_response")
    return payload


def candidate_from_ytdlp(provider: str, item: dict[str, Any]) -> ProviderCandidate | None:
    url = str(item.get("webpage_url") or item.get("original_url") or item.get("url") or "").strip()
    if not url.startswith("http"):
        item_id = str(item.get("id") or "").strip()
        if provider in {"youtube", "youtube_music"} and item_id:
            url = f"https://www.youtube.com/watch?v={item_id}"
    title = str(item.get("track") or item.get("title") or "").strip()
    if not title or not url.startswith("http"):
        return None
    year = item.get("release_year") or item.get("year")
    try:
        year = int(year) if year else None
    except (TypeError, ValueError):
        year = None
    duration = item.get("duration")
    try:
        duration = float(duration) if duration else None
    except (TypeError, ValueError):
        duration = None
    return ProviderCandidate(
        provider=provider,
        url=url,
        title=title,
        artist=str(item.get("artist") or item.get("creator") or "").strip() or None,
        duration=duration,
        album=str(item.get("album") or "").strip() or None,
        year=year,
        isrc=str(item.get("isrc") or "").strip() or None,
        source_id=str(item.get("id") or "").strip() or None,
        uploader=str(item.get("uploader") or "").strip() or None,
        channel=str(item.get("channel") or "").strip() or None,
        description=str(item.get("description") or "").strip()[:2000] or None,
        metadata={
            "extractor": item.get("extractor"),
            "extractor_key": item.get("extractor_key"),
            "availability": item.get("availability"),
        },
    )


def ytdlp_download_original(
    url: str,
    destination_dir: Path,
    *,
    timeout: int,
    provider: str,
    extra_args: list[str] | None = None,
) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    output = str(destination_dir / "source.%(ext)s")
    cmd = [
        str(yt_dlp_executable()),
        "--ignore-config",
        "--no-playlist",
        "--no-overwrites",
        "--socket-timeout",
        "30",
        "--retries",
        "2",
        "--extractor-retries",
        "2",
        "-f",
        "bestaudio/best",
        "--print",
        "after_move:filepath",
        "--output",
        output,
        *ytdlp_runtime_args(),
        *(extra_args or []),
        url,
    ]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ProviderError(f"{provider} download timeout", category="timeout") from exc
    files = [p for p in destination_dir.iterdir() if p.is_file() and p.stat().st_size > 0]
    if completed.returncode != 0 or not files:
        detail = (completed.stderr or completed.stdout or f"{provider} download mislukt")[-4000:]
        raise ProviderError(detail, category=_category_from_output(detail))
    printed = [Path(line.strip()) for line in completed.stdout.splitlines() if line.strip().startswith("/")]
    for path in reversed(printed):
        if path.is_file() and path.parent == destination_dir:
            return path
    return max(files, key=lambda p: p.stat().st_size)


def default_user_agent() -> str:
    return os.getenv(
        "TOP40_PROVIDER_USER_AGENT",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36 Top40Archiver/1.16.10",
    )
