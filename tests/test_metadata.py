from app.metadata import artist_bucket, clean_genre, track_relative_path


def test_genre_folder_uses_closed_genresplitter_rules():
    assert clean_genre("Hip-Hop/Rap") == "Rap"
    assert clean_genre("Hip-Hop") == "Hip-Hop"
    assert clean_genre("") == "Other"
    assert clean_genre("Niet-bestaand genre") == "Other"


def test_artist_bucket_letter_digit_and_symbol():
    assert artist_bucket("Beyoncé") == "B"
    assert artist_bucket("2 Unlimited") == "0-9"
    assert artist_bucket("#1 Dads") == "!-?"
    assert artist_bucket("?And The Mysterians") == "!-?"


def test_relative_path():
    assert track_relative_path("Pop", "Adele", "Hello").as_posix() == (
        "Pop/A/Adele - Hello.mp3"
    )
    assert track_relative_path("Pop", "2 Unlimited", "No Limit").as_posix() == (
        "Pop/0-9/2 Unlimited - No Limit.mp3"
    )
    assert track_relative_path("Other", "#1 Dads", "So Soldier").as_posix() == (
        "Other/!-_/#1 Dads - So Soldier.mp3"
    )
