from app import download_metrics


def test_youtube_dependency_matches_operations_center_example(monkeypatch):
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
    assert result["youtube_dependency_percent"] == 6.8
    assert result["youtube_family_dependency_percent"] == 17.6
    assert result["target_youtube_dependency_percent"] == 10.0
    assert result["target_met"] is True


def test_provider_ai_uses_direct_dependency_and_keeps_family_secondary():
    source = open("app/provider_ai.py", encoding="utf-8").read()
    assert "direct YouTube dependency below 10 percent" in source
    assert 'snapshot.get("youtube_dependency_percent")' in source
    assert 'snapshot.get("youtube_family_dependency_percent")' in source
    assert "YouTube Music en YouTube" in source
