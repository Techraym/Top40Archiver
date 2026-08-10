from app import download_metrics


def test_youtube_share_matches_operations_center_example(monkeypatch):
    monkeypatch.setattr(
        download_metrics,
        "_provider_dashboard",
        lambda: {
            "ok": True,
            "downloads_24h": 74,
            "providers": [
                {"provider": "soundcloud", "successes_24h": 35},
                {"provider": "audiomack", "successes_24h": 20},
                {"provider": "audius", "successes_24h": 4},
                {"provider": "bandcamp", "successes_24h": 2},
                {"provider": "youtube_music", "successes_24h": 8},
                {"provider": "youtube", "successes_24h": 5},
            ],
            "jobs": {},
        },
    )

    result = download_metrics.provider_dashboard()

    assert result["downloads_24h"] == 74
    assert result["without_youtube_24h"] == 61
    assert result["youtube_music_24h"] == 8
    assert result["youtube_24h"] == 5
    assert result["youtube_share_percent"] == 6.8
    assert result["youtube_family_share_percent"] == 17.6
    # Compatibility fields remain present, but there is no longer a target to
    # minimize because direct YouTube is now intentionally the primary source.
    assert result["youtube_dependency_percent"] == 6.8
    assert result["youtube_family_dependency_percent"] == 17.6
    assert result["target_youtube_dependency_percent"] is None
    assert result["target_met"] is None
    assert result["youtube_primary_download_source"] is True


def test_provider_ai_keeps_youtube_fixed_first_and_only_tunes_fallbacks():
    source = open("app/provider_ai.py", encoding="utf-8").read()
    assert 'FIXED_FIRST_PROVIDER = "youtube"' in source
    assert "Directe YouTube is door de operator vastgezet" in source
    assert "Je mag die positie, pacing of max_concurrent=1 nooit wijzigen" in source
    assert "fallbackbronnen" in source
    assert 'if provider == FIXED_FIRST_PROVIDER:' in source
    assert "adjustment = 0" in source
