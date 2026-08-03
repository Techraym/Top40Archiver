from app.spotify import score_spotify_candidate


def test_matching_spotify_candidate_scores_high():
    candidate = {
        "name": "Dancing Queen",
        "artists": [{"name": "ABBA"}],
    }
    assert score_spotify_candidate("ABBA", "Dancing Queen", candidate) > 0.9


def test_wrong_candidate_scores_lower():
    candidate = {
        "name": "Bohemian Rhapsody",
        "artists": [{"name": "Queen"}],
    }
    assert score_spotify_candidate("ABBA", "Dancing Queen", candidate) < 0.6
