from app.metadata import artist_bucket, clean_genre, track_relative_path


def test_genre_folder_is_safe():
    assert clean_genre("Hip-Hop/Rap") == "Hip-Hop & Rap"
    assert clean_genre("") == "Onbekend"


def test_artist_bucket_letter_digit_and_symbol():
    assert artist_bucket("Beyoncé") == "B"
    assert artist_bucket("2 Unlimited") == "2"
    assert artist_bucket("#1 Dads") == "#"
    assert artist_bucket("?And The Mysterians") == "TEKEN"


def test_relative_path():
    path = track_relative_path("Pop", "Adele", "Hello")
    assert path.as_posix() == "Pop/A/Adele - Hello.mp3"
