from app.genre_rules import artist_bucket, final_genre, normalize_genre
from app.metadata import track_relative_path


def test_closed_genre_normalization_matches_genresplitter():
    assert normalize_genre("Alternative Rock") == "Alternative"
    assert normalize_genre("Indie Rock") == "Indie"
    assert normalize_genre("Pop Punk") == "Punk"
    assert normalize_genre("Electro House") == "House"
    assert normalize_genre("Hip-Hop") == "Hip-Hop"
    assert normalize_genre("Synthpop") == "Pop"
    assert normalize_genre("Onbekend genre") == "Other"


def test_special_overrides_match_genresplitter():
    assert final_genre("Jannes", "Een gewone plaat", "Pop") == "Piratenmuziek"
    assert final_genre("Various", "Merry Christmas", "Pop") == "Christmas"


def test_artist_buckets_match_genresplitter():
    assert artist_bucket("2 Unlimited") == "0-9"
    assert artist_bucket("ABBA") == "A"
    assert artist_bucket("Édith Piaf") == "!-?"
    assert artist_bucket("") == "!-?"


def test_relative_path_uses_windows_safe_genresplitter_buckets():
    assert track_relative_path("Pop", "2 Unlimited", "No Limit").as_posix() == (
        "Pop/0-9/2 Unlimited - No Limit.mp3"
    )
    assert track_relative_path("Pop", "Édith Piaf", "La Vie en rose").as_posix() == (
        "Pop/!-_/Édith Piaf - La Vie en rose.mp3"
    )
