#!/usr/bin/env bash
set -Eeuo pipefail
APP="/opt/top40-archiver"
FROM_UPDATER=0
[ "${1:-}" = "--from-updater" ] && FROM_UPDATER=1
cd "$APP"

if [ "$(id -u)" -ne 0 ]; then
  echo "FOUT: voer uit met sudo."
  exit 1
fi

export PIP_DISABLE_PIP_VERSION_CHECK=1
"$APP/venv/bin/python" -m pip install --quiet 'mutagen>=1.47,<2' 'Pillow>=10,<12'

PYTHONDONTWRITEBYTECODE=1 "$APP/venv/bin/python" -m py_compile \
  app/id3_cover.py app/main.py app/db.py app/service.py

install -m 0755 scripts/safe-update.sh /usr/local/sbin/top40-archiver-safe-update
install -m 0644 systemd/top40-archiver-auto-update.service /etc/systemd/system/
install -m 0644 systemd/top40-archiver-auto-update.timer /etc/systemd/system/
install -m 0644 systemd/top40-archiver-id3-cover.service /etc/systemd/system/
install -m 0644 systemd/top40-archiver-id3-cover.timer /etc/systemd/system/

systemctl daemon-reload
systemctl enable --now top40-archiver-auto-update.timer
systemctl enable --now top40-archiver-id3-cover.timer

sudo -u top40archiver PYTHONDONTWRITEBYTECODE=1 \
  "$APP/venv/bin/python" -c 'from app.id3_cover import init_id3_cover_columns; init_id3_cover_columns()'

if [ "$FROM_UPDATER" -eq 0 ]; then
  systemctl restart top40-archiver-web.service
  systemctl restart top40-archiver-ai.service 2>/dev/null || true
  sleep 3
  curl -fsS http://127.0.0.1:8040/ >/dev/null
  curl -fsS http://127.0.0.1:8041/healthz >/dev/null 2>&1 || true
fi

echo "KLAAR: Top40Archiver 1.15.1 geïnstalleerd."
echo "Veilige updater: sudo /usr/local/sbin/top40-archiver-safe-update"
echo "Auto-update timer: top40-archiver-auto-update.timer"
echo "ID3-coverworker: top40-archiver-id3-cover.timer"
