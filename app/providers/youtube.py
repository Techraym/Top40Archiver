from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .base import (
    AudioProvider,
    ProviderCandidate,
    candidate_from_ytdlp,
    run_ytdlp_json,
    ytdlp_download_original,
)


_CONNECTOR_RE = re.compile(
    r"\s+(?:feat\.?|featuring|ft\.?|x|with|vs\.?|&|and|\+)\s+",
    re.I,
)
_VERSION_RE = re.compile(
    r"\s*[\[(](?:official(?: video| audio)?|lyrics?|visuali[sz]er|radio edit|original mix)[^\])]*[\])]\s*",
    re.I,
)


def _spaces(value: object) -> str:
    return " ".join(str(value or "").replace("_", " ").split()).strip()


def _query_variants(track: dict[str, Any]) -> list[str]:
    """Build a small, deterministic set of YouTube queries for chart metadata.

    Current chart feeds frequently encode collaborations as ``x``, ``ft`` or a
    slash-separated display artist while YouTube uses commas, ``feat.`` or only
    the lead artist. A single literal query therefore misses otherwise excellent
    candidates. Keep the set deliberately small because YouTube remains paced to
    one provider action at a time.
    """
    artist = _spaces(track.get("artist"))
    title = _spaces(track.get("title"))
    custom = _spaces(track.get("custom_search_query"))
    clean_title = _spaces(_VERSION_RE.sub(" ", title)) or title

    variants: list[str] = []

    def add(value: str) -> None:
        value = _spaces(value)
        if value and value.casefold() not in {item.casefold() for item in variants}:
            variants.append(value)

    if custom:
        add(custom)
    add(f"{artist} {title}")

    # YouTube and chart metadata disagree most often on collaboration syntax.
    normalized_artist = _spaces(_CONNECTOR_RE.sub(" ", artist.replace("/", " ")))
    if normalized_artist and normalized_artist.casefold() != artist.casefold():
        add(f"{normalized_artist} {clean_title}")

    # Slash-separated chart credits often contain an alternate/remix credit.
    for part in [p.strip() for p in artist.split("/") if p.strip()]:
        add(f"{part} {clean_title}")

    # Also try lead/collaborator names separately. This is especially useful for
    # entries such as "ANOTR ft 54 Ultra" and "Shakira x Burna Boy".
    for part in [p.strip(" ,-/") for p in _CONNECTOR_RE.split(artist) if p.strip(" ,-/")]:
        add(f"{part} {clean_title}")

    # A title can itself contain two chart-display variants separated by a slash.
    for part in [p.strip() for p in title.split("/") if p.strip()]:
        add(f"{normalized_artist or artist} {part}")

    return variants[:6]


class YouTubeProvider(AudioProvider):
    name = "youtube"
    EXTRACTOR_ARGS = ["--extractor-args", "youtube:player_client=mweb"]

    def download(
        self,
        candidate: ProviderCandidate,
        destination_dir: Path,
        *,
        timeout: int = 600,
    ) -> Path:
        return ytdlp_download_original(
            candidate.url,
            destination_dir,
            timeout=timeout,
            provider=self.name,
            extra_args=self.EXTRACTOR_ARGS,
        )

    def search(self, track: dict[str, Any], *, limit: int = 8) -> list[ProviderCandidate]:
        wanted = max(1, min(int(limit), 10))
        queries = _query_variants(track)
        if not queries:
            return []

        # Fetch a few candidates per query and interleave the results. Interleaving
        # prevents the literal first query from filling the complete candidate
        # budget before a normalized collaboration query gets a chance.
        per_query = max(3, min(5, (wanted + len(queries) - 1) // len(queries) + 1))
        buckets: list[list[ProviderCandidate]] = []
        seen: set[str] = set()

        for query in queries:
            payload = run_ytdlp_json(
                f"ytsearch{per_query}:{query}",
                timeout=60,
                extra_args=["--flat-playlist"],
            )
            bucket: list[ProviderCandidate] = []
            for item in payload.get("entries", []) or []:
                if not isinstance(item, dict):
                    continue
                candidate = candidate_from_ytdlp(self.name, item)
                if candidate is None or candidate.url in seen:
                    continue
                seen.add(candidate.url)
                bucket.append(candidate)
            buckets.append(bucket)

        result: list[ProviderCandidate] = []
        index = 0
        while len(result) < wanted and any(index < len(bucket) for bucket in buckets):
            for bucket in buckets:
                if index < len(bucket):
                    result.append(bucket[index])
                    if len(result) >= wanted:
                        break
            index += 1
        return result
