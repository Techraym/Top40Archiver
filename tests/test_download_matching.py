from app.download_matching import score_candidate


def test_exact_artist_title_with_good_duration_is_accepted():
    track = {"artist": "Coldplay", "title": "Viva La Vida", "duration_ms": 242000}
    candidate = {"artist": "Coldplay", "title": "Viva La Vida", "duration": 245}
    decision = score_candidate(track, candidate)
    assert decision.score >= 85
    assert decision.accepted is True
    assert decision.duration_difference == 3.0


def test_full_metadata_can_reach_excellent_match():
    track = {
        "artist": "Artist",
        "title": "Song",
        "duration_ms": 200000,
        "album": "Album",
        "year": 2026,
        "isrc": "NL-AAA-26-12345",
    }
    candidate = {
        "artist": "Artist",
        "title": "Song",
        "duration": 200,
        "album": "Album",
        "year": 2026,
        "isrc": "NLAAA2612345",
    }
    decision = score_candidate(track, candidate)
    assert decision.score == 100.0
    assert decision.accepted is True
    assert decision.excellent is True


def test_unrequested_cover_version_is_rejected():
    track = {"artist": "Artist", "title": "Song", "duration_ms": 200000}
    candidate = {
        "artist": "Artist",
        "title": "Song (Cover)",
        "duration": 200,
        "description": "Acoustic cover version",
    }
    decision = score_candidate(track, candidate)
    assert decision.accepted is False
    assert any(item["marker"] == "cover" for item in decision.penalties)


def test_requested_live_version_is_not_penalized_for_live_marker():
    track = {"artist": "Artist", "title": "Song Live", "duration_ms": 200000}
    candidate = {"artist": "Artist", "title": "Song Live", "duration": 202}
    decision = score_candidate(track, candidate)
    assert not any(item["marker"] == "live" for item in decision.penalties)
    assert decision.accepted is True


def test_duration_over_fifteen_seconds_is_hard_rejected():
    track = {"artist": "Artist", "title": "Song", "duration_ms": 200000}
    candidate = {"artist": "Artist", "title": "Song", "duration": 216}
    decision = score_candidate(track, candidate)
    assert decision.accepted is False
    assert decision.reason == "wrong_duration"
    assert decision.duration_difference == 16.0
