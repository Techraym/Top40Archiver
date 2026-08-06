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


def test_startup_recovers_stale_top40_404_cursor():
    con = _settings_connection(
        {
            "history_enabled": "0",
            "history_status": "running",
            "history_next_year": "1970",
            "history_next_week": "53",
            "history_last_edition": "1970-W52",
            "history_last_error": (
                "404 Client Error: Not Found for url: "
                "https://www.top40.nl/top40/1970/week-53"
            ),
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
        values = _read_settings(con)
    finally:
        con.close()

    assert recovered == ["top40:1970-W53"]
    assert values["history_next_year"] == "1971"
    assert values["history_next_week"] == "1"
    assert values["history_last_edition"] == "1970-W52"
    assert values["history_last_error"] == ""
    assert values["history_status"] == "running"
    assert values["history_enabled"] == "1"


def test_startup_does_not_advance_transient_network_failure():
    con = _settings_connection(
        {
            "history_enabled": "1",
            "history_status": "running",
            "history_next_year": "1970",
            "history_next_week": "53",
            "history_last_error": "Read timed out while contacting Top40.nl",
            "history_completed_at": "",
            "tip_history_status": "completed",
            "tip_history_next_year": "2026",
            "tip_history_next_week": "31",
            "tip_history_last_error": "",
            "tip_history_completed_at": "",
        }
    )
    try:
        recovered = _recover_stale_missing_history(con)
        values = _read_settings(con)
    finally:
        con.close()

    assert recovered == []
    assert values["history_next_year"] == "1970"
    assert values["history_next_week"] == "53"
    assert values["history_last_error"].startswith("Read timed out")


def test_auto_updater_validates_sha_and_version():
    updater = (ROOT / "auto-update.sh").read_text(encoding="utf-8")

    assert "REMOTE_VERSION=" in updater
    assert 'LOCAL_VERSION_FILE="$APP_ROOT/VERSION"' in updater
    assert '[ "$LOCAL_SHA" = "$REMOTE_SHA" ]' in updater
    assert '[ "$LOCAL_VERSION" = "$REMOTE_VERSION" ]' in updater
    assert '[ "$APPLIED_VERSION" != "$REMOTE_VERSION" ]' in updater
    assert "Lokale installatie is inconsistent" in updater
