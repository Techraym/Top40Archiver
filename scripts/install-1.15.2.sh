#!/usr/bin/env bash
set -Eeuo pipefail
APP=/opt/top40-archiver
FROM_UPDATER=0
[ "${1:-}" = "--from-updater" ] && FROM_UPDATER=1
cd "$APP"

if [ "$(id -u)" -ne 0 ]; then
  echo "FOUT: voer uit met sudo."
  exit 1
fi

PYTHONDONTWRITEBYTECODE=1 "$APP/venv/bin/python" -m py_compile \
  app/incident_engine.py app/incident_scan.py app/ai_sidecar.py \
  app/health_engine.py app/health_trends.py app/prediction_engine.py

install -m 0755 scripts/safe-update.sh /usr/local/sbin/top40-archiver-safe-update
install -m 0644 systemd/top40-archiver-auto-update.service /etc/systemd/system/
install -m 0644 systemd/top40-archiver-auto-update.timer /etc/systemd/system/
install -m 0644 systemd/top40-archiver-incident-scan.service /etc/systemd/system/
install -m 0644 systemd/top40-archiver-incident-scan.timer /etc/systemd/system/

systemctl daemon-reload
systemctl enable --now top40-archiver-auto-update.timer
systemctl enable --now top40-archiver-incident-scan.timer

sudo -u top40archiver PYTHONDONTWRITEBYTECODE=1 \
  "$APP/venv/bin/python" -c 'from app.incident_engine import init_incident_schema; init_incident_schema()'

if [ "$FROM_UPDATER" -eq 0 ]; then
  systemctl restart top40-archiver-ai.service
  sleep 3
  curl -fsS http://127.0.0.1:8041/healthz | grep -q '1.15.2'
  curl -fsS -X POST 'http://127.0.0.1:8041/api/incidents/scan?minutes=5' >/dev/null
fi

echo "KLAAR: Top40Archiver 1.15.2 geïnstalleerd."
echo "AI Incident Center: http://$(hostname -I | awk '{print $1}'):8041/"
