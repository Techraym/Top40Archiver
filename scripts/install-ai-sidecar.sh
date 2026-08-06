#!/usr/bin/env bash
set -euo pipefail
cd /opt/top40-archiver

./scripts/check-local-work-before-update.sh

TEMPLATE="app/templates/index.html"
SCRIPT_TAG='  <script src="/static/ai_sidecar_link.js?v=1" defer></script>'
if ! grep -q 'ai_sidecar_link.js' "$TEMPLATE"; then
  sed -i "/<script src=\"\/static\/live.js/a\\$SCRIPT_TAG" "$TEMPLATE"
  echo "AI-knop toegevoegd aan de bestaande hoofdpagina zonder de stylesheet te wijzigen."
fi

sudo install -m 0644 systemd/top40-archiver-ai.service /etc/systemd/system/top40-archiver-ai.service
sudo systemctl daemon-reload
sudo systemctl enable --now top40-archiver-ai.service
sudo systemctl restart top40-archiver-web.service

echo "AI sidecar: http://$(hostname -I | awk '{print $1}'):8041/"
sudo systemctl status top40-archiver-ai.service --no-pager --full
