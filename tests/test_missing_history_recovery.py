import sqlite3

from app.db import _recover_stale_missing_history
from app.service_history import _http_status_from_exception


def _settings_connection(values: dict[str, str]) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    con.executemany("INSERT INTO settings(key,value) VALUES(?,?)", values.items())
    return con


def test_http_status_is_recognized_when_only_present_in_error_text():
    error = RuntimeError(
        "404 Client Error: Not Found for url: "
        "https://www.top40.nl/top40/1970/week-53"
    )
    assert _http_status_from_exception(error) == 404


def test_http_status_is_recognized_inside_wrapped_exception():
    source = RuntimeError("HTTP 410 while loading historical source")
    wrapper = RuntimeError("Historische download mislukt")
    wrapper.__cause__ = source
    assert _http_status_from_exception(wrapper) == 410


def test_startup_recovery_uses_blacklist_for_known_missing_page():
    con = _settings_connection(
        {
            "history_enabled": "0",
            "history_status": "error",
            "history_next_year": "1970",
            "history_next_week": "53",
            "history_last_edition": "1970-W52",
            "history_last_error": "HTTP 404 voor https://www.top40.nl/top40/1970/week-53",
            "history_completed_at": "",
            "tip_history_status": "running",
            "tip_history_next_year": "1969",
            "tip_history_next_week": "37",
            "tip_history_last_error": "",
            "tip_history_completed_at": "",
        }
    )
    try:
        recovered = _recover_stale_missing_history(con)
        values = {
            row["key"]: row["value"]
            for row in con.execute("SELECT key,value FROM settings")
        }
    finally:
        con.close()

    assert recovered == ["blacklist:top40:1970-W53"]
    assert values["history_next_year"] == "1971"
    assert values["history_next_week"] == "1"
    assert values["history_last_edition"] == "1970-W52"
    assert values["history_last_error"] == ""
    assert values["history_status"] == "running"
    assert values["history_enabled"] == "1"
