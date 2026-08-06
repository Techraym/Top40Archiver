#!/usr/bin/env bash
set -Eeuo pipefail
APP=/opt/top40-archiver
cd "$APP"
[ "$(id -u)" -eq 0 ] || { echo 'FOUT: voer uit met sudo.'; exit 1; }

PYTHONDONTWRITEBYTECODE=1 "$APP/venv/bin/python" -m py_compile \
  app/ai_sidecar.py app/quality_diagnostics.py app/diagnostics_run.py \
  app/recovery_engine.py app/incident_engine.py app/log_console.py

install -d -o top40archiver -g top40archiver -m 0750 /var/lib/top40-archiver/ai
install -m 0644 systemd/top40-ai-diagnostics.service /etc/systemd/system/
install -m 0644 systemd/top40-ai-diagnostics.timer /etc/systemd/system/

systemctl daemon-reload
systemctl enable --now top40-ai-diagnostics.timer
systemctl restart top40-archiver-ai.service
sleep 4

curl -fsS http://127.0.0.1:8041/healthz | grep -q '1.15.4'
curl -fsS http://127.0.0.1:8041/api/quality-check >/dev/null
curl -fsS http://127.0.0.1:8041/api/diagnostics >/dev/null

echo 'KLAAR: Top40Archiver 1.15.4 geïnstalleerd.'
echo 'AI Operations: http://SERVER-IP:8041/'
