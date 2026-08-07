from __future__ import annotations

from typing import Any

from .base import AudioProvider, ProviderCandidate, candidate_from_ytdlp, run_ytdlp_json


class SoundCloudProvider(AudioProvider):
    name = "soundcloud"

    def search(self, track: dict[str, Any], *, limit: int = 8) -> list[ProviderCandidate]:
        query = f"{track.get('artist') or ''} {track.get('title') or ''}".strip()
        payload = run_ytdlp_json(
            f"scsearch{max(1, min(limit, 10))}:{query}",
            timeout=60,
            extra_args=["--flat-playlist"],
        )
        result: list[ProviderCandidate] = []
        for item in payload.get("entries", []) or []:
            if not isinstance(item, dict):
                continue
            candidate = candidate_from_ytdlp(self.name, item)
            if candidate is not None:
                result.append(candidate)
        return result[:limit]
