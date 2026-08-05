from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime

from .config import DATA_DIR, DB_PATH, DEFAULT_DOWNLOAD_DIR

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS editions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  edition_key TEXT NOT NULL UNIQUE,
  chart_date TEXT NOT NULL,
  year INTEGER NOT NULL,
  week INTEGER NOT NULL,
  source_url TEXT NOT NULL,
  checked_at TEXT NOT NULL,
  track_count INTEGER NOT NULL DEFAULT 0,
  new_count INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'completed',
  error TEXT
);

CREATE TABLE IF NOT EXISTS tipparade_editions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  edition_key TEXT NOT NULL UNIQUE,
  chart_date TEXT NOT NULL,
  year INTEGER NOT NULL,
  week INTEGER NOT NULL,
  source_url TEXT NOT NULL,
  checked_at TEXT NOT NULL,
  track_count INTEGER NOT NULL DEFAULT 0,
  new_count INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'completed',
  error TEXT
);

CREATE TABLE IF NOT EXISTS tracks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  artist TEXT NOT NULL,
  title TEXT NOT NULL,
  normalized_artist TEXT NOT NULL,
  normalized_title TEXT NOT NULL,
  first_chart_date TEXT NOT NULL,
  first_edition TEXT NOT NULL,
  first_position INTEGER NOT NULL,
  peak_position INTEGER NOT NULL,
  last_position INTEGER NOT NULL,
  processed_at TEXT NOT NULL,
  download_status TEXT NOT NULL DEFAULT 'pending',
  youtube_url TEXT,
  genre TEXT,
  mp3_filename TEXT,
  error_message TEXT,
  download_attempts INTEGER NOT NULL DEFAULT 0,
  custom_search_query TEXT,
  updated_at TEXT NOT NULL,
  UNIQUE(normalized_artist, normalized_title)
);

CREATE TABLE IF NOT EXISTS chart_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  edition_id INTEGER NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
  track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  is_new INTEGER NOT NULL DEFAULT 0,
  UNIQUE(edition_id, position),
  UNIQUE(edition_id, track_id)
);

CREATE TABLE IF NOT EXISTS tipparade_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  edition_id INTEGER NOT NULL REFERENCES tipparade_editions(id) ON DELETE CASCADE,
  track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  is_new INTEGER NOT NULL DEFAULT 0,
  UNIQUE(edition_id, position),
  UNIQUE(edition_id, track_id)
);

CREATE INDEX IF NOT EXISTS idx_tracks_status ON tracks(download_status);
CREATE INDEX IF NOT EXISTS idx_tracks_search ON tracks(normalized_artist, normalized_title);
CREATE INDEX IF NOT EXISTS idx_editions_year_week ON editions(year, week);
CREATE INDEX IF NOT EXISTS idx_tipparade_editions_year_week ON tipparade_editions(year, week);
CREATE INDEX IF NOT EXISTS idx_tipparade_entries_track ON tipparade_entries(track_id);
"""

DEFAULTS = {
    "start_date": date.today().isoformat(),
    "weekly_day": "Fri",
    "weekly_time": "10:00",
    "download_dir": DEFAULT_DOWNLOAD_DIR,
    "download_workers": "2",
    "max_download_attempts": "3",
    "search_template": "{artist} - {title}",
    "last_edition": "",
    "last_tipparade_edition": "",
    "tipparade_enabled": "1",
    "spotify_validation_enabled": "1",
    "spotify_min_match_score": "0.70",
    "history_enabled": "0",
    "history_start_year": "1965",
    "history_start_week": "1",
    "history_next_year": "1965",
    "history_next_week": "1",
    "history_batch_weeks": "10",
    "history_delay_seconds": "2",
    "history_download_limit": "5",
    "history_status": "idle",
    "history_last_error": "",
    "history_last_edition": "",
    "history_completed_at": "",
    # De Tipparade begon op 15 juli 1967: ISO-week 28.
    "tip_history_start_year": "1967",
    "tip_history_start_week": "28",
    "tip_history_next_year": "1967",
    "tip_history_next_week": "28",
    "tip_history_status": "idle",
    "tip_history_last_error": "",
    "tip_history_last_edition": "",
    "tip_history_completed_at": "",
}

TRACK_MIGRATION_COLUMNS = {
    "first_chart_type": "TEXT NOT NULL DEFAULT 'top40'",
    "seen_top40": "INTEGER NOT NULL DEFAULT 0",
    "seen_tipparade": "INTEGER NOT NULL DEFAULT 0",
    "top40_peak_position": "INTEGER",
    "top40_last_position": "INTEGER",
    "tipparade_peak_position": "INTEGER",
    "tipparade_last_position": "INTEGER",
    "spotify_id": "TEXT",
    "spotify_url": "TEXT",
    "spotify_artist": "TEXT",
    "spotify_title": "TEXT",
    "spotify_album": "TEXT",
    "spotify_release_date": "TEXT",
    "spotify_duration_ms": "INTEGER",
    "spotify_isrc": "TEXT",
    "spotify_match_score": "REAL",
    "spotify_status": "TEXT NOT NULL DEFAULT 'unchecked'",
    "spotify_checked_at": "TEXT",
    "youtube_match_score": "REAL",
    "youtube_channel": "TEXT",
    "youtube_duration_seconds": "INTEGER",
}


@contextmanager
def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _ensure_columns(con: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in con.execute(f"PRAGMA table_info({table})")}
    for name, definition in columns.items():
        if name not in existing:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def init_db():
    with connect() as con:
        con.executescript(SCHEMA)
        _ensure_columns(con, "tracks", TRACK_MIGRATION_COLUMNS)

        # Records uit oudere versies waren uitsluitend Top 40-records.
        con.execute(
            """
            UPDATE tracks
            SET seen_top40=1,
                first_chart_type=COALESCE(NULLIF(first_chart_type,''),'top40'),
                top40_peak_position=COALESCE(top40_peak_position, peak_position),
                top40_last_position=COALESCE(top40_last_position, last_position)
            WHERE id IN (SELECT DISTINCT track_id FROM chart_entries)
            """
        )

        for key, value in DEFAULTS.items():
            con.execute(
                "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
                (key, value),
            )

        # Migreer alleen de oude meegeleverde standaard. Een zelf ingestelde
        # zoektemplate blijft bewust onaangetast.
        con.execute(
            """
            UPDATE settings
            SET value='{artist} - {title}'
            WHERE key='search_template'
              AND lower(trim(value))='{artist} - {title} official audio'
            """
        )

        # Oude, volledig uitgeputte zoekfouten die duidelijk op ontbrekend
        # bronmateriaal wijzen worden niet opnieuw als technische fout getoond.
        max_attempts_row = con.execute(
            "SELECT value FROM settings WHERE key='max_download_attempts'"
        ).fetchone()
        try:
            max_attempts = max(1, int(max_attempts_row["value"]))
        except (TypeError, ValueError, KeyError):
            max_attempts = 3

        con.execute(
            """
            UPDATE tracks
            SET download_status='unavailable',
                error_message=(
                    'Automatisch als niet beschikbaar gemarkeerd na eerdere '
                    'volledige zoekpogingen. De hitlijstnotering blijft bewaard. '
                    'Laatste fout: ' || COALESCE(error_message,'')
                ),
                updated_at=?
            WHERE download_status='failed'
              AND download_attempts>=?
              AND (
                    lower(COALESCE(error_message,'')) LIKE '%geen youtube-resultaten gevonden%'
                 OR lower(COALESCE(error_message,'')) LIKE '%geen betrouwbaar youtube-resultaat%'
                 OR lower(COALESCE(error_message,'')) LIKE '%youtube-resultaat bevat geen bruikbare url%'
                 OR lower(COALESCE(error_message,'')) LIKE '%video unavailable%'
                 OR lower(COALESCE(error_message,'')) LIKE '%private video%'
                 OR lower(COALESCE(error_message,'')) LIKE '%removed by the uploader%'
              )
            """,
            (now_iso(), max_attempts),
        )


def get_settings(con=None):
    own = con is None
    ctx = connect() if own else None
    if own:
        con = ctx.__enter__()
    try:
        return {row["key"]: row["value"] for row in con.execute("SELECT key,value FROM settings")}
    finally:
        if own:
            ctx.__exit__(None, None, None)


def set_settings(values):
    with connect() as con:
        for key, value in values.items():
            con.execute(
                """
                INSERT INTO settings(key,value) VALUES(?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, str(value)),
            )


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")
