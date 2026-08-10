from __future__ import annotations

from typing import Any

from .download_db import provider_dashboard as _provider_dashboard


def provider_dashboard() -> dict[str, Any]:
    """Return provider metrics for the fixed YouTube-first source policy.

    YouTube share is now informational rather than a target to minimize. Direct
    YouTube is intentionally the first source; YouTube Music and the remaining
    providers are fallbacks whenever the first source cannot complete the track.
    """
    payload = dict(_provider_dashboard())
    providers = list(payload.get("providers") or [])
    by_name = {str(item.get("provider")): item for item in providers}

    total = int(payload.get("downloads_24h") or 0)
    youtube = int((by_name.get("youtube") or {}).get("successes_24h") or 0)
    youtube_music = int((by_name.get("youtube_music") or {}).get("successes_24h") or 0)
    family = youtube + youtube_music
    non_youtube = max(0, total - family)

    direct_percent = round(youtube / total * 100, 1) if total else 0.0
    family_percent = round(family / total * 100, 1) if total else 0.0

    payload.update(
        {
            "downloads_24h": total,
            "without_youtube_24h": non_youtube,
            "without_youtube_family_24h": non_youtube,
            "youtube_music_24h": youtube_music,
            "youtube_24h": youtube,
            "youtube_family_24h": family,
            "youtube_dependency_percent": direct_percent,
            "youtube_family_dependency_percent": family_percent,
            "youtube_share_percent": direct_percent,
            "youtube_family_share_percent": family_percent,
            "youtube_primary_download_source": True,
            "target_youtube_dependency_percent": None,
            "target_met": None,
        }
    )
    return payload
