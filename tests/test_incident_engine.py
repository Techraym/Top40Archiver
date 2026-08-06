from app.incident_engine import classify_line


def test_classifies_youtube_429():
    item = classify_line("ERROR: HTTP Error 429: Too Many Requests")
    assert item is not None
    assert item["category"] == "youtube_rate_limit"
    assert item["severity"] == "critical"


def test_classifies_bot_check():
    item = classify_line("Sign in to confirm you're not a bot")
    assert item is not None
    assert item["category"] == "youtube_bot_check"


def test_classifies_database_lock():
    item = classify_line("sqlite3.OperationalError: database is locked")
    assert item is not None
    assert item["category"] == "database_locked"


def test_ignores_normal_log_line():
    assert classify_line("Download completed successfully") is None
