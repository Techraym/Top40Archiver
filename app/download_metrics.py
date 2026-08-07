from __future__ import annotations

from typing import Any

from .download_db import provider_dashboard as _provider_dashboard


def provider_dashboard() -> dict[str, Any]:
    """Return provider metrics with direct YouTube as the primary dependency KPI.

    The original DB dashboard remains backward-compatible internally. This view
    derives both user-facing dependency measures from per-provider successful
    downloads in the last 24 hours:

    - youtube_dependency_percent: direct YouTube only;
    - youtube_family_dependency_percent: YouTube Music + YouTube.
    """
    payload = dict(_provider_dashboard())
    providers = list(payload.get("providers") or [])
    by_name = {str(item.get("provider")): item for item in providers}

    total = int(payload.get("downloads_24h") or 0)
    youtube = int((by_name.get("youtube") or {}).get("successes_24h") or 0)
    youtube_music = int((by_name.get("youtube_music") or {}).get("successes_24h") or 0)
    family = youtube + youtube_music

    direct_percent = round(youtube / total * 100, 1) if total else 0.0
    family_percent = round(family / total * 100, 1) if total else 0.0

    payload.update(
        {
            "downloads_24h": total,
            "without_youtube_24h": max(0, total - youtube),
            "without_youtube_family_24h": max(0, total - family),
            "youtube_music_24h": youtube_music,
            "youtube_24h": youtube,
            "youtube_family_24h": family,
            "youtube_dependency_percent": direct_percent,
            "youtube_family_dependency_percent": family_percent,
            "target_youtube_dependency_percent": 10.0,
            "target_met": direct_percent < 10.0 if total else None,
        }
    )
    return payload
