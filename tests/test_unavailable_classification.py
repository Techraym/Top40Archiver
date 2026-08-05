from app.service_queue import _failure_is_probably_unavailable


def test_missing_online_media_is_classified_as_unavailable():
    assert _failure_is_probably_unavailable(
        "Geen YouTube-resultaten gevonden. Zoekvarianten: Artiest - Titel"
    )
    assert _failure_is_probably_unavailable(
        "Geen betrouwbaar YouTube-resultaat voor 'Artiest - Titel'"
    )
    assert _failure_is_probably_unavailable("ERROR: [youtube] Private video")


def test_technical_failures_are_not_classified_as_unavailable():
    assert not _failure_is_probably_unavailable("Temporary failure in name resolution")
    assert not _failure_is_probably_unavailable("Permission denied: /mnt/top40-music")
    assert not _failure_is_probably_unavailable("yt-dlp niet gevonden")
