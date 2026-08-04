from app.downloader import _candidate_score, _unique_queries


def test_autonomous_queries_include_fallbacks_and_canonical_metadata():
    queries = _unique_queries(
        "Original Artist",
        "Song Title (Radio Edit)",
        "Original Artist - Song Title official audio",
        "Canonical Artist",
        "Canonical Song",
    )

    assert queries[0] == "Original Artist - Song Title official audio"
    assert "Canonical Artist - Canonical Song official audio" in queries
    assert "Original Artist Song Title (Radio Edit) topic" in queries
    assert any("Song Title" in query and "Radio Edit" not in query for query in queries)
    assert len(queries) <= 8
    assert len({query.casefold() for query in queries}) == len(queries)


def test_candidate_score_rewards_exact_official_audio_and_duration():
    candidate = {
        "title": "Artist Name - Hit Title (Official Audio)",
        "channel": "Artist Name - Topic",
        "duration": 183,
    }

    score = _candidate_score("Artist Name", "Hit Title", candidate, 181_000)
    assert score >= 0.80


def test_candidate_score_penalizes_unrequested_live_version():
    normal = {
        "title": "Artist Name - Hit Title",
        "channel": "Artist Name - Topic",
        "duration": 183,
    }
    live = {
        "title": "Artist Name - Hit Title Live",
        "channel": "Random Channel",
        "duration": 245,
    }

    assert _candidate_score("Artist Name", "Hit Title", normal, 181_000) > _candidate_score(
        "Artist Name", "Hit Title", live, 181_000
    )
