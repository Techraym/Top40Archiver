from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .base import (
    AudioProvider,
    ProviderCandidate,
    ProviderError,
    candidate_from_ytdlp,
    default_user_agent,
    run_ytdlp_json,
)


class AudiomackProvider(AudioProvider):
    name = "audiomack"
    SEARCH_URL = "https://audiomack.com/search?q={query}"

    def _search_urls(self, query: str, limit: int) -> list[str]:
        url = self.SEARCH_URL.format(query=quote_plus(query))
        try:
            response = requests.get(
                url,
                headers={"User-Agent": default_user_agent(), "Accept": "text/html"},
                timeout=15,
            )
        except requests.Timeout as exc:
            raise ProviderError("Audiomack zoekpagina time-out", category="timeout") from exc
        except requests.RequestException as exc:
            raise ProviderError(f"Audiomack zoekfout: {exc}", category="network") from exc
        if response.status_code == 429:
            raise ProviderError("Audiomack rate limit", category="rate_limited", status_code=429)
        if response.status_code == 403:
            raise ProviderError("Audiomack toegang geweigerd", category="forbidden", status_code=403)
        if not response.ok:
            raise ProviderError(
                f"Audiomack HTTP {response.status_code}",
                category="http_error",
                status_code=response.status_code,
            )

        soup = BeautifulSoup(response.text, "html.parser")
        found: list[str] = []
        seen: set[str] = set()
        for link in soup.select("a[href]"):
            href = urljoin("https://audiomack.com", str(link.get("href") or "").strip())
            parsed = urlparse(href)
            if (parsed.hostname or "").casefold() not in {"audiomack.com", "www.audiomack.com"}:
                continue
            path = parsed.path.rstrip("/")
            if "/song/" not in path:
                continue
            clean = f"https://audiomack.com{path}"
            if clean not in seen:
                seen.add(clean)
                found.append(clean)
            if len(found) >= max(limit * 2, 8):
                break
        return found

    def search(self, track: dict[str, Any], *, limit: int = 8) -> list[ProviderCandidate]:
        query = f"{track.get('artist') or ''} {track.get('title') or ''}".strip()
        result: list[ProviderCandidate] = []
        for url in self._search_urls(query, limit):
            try:
                payload = run_ytdlp_json(url, timeout=45)
            except ProviderError:
                continue
            candidate = candidate_from_ytdlp(self.name, payload)
            if candidate is not None:
                result.append(candidate)
            if len(result) >= limit:
                break
        return result
