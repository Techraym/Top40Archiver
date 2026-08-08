from app.download_matching import score_candidate


def test_exact_artist_title_with_good_duration_is_accepted():
    track = {"artist": "Coldplay", "title": "Viva La Vida", "duration_ms": 242000}
    candidate = {"artist": "Coldplay", "title": "Viva La Vida", "duration": 245}
    decision = score_candidate(track, candidate)
    assert decision.score >= 92
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


def test_exact_identity_without_provider_duration_can_be_verified_after_download():
    track = {"artist": "Hazell Dean", "title": "Who's Leaving Who", "duration_ms": 225000}
    candidate = {"artist": "Hazell Dean", "title": "Who's Leaving Who"}
    decision = score_candidate(track, candidate)
    assert decision.score >= 92
    assert decision.accepted is True
    assert decision.excellent is False
    assert decision.reason == "strong_identity_verify_after_download"
    assert decision.duration_difference is None


def test_legacy_track_without_reference_duration_accepts_only_very_strong_identity():
    track = {"artist": "INXS", "title": "Never Tear Us Apart", "duration_ms": None}
    candidate = {"artist": "INXS", "title": "Never Tear Us Apart", "duration": 231}
    decision = score_candidate(track, candidate)
    assert decision.score == 100.0
    assert decision.accepted is True
    assert decision.excellent is False
    assert decision.reason == "strong_identity_without_reference_duration"


def test_provider_artist_prefix_is_removed_before_legacy_title_scoring():
    track = {"artist": "INXS", "title": "Never Tear Us Apart", "duration_ms": None}
    candidate = {
        "title": "INXS - Never Tear Us Apart (Official Music Video)",
        "duration": 231,
    }
    decision = score_candidate(track, candidate)
    assert decision.score == 100.0
    assert decision.components["artist"] == 30.0
    assert decision.components["title"] == 35.0
    assert decision.accepted is True
    assert decision.reason == "strong_identity_without_reference_duration"


def test_collaboration_prefix_with_ampersand_matches_with_wording():
    track = {
        "artist": "UB40 with Chrissie Hynde",
        "title": "Breakfast In Bed",
        "duration_ms": None,
    }
    candidate = {
        "title": "UB40 & Chrissie Hynde - Breakfast In Bed",
        "duration": 197,
    }
    decision = score_candidate(track, candidate)
    assert decision.score == 100.0
    assert decision.accepted is True


def test_legacy_track_without_reference_duration_rejects_30_second_preview():
    track = {"artist": "Belinda Carlisle", "title": "Circle In The Sand", "duration_ms": None}
    candidate = {"artist": "Belinda Carlisle", "title": "Circle In The Sand", "duration": 30}
    decision = score_candidate(track, candidate)
    assert decision.score == 100.0
    assert decision.accepted is False
    assert decision.reason == "preview_duration"


def test_legacy_track_without_reference_duration_rejects_implausibly_long_candidate():
    track = {"artist": "Artist", "title": "Song", "duration_ms": None}
    candidate = {"artist": "Artist", "title": "Song", "duration": 1200}
    decision = score_candidate(track, candidate)
    assert decision.accepted is False
    assert decision.reason == "implausible_long_duration"


def test_legacy_track_without_reference_duration_still_rejects_cover():
    track = {"artist": "INXS", "title": "Never Tear Us Apart", "duration_ms": None}
    candidate = {"artist": "INXS", "title": "Never Tear Us Apart (Cover)", "duration": 231}
    decision = score_candidate(track, candidate)
    assert decision.accepted is False
    assert any(item["marker"] == "cover" for item in decision.penalties)


def test_missing_duration_does_not_rescue_weak_identity():
    track = {"artist": "Hazell Dean", "title": "Who's Leaving Who", "duration_ms": 225000}
    candidate = {"artist": "Someone Else", "title": "Who's Leaving Who"}
    decision = score_candidate(track, candidate)
    assert decision.accepted is False


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


def test_normalized_score_exposes_available_evidence_budget():
    track = {"artist": "Artist", "title": "Song", "duration_ms": 200000}
    candidate = {"artist": "Artist", "title": "Song"}
    decision = score_candidate(track, candidate)
    assert decision.components["available_max"] == 65.0
    assert decision.components["raw_positive"] == 65.0
