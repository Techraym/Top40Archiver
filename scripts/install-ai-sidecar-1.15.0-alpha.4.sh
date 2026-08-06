#!/usr/bin/env bash
set -euo pipefail

APP=/opt/top40-archiver
cd "$APP"

if ! git diff --quiet || ! git diff --cached --quiet || [ -n "$(git ls-files --others --exclude-standard)" ]; then
  echo "FOUT: lokale wijzigingen gevonden. Commit of backup deze eerst."
  git status --short
  exit 1
fi

STAMP=$(date +%Y%m%d_%H%M%S)
BACKUP="/var/lib/top40-archiver/backups/ai_sidecar_$STAMP"
sudo install -d -o root -g root -m 750 "$BACKUP"
sudo cp -a /etc/systemd/system/top40-archiver-ai.service "$BACKUP/" 2>/dev/null || true
sudo cp -a VERSION "$BACKUP/" 2>/dev/null || true

sudo -u top40archiver "$APP/venv/bin/python" -m py_compile \
  app/health_engine.py app/health_trends.py app/prediction_engine.py app/ai_sidecar.py

sudo install -m 0644 systemd/top40-archiver-ai.service /etc/systemd/system/top40-archiver-ai.service
sudo systemctl daemon-reload
sudo systemctl enable --now top40-archiver-ai.service
sleep 2

curl -fsS http://127.0.0.1:8041/healthz >/dev/null
curl -fsS 'http://127.0.0.1:8041/api/predictions?range=24h' >/dev/null

printf '%s\n' '1.15.0-alpha.4' | sudo tee VERSION >/dev/null
sudo chown root:root VERSION

echo "KLAAR: AI-sidecar actief op http://$(hostname -I | awk '{print $1}'):8041/"
echo "De hoofdinterface op poort 8040 en de coverworker zijn niet gewijzigd."
echo "Backup: $BACKUP"
