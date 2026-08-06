#!/usr/bin/env bash
set -euo pipefail

APP="/opt/top40-archiver"
DB="/var/lib/top40-archiver/top40.sqlite3"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="$APP/backups/musicbrainz_covers_$STAMP"

cd "$APP"

echo "=== Backup maken ==="
sudo mkdir -p "$BACKUP"
sudo cp -a app/main.py app/db.py app/templates/index.html app/static/live.js app/static/style.css "$BACKUP/"

cat <<'PY' | sudo tee app/cover_art.py >/dev/null
from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import quote

import requests

from .db import connect

MUSICBRAINZ_SEARCH = "https://musicbrainz.org/ws/2/recording/"
COVER_ART_RELEASE = "https://coverartarchive.org/release/{release_id}/front-500"
USER_AGENT = "Top40Archiver/1.12 (https://github.com/Techraym/Top40Archiver)"
_LOCK = threading.Lock()
_RUNNING = False


def _norm(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    return " ".join(value.split())


def _score(artist: str, title: str, recording: dict) -> float:
    wanted_artist = _norm(artist)
    wanted_title = _norm(title)
    found_title = _norm(recording.get("title") or "")
    credits = recording.get("artist-credit") or []
    found_artist = _norm(" ".join(str(x.get("name") or "") for x in credits if isinstance(x, dict)))
    return (
        SequenceMatcher(None, wanted_title, found_title).ratio() * 0.68
        + SequenceMatcher(None, wanted_artist, found_artist).ratio() * 0.32
    )


def lookup_cover(artist: str, title: str) -> dict[str, str]:
    query = f'recording:"{title}" AND artist:"{artist}"'
    response = requests.get(
        MUSICBRAINZ_SEARCH,
        params={"query": query, "fmt": "json", "limit": 8},
        headers={"User-Agent": USER_AGENT},
        timeout=25,
    )
    response.raise_for_status()
    recordings = list(response.json().get("recordings") or [])
    recordings.sort(key=lambda item: _score(artist, title, item), reverse=True)

    for recording in recordings:
        if _score(artist, title, recording) < 0.62:
            continue
        releases = recording.get("releases") or []
        releases.sort(key=lambda item: (not bool(item.get("date")), str(item.get("date") or "9999")))
        for release in releases:
            release_id = str(release.get("id") or "").strip()
            if not release_id:
                continue
            url = COVER_ART_RELEASE.format(release_id=quote(release_id))
            try:
                check = requests.head(
                    url,
                    headers={"User-Agent": USER_AGENT},
                    timeout=15,
                    allow_redirects=True,
                )
                if check.status_code == 200:
                    return {
                        "cover_url": url,
                        "cover_source": "cover_art_archive",
                        "musicbrainz_recording_id": str(recording.get("id") or ""),
                        "musicbrainz_release_id": release_id,
                    }
            except requests.RequestException:
                continue
    return {}


def fill_missing_covers(limit: int = 80) -> int:
    with _LOCK:
        with connect() as con:
            rows = con.execute(
                """
                SELECT id,artist,title
                FROM tracks
                WHERE cover_checked_at IS NULL
                   OR (cover_url IS NULL AND cover_checked_at < datetime('now','-30 days'))
                ORDER BY CASE WHEN id IN (
                    SELECT track_id FROM chart_entries
                    UNION SELECT track_id FROM tipparade_entries
                ) THEN 0 ELSE 1 END,
                updated_at DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 200)),),
            ).fetchall()

        updated = 0
        for row in rows:
            result = {}
            try:
                result = lookup_cover(row["artist"], row["title"])
            except Exception:
                result = {}

            checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            with connect() as con:
                con.execute(
                    """
                    UPDATE tracks
                    SET cover_url=?,cover_source=?,musicbrainz_recording_id=?,
                        musicbrainz_release_id=?,cover_checked_at=?
                    WHERE id=?
                    """,
                    (
                        result.get("cover_url"),
                        result.get("cover_source"),
                        result.get("musicbrainz_recording_id"),
                        result.get("musicbrainz_release_id"),
                        checked_at,
                        row["id"],
                    ),
                )
            updated += 1
            time.sleep(1.05)
        return updated


def start_cover_backfill(limit: int = 80) -> None:
    global _RUNNING
    if _RUNNING:
        return

    def worker() -> None:
        global _RUNNING
        _RUNNING = True
        try:
            fill_missing_covers(limit)
        finally:
            _RUNNING = False

    threading.Thread(target=worker, name="cover-art-backfill", daemon=True).start()
PY

echo "=== Databasekolommen toevoegen ==="
sudo -u top40archiver sqlite3 "$DB" <<'SQL'
ALTER TABLE tracks ADD COLUMN cover_url TEXT;
ALTER TABLE tracks ADD COLUMN cover_source TEXT;
ALTER TABLE tracks ADD COLUMN musicbrainz_recording_id TEXT;
ALTER TABLE tracks ADD COLUMN musicbrainz_release_id TEXT;
ALTER TABLE tracks ADD COLUMN cover_checked_at TEXT;
SQL

# Bovenstaande ALTER-opdrachten kunnen bij herhaald uitvoeren fouten geven; controleer en herstel idempotent via db.py.
sudo python3 - <<'PY'
from pathlib import Path

path = Path('/opt/top40-archiver/app/db.py')
text = path.read_text(encoding='utf-8')
insert_after = '    "spotify_checked_at": "TEXT",\n'
addition = (
    '    "cover_url": "TEXT",\n'
    '    "cover_source": "TEXT",\n'
    '    "musicbrainz_recording_id": "TEXT",\n'
    '    "musicbrainz_release_id": "TEXT",\n'
    '    "cover_checked_at": "TEXT",\n'
)
if '"cover_url": "TEXT"' not in text:
    if insert_after not in text:
        raise SystemExit('FOUT: invoegpunt in db.py niet gevonden')
    text = text.replace(insert_after, insert_after + addition, 1)
path.write_text(text, encoding='utf-8')
PY

echo "=== Backend koppelen ==="
sudo python3 - <<'PY'
from pathlib import Path

path = Path('/opt/top40-archiver/app/main.py')
text = path.read_text(encoding='utf-8')
if 'from .cover_art import start_cover_backfill' not in text:
    text = text.replace('from .dashboard import download_chart, history_progress, storage_status\n', 'from .cover_art import start_cover_backfill\nfrom .dashboard import download_chart, history_progress, storage_status\n', 1)
text = text.replace('def startup() -> None:\n    init_db()\n', 'def startup() -> None:\n    init_db()\n    start_cover_backfill(80)\n', 1)
path.write_text(text, encoding='utf-8')
PY

echo "=== Tabellen en live-updates uitbreiden ==="
sudo python3 - <<'PY'
from pathlib import Path

path = Path('/opt/top40-archiver/app/templates/index.html')
text = path.read_text(encoding='utf-8')
old = '<td><b>{{ x.artist }}</b></td><td>{{ x.title }}'
new = '<td><div class="artist-cell">{% if x.cover_url %}<img class="track-cover" src="{{ x.cover_url }}" alt="" loading="lazy" referrerpolicy="no-referrer">{% else %}<span class="cover-placeholder">&#9835;</span>{% endif %}<b>{{ x.artist }}</b></div></td><td>{{ x.title }}'
if 'class="artist-cell"' not in text:
    text = text.replace(old, new)
for version in ('22','23','24'):
    text = text.replace(f'/static/style.css?v={version}', '/static/style.css?v=25')
    text = text.replace(f'/static/live.js?v={version}', '/static/live.js?v=25')
path.write_text(text, encoding='utf-8')

path = Path('/opt/top40-archiver/app/static/live.js')
text = path.read_text(encoding='utf-8')
start = text.find('  function chartRows(rows, statusLabels) {')
end = text.find('\n\n  function updateChart(', start)
replacement = '''  function chartRows(rows, statusLabels) {
    return rows.length
      ? rows.map((row) => {
          const cover = row.cover_url
            ? `<img class="track-cover" src="${escapeHtml(row.cover_url)}" alt="" loading="lazy" referrerpolicy="no-referrer">`
            : '<span class="cover-placeholder">&#9835;</span>';
          return `
          <tr class="${row.is_new ? "new" : ""}">
            <td><span class="position">${escapeHtml(row.position)}</span></td>
            <td><div class="artist-cell">${cover}<b>${escapeHtml(row.artist)}</b></div></td>
            <td>${escapeHtml(row.title)} ${row.is_new ? '<span class="new-label">NIEUW</span>' : ""}</td>
            <td><span class="status-badge status-${escapeHtml(row.download_status)}">${escapeHtml(statusLabels[row.download_status] || row.download_status)}</span></td>
          </tr>`;
        }).join("")
      : '<tr><td colspan="4" class="empty">Nog geen editie verwerkt.</td></tr>';
  }'''
if start != -1 and end != -1:
    text = text[:start] + replacement + text[end:]
path.write_text(text, encoding='utf-8')
PY

sudo tee -a app/static/style.css >/dev/null <<'CSS'

/* MusicBrainz/Cover Art Archive afbeeldingen + lichte invoervelden */
input,select,textarea,.search-form input,.retry-form input,.settings-grid input,.settings-grid select {
  background:#fff!important;color:#181817!important;border:1px solid #d9d6cf!important;
  box-shadow:none!important;-webkit-text-fill-color:#181817!important;
}
input::placeholder,textarea::placeholder{color:#8a877f!important;opacity:1}
input:focus,select:focus,textarea:focus{outline:3px solid rgba(239,88,70,.14)!important;border-color:#ef5846!important}
.artist-cell{min-width:190px;display:flex;align-items:center;gap:12px}
.track-cover,.cover-placeholder{width:42px;height:42px;flex:0 0 42px;border-radius:8px;border:1px solid #e7e4de;box-shadow:0 3px 10px rgba(30,28,24,.08)}
.track-cover{display:block;object-fit:cover;background:#f2f1ed}
.cover-placeholder{display:grid;place-items:center;color:#ef5846;background:linear-gradient(145deg,#fff3ef,#f7eee9);font-size:18px;font-weight:700}
td{vertical-align:middle}
CSS

echo "=== Syntax en service controleren ==="
sudo -u top40archiver "$APP/venv/bin/python" -m py_compile app/main.py app/db.py app/cover_art.py
sudo systemctl restart top40-archiver-web.service
sleep 3
curl -fsS http://127.0.0.1:8040/ >/dev/null

echo "KLAAR. MusicBrainz en Cover Art Archive zijn actief."
echo "De eerste 80 ontbrekende hoezen worden op de achtergrond verwerkt."
echo "Backup: $BACKUP"
