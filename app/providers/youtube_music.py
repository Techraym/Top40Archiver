from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import (
    AudioProvider,
    ProviderCandidate,
    candidate_from_ytdlp,
    run_ytdlp_json,
    ytdlp_download_original,
)


class YouTubeMusicProvider(AudioProvider):
    name = "youtube_music"
    EXTRACTOR_ARGS = ["--extractor-args", "youtube:player_client=web_music"]

    def search(self, track: dict[str, Any], *, limit: int = 8) -> list[ProviderCandidate]:
        query = f"{track.get('artist') or ''} {track.get('title') or ''} official audio".strip()
        payload = run_ytdlp_json(
            f"ytsearch{max(1, min(limit, 10))}:{query}",
            timeout=60,
            extra_args=["--flat-playlist", *self.EXTRACTOR_ARGS],
        )
        result: list[ProviderCandidate] = []
        for item in payload.get("entries", []) or []:
            if not isinstance(item, dict):
                continue
            candidate = candidate_from_ytdlp(self.name, item)
            if candidate is not None:
                result.append(candidate)
        return result[:limit]

    def download(self, candidate: ProviderCandidate, destination_dir: Path, *, timeout: int = 600) -> Path:
        return ytdlp_download_original(
            candidate.url,
            destination_dir,
            timeout=timeout,
            provider=self.name,
            extra_args=self.EXTRACTOR_ARGS,
        )
