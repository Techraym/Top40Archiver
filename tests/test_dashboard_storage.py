from app.dashboard import storage_status


def test_storage_status_counts_real_mp3_files(tmp_path):
    first = tmp_path / "Pop" / "A" / "Artiest - Titel.mp3"
    second = tmp_path / "Rock" / "B" / "Band - Nummer.MP3"
    ignored = tmp_path / "Rock" / "B" / "notitie.txt"

    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(b"a" * 1024)
    second.write_bytes(b"b" * 2048)
    ignored.write_bytes(b"x" * 4096)

    status = storage_status(str(tmp_path))

    assert status["exists"] is True
    assert status["mp3_count"] == 2
    assert status["music_bytes"] == 3072
    assert status["music_size_label"] == "3.0 KB"
    assert 0.0 <= float(status["used_percent"]) <= 100.0
    whole, separator, decimals = str(status["used_percent_label"]).partition(".")
    assert whole.isdigit()
    assert separator == "."
    assert len(decimals) == 3
    assert decimals.isdigit()
