#!/usr/bin/env bash
set -euo pipefail

APP="/opt/top40-archiver"
DB="/var/lib/top40-archiver/top40.sqlite3"
STAMP="$(date +%Y%m%d_%H%M%S)"

cd "$APP"

echo "=== Backup service_queue.py ==="
sudo cp -a app/service_queue.py "app/service_queue.py.backup_workers8_$STAMP"

echo "=== Maximale downloadworkers op 8 zetten ==="
sudo python3 - <<'PY'
from pathlib import Path

path = Path('/opt/top40-archiver/app/service_queue.py')
text = path.read_text(encoding='utf-8')

old = 'MAX_DOWNLOAD_WORKERS = 4'
new = 'MAX_DOWNLOAD_WORKERS = 8'

if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit('FOUT: MAX_DOWNLOAD_WORKERS-regel niet gevonden')

path.write_text(text, encoding='utf-8')
PY

echo "=== Database-instelling op 8 zetten ==="
sudo -u top40archiver sqlite3 "$DB" <<'SQL'
INSERT INTO settings(key,value)
VALUES('download_workers','8')
ON CONFLICT(key) DO UPDATE SET value='8';
SQL

echo "=== Syntaxcontrole ==="
sudo -u top40archiver "$APP/venv/bin/python" -m py_compile app/service_queue.py

echo "=== Downloadservice herstarten ==="
sudo systemctl restart top40-archiver-download.service
sleep 2

echo "=== Controle ==="
grep -n '^MAX_DOWNLOAD_WORKERS' app/service_queue.py
sudo -u top40archiver sqlite3 -header -column "$DB" \
  "SELECT key,value FROM settings WHERE key='download_workers';"
systemctl is-active top40-archiver-download.service

echo "KLAAR: muziekdownloads gebruiken maximaal 8 workers."
echo "De coverworker is niet aangepast."
