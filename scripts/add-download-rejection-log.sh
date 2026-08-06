#!/usr/bin/env bash
set -euo pipefail

APP="/opt/top40-archiver"
DB="/var/lib/top40-archiver/top40.sqlite3"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="/var/lib/top40-archiver/backups/rejection_log_$STAMP"

cd "$APP"

sudo install -d -o root -g root -m 750 "$BACKUP"
sudo cp -a app/service_queue.py "$BACKUP/"

cat <<'PY' | sudo tee app/rejection_log.py >/dev/null
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import DATA_DIR
from .db import connect, now_iso

LOG_FILE = DATA_DIR / "download-rejections.jsonl"


def classify_rejection(reason: str) -> str:
    text = " ".join(str(reason or "").casefold().split())
    rules = (
        ("youtube_bot_check", ("sign in to confirm you're not a bot", "not a bot")),
        ("youtube_private", ("private video", "video is private")),
        ("youtube_removed", ("removed by the uploader", "video unavailable", "this video is unavailable")),
        ("youtube_geo_block", ("not available in your country", "geo-restricted")),
        ("youtube_copyright", ("copyright claim", "copyright")),
        ("no_search_results", ("geen youtube-resultaten gevonden",)),
        ("low_match_score", ("geen betrouwbaar youtube-resultaat", "beste score")),
        ("invalid_source_url", ("geen bruikbare url",)),
        ("rate_limit", ("http error 429", "too many requests")),
        ("forbidden", ("http error 403", "forbidden")),
        ("timeout", ("timeout", "timed out")),
        ("network", ("connection", "network", "temporary failure", "name resolution")),
        ("storage", ("no space left", "read-only file system", "permission denied")),
        ("database", ("database is locked", "sqlite")),
    )
    for category, markers in rules:
        if any(marker in text for marker in markers):
            return category
    return "other"


def _ensure_table() -> None:
    with connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS download_rejection_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              track_id INTEGER,
              artist TEXT NOT NULL,
              title TEXT NOT NULL,
              status TEXT NOT NULL,
              category TEXT NOT NULL,
              reason TEXT NOT NULL,
              attempts INTEGER NOT NULL DEFAULT 0,
              search_query TEXT,
              source_url TEXT,
              created_at TEXT NOT NULL
            )
            """
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_rejection_created_at ON download_rejection_log(created_at)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_rejection_category ON download_rejection_log(category)"
        )


def log_rejection(
    *,
    track_id: int,
    artist: str,
    title: str,
    status: str,
    reason: str,
    attempts: int,
    search_query: str | None = None,
    source_url: str | None = None,
) -> None:
    """Schrijf een afwijzing naar SQLite en JSONL zonder de downloader te blokkeren."""
    try:
        _ensure_table()
        category = classify_rejection(reason)
        created_at = now_iso()
        payload: dict[str, Any] = {
            "track_id": int(track_id),
            "artist": str(artist or ""),
            "title": str(title or ""),
            "status": str(status or "failed"),
            "category": category,
            "reason": str(reason or "")[-3000:],
            "attempts": int(attempts or 0),
            "search_query": str(search_query or "") or None,
            "source_url": str(source_url or "") or None,
            "created_at": created_at,
        }
        with connect() as con:
            con.execute(
                """
                INSERT INTO download_rejection_log(
                  track_id,artist,title,status,category,reason,attempts,
                  search_query,source_url,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    payload["track_id"], payload["artist"], payload["title"],
                    payload["status"], payload["category"], payload["reason"],
                    payload["attempts"], payload["search_query"],
                    payload["source_url"], payload["created_at"],
                ),
            )
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        # Logging mag een download nooit laten mislukken.
        return
PY

sudo python3 - <<'PY'
from pathlib import Path

path = Path('/opt/top40-archiver/app/service_queue.py')
text = path.read_text(encoding='utf-8')

import_line = 'from .rejection_log import log_rejection\n'
anchor = 'from .metadata import UNKNOWN_GENRE, clean_genre, resolve_genre, track_relative_path\n'
if import_line not in text:
    if anchor not in text:
        raise SystemExit('FOUT: import-invoegpunt niet gevonden')
    text = text.replace(anchor, anchor + import_line, 1)

needle = '''        with connect() as con:\n            con.execute(\n                \"\"\"\n                UPDATE tracks\n                SET download_status=?,error_message=?,updated_at=?\n                WHERE id=?\n                \"\"\",\n                (status, message, now_iso(), track_id),\n            )\n        return (track_id, status)\n'''
replacement = '''        with connect() as con:\n            con.execute(\n                \"\"\"\n                UPDATE tracks\n                SET download_status=?,error_message=?,updated_at=?\n                WHERE id=?\n                \"\"\",\n                (status, message, now_iso(), track_id),\n            )\n        log_rejection(\n            track_id=track_id,\n            artist=row[\"artist\"],\n            title=row[\"title\"],\n            status=status,\n            reason=message,\n            attempts=attempts,\n            search_query=query,\n            source_url=source_url,\n        )\n        return (track_id, status)\n'''
if 'log_rejection(' not in text:
    if needle not in text:
        raise SystemExit('FOUT: foutafhandelingsblok niet gevonden')
    text = text.replace(needle, replacement, 1)

path.write_text(text, encoding='utf-8')
PY

sudo -u top40archiver sqlite3 "$DB" <<'SQL'
CREATE TABLE IF NOT EXISTS download_rejection_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  track_id INTEGER,
  artist TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL,
  category TEXT NOT NULL,
  reason TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  search_query TEXT,
  source_url TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rejection_created_at ON download_rejection_log(created_at);
CREATE INDEX IF NOT EXISTS idx_rejection_category ON download_rejection_log(category);

INSERT INTO download_rejection_log(
  track_id,artist,title,status,category,reason,attempts,search_query,source_url,created_at
)
SELECT
  id,artist,title,download_status,
  CASE
    WHEN lower(coalesce(error_message,'')) LIKE '%not a bot%' THEN 'youtube_bot_check'
    WHEN lower(coalesce(error_message,'')) LIKE '%private video%' THEN 'youtube_private'
    WHEN lower(coalesce(error_message,'')) LIKE '%not available in your country%' THEN 'youtube_geo_block'
    WHEN lower(coalesce(error_message,'')) LIKE '%geen youtube-resultaten%' THEN 'no_search_results'
    WHEN lower(coalesce(error_message,'')) LIKE '%geen betrouwbaar youtube-resultaat%' THEN 'low_match_score'
    WHEN lower(coalesce(error_message,'')) LIKE '%timeout%' THEN 'timeout'
    ELSE 'other'
  END,
  coalesce(error_message,'Onbekende afwijsreden'),download_attempts,custom_search_query,youtube_url,updated_at
FROM tracks t
WHERE download_status IN ('failed','unavailable')
  AND NOT EXISTS (
    SELECT 1 FROM download_rejection_log l
    WHERE l.track_id=t.id AND l.created_at=t.updated_at
  );
SQL

cat <<'SH' | sudo tee scripts/show-download-rejections.sh >/dev/null
#!/usr/bin/env bash
set -euo pipefail
DB="/var/lib/top40-archiver/top40.sqlite3"
LIMIT="${1:-50}"
sudo -u top40archiver sqlite3 -header -column "$DB" "
SELECT
  created_at AS tijd,
  category AS categorie,
  status,
  artist,
  title,
  attempts AS pogingen,
  substr(replace(reason,char(10),' '),1,180) AS reden
FROM download_rejection_log
ORDER BY id DESC
LIMIT $LIMIT;
"
SH
sudo chmod +x scripts/show-download-rejections.sh
sudo chown top40archiver:top40archiver app/rejection_log.py
sudo -u top40archiver "$APP/venv/bin/python" -m py_compile app/rejection_log.py app/service_queue.py
sudo systemctl restart top40-archiver-download.service

echo "KLAAR"
echo "SQLite-log: download_rejection_log"
echo "JSONL-log: /var/lib/top40-archiver/download-rejections.jsonl"
echo "Bekijken: /opt/top40-archiver/scripts/show-download-rejections.sh 50"
echo "Backup: $BACKUP"
