import sqlite3

from app.db import (
    UNAVAILABLE_MIGRATION_PREFIX,
    _migrate_exhausted_unavailable_tracks,
    _missing_http_status_text,
)


def _connection() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute(
        """
        CREATE TABLE tracks (
            id INTEGER PRIMARY KEY,
            download_status TEXT NOT NULL,
            download_attempts INTEGER NOT NULL,
            error_message TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    return con


def test_unavailable_migration_executes_valid_sqlite_and_preserves_error():
    con = _connection()
    try:
        con.execute(
            """
            INSERT INTO tracks(
                id,download_status,download_attempts,error_message,updated_at
            ) VALUES(1,'failed',3,'Geen YouTube-resultaten gevonden','oud')
            """
        )

        changed = _migrate_exhausted_unavailable_tracks(con, 3)
        row = con.execute("SELECT * FROM tracks WHERE id=1").fetchone()

        assert changed == 1
        assert row["download_status"] == "unavailable"
        assert row["error_message"].startswith(UNAVAILABLE_MIGRATION_PREFIX)
        assert row["error_message"].endswith("Geen YouTube-resultaten gevonden")
        assert row["updated_at"] != "oud"
    finally:
        con.close()


def test_unavailable_migration_does_not_hide_technical_failure():
    con = _connection()
    try:
        con.execute(
            """
            INSERT INTO tracks(
                id,download_status,download_attempts,error_message,updated_at
            ) VALUES(1,'failed',8,'Schijf is niet schrijfbaar','oud')
            """
        )

        changed = _migrate_exhausted_unavailable_tracks(con, 3)
        row = con.execute("SELECT * FROM tracks WHERE id=1").fetchone()

        assert changed == 0
        assert row["download_status"] == "failed"
        assert row["error_message"] == "Schijf is niet schrijfbaar"
    finally:
        con.close()


def test_stored_history_status_recognizes_402_404_and_410():
    assert _missing_http_status_text("402 Client Error") == 402
    assert _missing_http_status_text("404 Client Error") == 404
    assert _missing_http_status_text("410 Gone") == 410
    assert _missing_http_status_text("503 Service Unavailable") is None
