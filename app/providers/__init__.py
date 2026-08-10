from __future__ import annotations

from typing import Any

from .audiomack import AudiomackProvider
from .audius import AudiusProvider
from .bandcamp import BandcampProvider
from .base import AudioProvider, ProviderConfig
from .soundcloud import SoundCloudProvider
from .youtube import YouTubeProvider
from .youtube_music import YouTubeMusicProvider


PROVIDER_CLASSES: dict[str, type[AudioProvider]] = {
    "soundcloud": SoundCloudProvider,
    "audiomack": AudiomackProvider,
    "audius": AudiusProvider,
    "bandcamp": BandcampProvider,
    "youtube_music": YouTubeMusicProvider,
    "youtube": YouTubeProvider,
}

# De directe YouTube-provider is bewust de eerste bron. In productie bleek een
# latere retry via YouTube regelmatig wel te slagen terwijl eerdere alternatieve
# providers al DRM/preview/transient-fouten hadden opgeleverd. De ruime
# prioriteitsgaten zorgen er bovendien voor dat een begrensde AI-adjustment de
# vaste eerste positie van YouTube niet onbedoeld kan opheffen.
DEFAULT_PROVIDER_CONFIG: dict[str, dict[str, Any]] = {
    "youtube": {
        "enabled": True,
        "priority": 10,
        "max_concurrent": 1,
        "requests_per_minute": 3,
        "min_delay_seconds": 20.0,
        "error_backoff_seconds": 300,
    },
    "youtube_music": {
        "enabled": True,
        "priority": 40,
        "max_concurrent": 1,
        "requests_per_minute": 3,
        "min_delay_seconds": 20.0,
        "error_backoff_seconds": 300,
    },
    "soundcloud": {
        "enabled": True,
        "priority": 80,
        "max_concurrent": 2,
        "requests_per_minute": 30,
        "min_delay_seconds": 3.0,
        "error_backoff_seconds": 120,
    },
    "audiomack": {
        "enabled": True,
        "priority": 120,
        "max_concurrent": 2,
        "requests_per_minute": 30,
        "min_delay_seconds": 3.0,
        "error_backoff_seconds": 120,
    },
    "audius": {
        "enabled": True,
        "priority": 160,
        "max_concurrent": 2,
        "requests_per_minute": 60,
        "min_delay_seconds": 2.0,
        "error_backoff_seconds": 120,
    },
    "bandcamp": {
        "enabled": True,
        "priority": 200,
        "max_concurrent": 1,
        "requests_per_minute": 20,
        "min_delay_seconds": 3.0,
        "error_backoff_seconds": 180,
    },
}


def provider_from_row(row: dict[str, Any]) -> AudioProvider:
    name = str(row["provider"])
    cls = PROVIDER_CLASSES[name]
    config = ProviderConfig(
        name=name,
        enabled=bool(int(row.get("enabled", 1))),
        priority=int(row.get("priority", DEFAULT_PROVIDER_CONFIG[name]["priority"])),
        max_concurrent=max(1, int(row.get("max_concurrent", 1))),
        requests_per_minute=max(1, int(row.get("requests_per_minute", 1))),
        min_delay_seconds=max(0.0, float(row.get("min_delay_seconds", 0))),
        error_backoff_seconds=max(1, int(row.get("error_backoff_seconds", 120))),
    )
    return cls(config)


__all__ = [
    "AudioProvider",
    "ProviderConfig",
    "DEFAULT_PROVIDER_CONFIG",
    "PROVIDER_CLASSES",
    "provider_from_row",
]
