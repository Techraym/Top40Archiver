from pathlib import Path
import sqlite3

from app.db import _recover_stale_missing_history


ROOT = Path(__file__).resolve().parents[1]


def _settings_connection(values: dict[str, str]) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    con.executemany(
        "INSERT INTO settings(key,value) VALUES(?,?)",
        list(values.items()),
    )
    return con


def _read_settings(con: sqlite3.Connection) -> dict[str, str]:
    return {
        row["key"]: row["value"]
        for row in con.execute("SELECT key,value FROM settings")
    }


def _base_settings() -> dict[str, str]:
    return {
        "history_enabled": "0",
        "history_status": "running",
        "history_next_year": "1970",
        "history_next_week": "53",
        "history_last_edition": "1970-W52",
        "history_last_error": "",
        "history_completed_at": "",
        "tip_history_status": "running",
        "tip_history_next_year": "1969",
        "tip_history_next_week": "37",
        "tip_history_last_error": "",
        "tip_history_completed_at": "",
    }


def test_startup_blacklists_top40_1970_week_53_without_error_text():
    con = _settings_connection(_base_settings())
    try:
        recovered = _recover_stale_missing_history(con)
        values = _read_settings(con)
    finally:
        con.close()

    assert recovered == ["blacklist:top40:1970-W53"]
    assert values["history_next_year"] == "1971"
    assert values["history_next_week"] == "1"
    assert values["history_last_edition"] == "1970-W52"
    assert values["history_last_error"] == ""
    assert values["history_status"] == "running"
    assert values["history_enabled"] == "1"


def test_startup_blacklist_clears_stored_404_url():
    values = _base_settings()
    values["history_last_error"] = (
        "404 Client Error: Not Found for url: "
        "https://www.top40.nl/top40/1970/week-53"
    )
    con = _settings_connection(values)
    try:
        recovered = _recover_stale_missing_history(con)
        stored = _read_settings(con)
    finally:
        con.close()

    assert recovered == ["blacklist:top40:1970-W53"]
    assert stored["history_next_year"] == "1971"
    assert stored["history_next_week"] == "1"
    assert stored["history_last_error"] == ""


def test_startup_does_not_advance_transient_network_failure_on_normal_week():
    values = _base_settings()
    values.update(
        {
            "history_enabled": "1",
            "history_next_year": "1971",
            "history_next_week": "2",
            "history_last_error": "Read timed out while contacting Top40.nl",
            "tip_history_status": "completed",
            "tip_history_next_year": "2026",
            "tip_history_next_week": "31",
        }
    )
    con = _settings_connection(values)
    try:
        recovered = _recover_stale_missing_history(con)
        stored = _read_settings(con)
    finally:
        con.close()

    assert recovered == []
    assert stored["history_next_year"] == "1971"
    assert stored["history_next_week"] == "2"
    assert stored["history_last_error"].startswith("Read timed out")


def test_auto_updater_validates_sha_and_version():
    updater = (ROOT / "auto-update.sh").read_text(encoding="utf-8")

    assert "REMOTE_VERSION=" in updater
    assert 'LOCAL_VERSION_FILE="$APP_ROOT/VERSION"' in updater
    assert '[ "$LOCAL_SHA" = "$REMOTE_SHA" ]' in updater
    assert '[ "$LOCAL_VERSION" = "$REMOTE_VERSION" ]' in updater
    assert '[ "$APPLIED_VERSION" != "$REMOTE_VERSION" ]' in updater
    assert "Lokale installatie is inconsistent" in updater
