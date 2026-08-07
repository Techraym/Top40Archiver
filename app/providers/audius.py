from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from .base import AudioProvider, ProviderCandidate, ProviderError, default_user_agent


class AudiusProvider(AudioProvider):
    name = "audius"
    SEARCH_URL = "https://api.audius.co/v1/tracks/search"

    def search(self, track: dict[str, Any], *, limit: int = 8) -> list[ProviderCandidate]:
        query = f"{track.get('artist') or ''} {track.get('title') or ''}".strip()
        headers = {"User-Agent": default_user_agent(), "Accept": "application/json"}
        try:
            response = requests.get(
                self.SEARCH_URL,
                params={"query": query, "limit": max(1, min(limit, 10)), "sort_method": "relevant"},
                headers=headers,
                timeout=15,
            )
        except requests.Timeout as exc:
            raise ProviderError("Audius zoekopdracht time-out", category="timeout") from exc
        except requests.RequestException as exc:
            raise ProviderError(f"Audius zoekfout: {exc}", category="network") from exc
        if response.status_code == 429:
            raise ProviderError("Audius rate limit", category="rate_limited", status_code=429)
        if response.status_code == 403:
            raise ProviderError("Audius toegang geweigerd", category="forbidden", status_code=403)
        if not response.ok:
            raise ProviderError(
                f"Audius HTTP {response.status_code}: {response.text[-1000:]}",
                category="http_error",
                status_code=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError("Audius gaf geen geldige JSON terug", category="invalid_response") from exc

        items = payload.get("data") or payload.get("results") or []
        result: list[ProviderCandidate] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            permalink = str(item.get("permalink") or "").strip()
            if permalink.startswith("/"):
                permalink = "https://audius.co" + permalink
            if permalink and not permalink.startswith("http"):
                permalink = "https://audius.co/" + permalink.lstrip("/")
            if not permalink.startswith("http"):
                continue
            user = item.get("user") if isinstance(item.get("user"), dict) else {}
            release_date = str(item.get("release_date") or item.get("releaseDate") or "")
            year = None
            if release_date:
                try:
                    year = datetime.fromisoformat(release_date.replace("Z", "+00:00")).year
                except ValueError:
                    try:
                        year = int(release_date[:4])
                    except (TypeError, ValueError):
                        year = None
            result.append(
                ProviderCandidate(
                    provider=self.name,
                    url=permalink,
                    title=str(item.get("title") or "").strip(),
                    artist=str(user.get("name") or user.get("handle") or "").strip() or None,
                    duration=float(item.get("duration")) if item.get("duration") else None,
                    year=year,
                    isrc=str(item.get("isrc") or "").strip() or None,
                    source_id=str(item.get("id") or "").strip() or None,
                    uploader=str(user.get("name") or "").strip() or None,
                    description=str(item.get("description") or "").strip()[:2000] or None,
                    metadata={
                        "downloadable": item.get("downloadable"),
                        "is_streamable": item.get("is_streamable") or item.get("isStreamable"),
                        "genre": item.get("genre"),
                        "play_count": item.get("play_count") or item.get("playCount"),
                    },
                )
            )
        return [item for item in result if item.title][:limit]
