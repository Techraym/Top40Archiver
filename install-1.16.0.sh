#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR=${TOP40_APP_DIR:-/opt/top40-archiver}
DATA_DIR=${TOP40_DATA_DIR:-/var/lib/top40-archiver}
VENV_PY="$APP_DIR/venv/bin/python"
BACKUP_DIR="$DATA_DIR/backups/1.16.0-$(date +%Y%m%d-%H%M%S)"
DROPIN=/etc/systemd/system/top40-archiver-ai.service.d/1.16-development-assistant.conf
COMPLETE=0

[[ $EUID -eq 0 ]] || { echo "Start als root: sudo bash ./install-1.16.0.sh"; exit 1; }
cd "$APP_DIR"

rollback(){
  local rc=$?
  [[ $COMPLETE -eq 1 ]] && return 0
  echo "Installatie 1.16.0 mislukt; rollback wordt uitgevoerd."
  if [[ -d "$BACKUP_DIR/app" ]]; then rm -rf "$APP_DIR/app"; cp -a "$BACKUP_DIR/app" "$APP_DIR/app"; fi
  [[ -f "$BACKUP_DIR/VERSION" ]] && cp "$BACKUP_DIR/VERSION" "$APP_DIR/VERSION"
  rm -f "$DROPIN"
  systemctl daemon-reload || true
  systemctl restart top40-archiver-ai.service || true
  journalctl -u top40-archiver-ai.service -n 100 --no-pager || true
  exit "$rc"
}
trap rollback ERR

[[ -x "$VENV_PY" ]] || { echo "Virtualenv ontbreekt: $VENV_PY"; exit 1; }
mkdir -p "$BACKUP_DIR" "$DATA_DIR/ai/development/workspaces" "$DATA_DIR/ai/development/reports" "$DATA_DIR/ai/quarantine"
cp -a app "$BACKUP_DIR/app"
cp VERSION "$BACKUP_DIR/VERSION"

SERVICE_USER=top40archiver
id "$SERVICE_USER" >/dev/null 2>&1 || SERVICE_USER=top40
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR/ai/development" "$DATA_DIR/ai/quarantine"
chmod 0750 "$DATA_DIR/ai/development" "$DATA_DIR/ai/quarantine"

mkdir -p "$(dirname "$DROPIN")"
cat >"$DROPIN" <<EOF
[Service]
ExecStart=
ExecStart=$APP_DIR/venv/bin/uvicorn app.ai_platform:app --host 0.0.0.0 --port 8041
Environment=TOP40_AI_GITHUB_WRITE=0
ReadWritePaths=$DATA_DIR/ai/development $DATA_DIR/ai/quarantine
EOF

"$VENV_PY" -m py_compile app/dev_assistant.py app/dev_assistant_api.py app/ai_platform.py
TOP40_APP_DIR="$APP_DIR" TOP40_DATA_DIR="$DATA_DIR" PYTHONPATH="$APP_DIR" "$VENV_PY" -m pytest -q tests/test_dev_assistant.py tests/test_operations_center.py

systemctl daemon-reload
systemctl restart top40-archiver-ai.service

for i in $(seq 1 30); do
  if curl -fsS --connect-timeout 2 --max-time 5 http://127.0.0.1:8041/healthz >/tmp/top40-1.16-health.json 2>/dev/null; then break; fi
  sleep 2
done

grep -q '"version":"1.16.0"\|"version": "1.16.0"' /tmp/top40-1.16-health.json
curl -fsS http://127.0.0.1:8041/api/development/workspaces >/dev/null

COMPLETE=1
trap - ERR

echo "Top40Archiver 1.16.0 is geïnstalleerd."
echo "Development Assistant: http://$(hostname -I | awk '{print $1}'):8041/development"
echo "GitHub-writes staan standaard uit: TOP40_AI_GITHUB_WRITE=0"
echo "Backup: $BACKUP_DIR"
