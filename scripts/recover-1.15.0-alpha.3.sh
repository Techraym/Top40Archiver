#!/usr/bin/env bash
set -euo pipefail

APP="/opt/top40-archiver"
DB="/var/lib/top40-archiver/top40.sqlite3"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="/var/lib/top40-archiver/backups/recovery_1.15.0-alpha.3_${STAMP}"

cd "$APP"

if [ "$(id -u)" -ne 0 ]; then
  echo "FOUT: voer dit script uit met sudo of als root."
  exit 1
fi

if [ ! -d .git ]; then
  echo "FOUT: $APP is geen Git-repository."
  exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet || [ -n "$(git ls-files --others --exclude-standard)" ]; then
  echo "FOUT: er staan lokale wijzigingen in $APP."
  echo "Sla deze eerst op in een commit of maak een aparte backupbranch."
  git status --short
  exit 1
fi

echo "=== Volledige recovery-backup maken ==="
install -d -o root -g root -m 750 "$BACKUP"
cp -a app "$BACKUP/app"
cp -a scripts "$BACKUP/scripts"
cp -a systemd "$BACKUP/systemd" 2>/dev/null || true
cp -a VERSION "$BACKUP/VERSION" 2>/dev/null || true
cp -a "$DB" "$BACKUP/top40.sqlite3" 2>/dev/null || true
systemctl cat top40-archiver-web.service > "$BACKUP/top40-archiver-web.service.txt" 2>/dev/null || true
systemctl cat top40-archiver-cover-art.service > "$BACKUP/top40-archiver-cover-art.service.txt" 2>/dev/null || true
systemctl cat top40-archiver-cover-art.timer > "$BACKUP/top40-archiver-cover-art.timer.txt" 2>/dev/null || true

echo "Backup: $BACKUP"

echo "=== Lichte dashboardvormgeving herstellen ==="
bash scripts/apply-modern-light-ui.sh
bash scripts/apply-light-settings-panel.sh

echo "=== MusicBrainz en Cover Art Archive herstellen ==="
bash scripts/apply-musicbrainz-cover-art.sh
bash scripts/fix-cover-art-worker.sh

echo "=== Bestaande queue- en logverbeteringen opnieuw toepassen ==="
bash scripts/apply-history-queue-limit.sh
bash scripts/apply-clear-unavailable-list.sh
bash scripts/add-download-rejection-log.sh

echo "=== Veilige workerinstelling afdwingen ==="
if command -v sqlite3 >/dev/null 2>&1 && [ -f "$DB" ]; then
  sudo -u top40archiver sqlite3 "$DB" "
    INSERT INTO settings(key,value) VALUES('download_workers','1')
    ON CONFLICT(key) DO UPDATE SET value='1';
  "
fi

echo "=== Versie vastleggen ==="
printf '%s\n' '1.15.0-alpha.3' > VERSION
chown root:root VERSION
chmod 0644 VERSION

echo "=== Python-syntax controleren ==="
sudo -u top40archiver "$APP/venv/bin/python" -m py_compile \
  app/main.py \
  app/db.py \
  app/service.py \
  app/cover_art.py

echo "=== Databasekolommen controleren ==="
sudo -u top40archiver sqlite3 -header -column "$DB" "
SELECT name
FROM pragma_table_info('tracks')
WHERE name IN (
  'cover_url',
  'cover_source',
  'musicbrainz_recording_id',
  'musicbrainz_release_id',
  'cover_checked_at'
)
ORDER BY name;
"

COLUMN_COUNT="$(sudo -u top40archiver sqlite3 "$DB" "
SELECT COUNT(*)
FROM pragma_table_info('tracks')
WHERE name IN (
  'cover_url',
  'cover_source',
  'musicbrainz_recording_id',
  'musicbrainz_release_id',
  'cover_checked_at'
);
")"

if [ "$COLUMN_COUNT" != "5" ]; then
  echo "FOUT: niet alle coverkolommen zijn aanwezig."
  exit 1
fi

echo "=== Services activeren ==="
systemctl daemon-reload
systemctl enable --now top40-archiver-cover-art.timer
systemctl restart top40-archiver-web.service

sleep 3

echo "=== Runtimecontroles ==="
curl -fsS http://127.0.0.1:8040/ >/dev/null
systemctl is-active --quiet top40-archiver-web.service
systemctl is-enabled --quiet top40-archiver-cover-art.timer

if grep -q 'color-scheme: dark' app/static/style.css; then
  echo "WAARSCHUWING: donkere basisregels zijn nog aanwezig; controleer visueel of de lichte recoveryregels onderaan correct winnen."
fi

if ! grep -q 'track-cover' app/static/style.css; then
  echo "FOUT: covervormgeving ontbreekt in style.css."
  exit 1
fi

if ! grep -q 'cover_url' app/db.py; then
  echo "FOUT: coverkolommen ontbreken in app/db.py."
  exit 1
fi

echo "=== Recoveryrapport ==="
echo "Versie: $(cat VERSION)"
echo "Dashboard: http://$(hostname -I | awk '{print $1}'):8040/"
echo "Coverworker timer: $(systemctl is-active top40-archiver-cover-art.timer 2>/dev/null || true)"
echo "Downloadworkers: $(sudo -u top40archiver sqlite3 "$DB" "SELECT value FROM settings WHERE key='download_workers';")"
echo "Backup: $BACKUP"
echo
echo "KLAAR: v1.15.0-alpha.3 Recovery is toegepast."
