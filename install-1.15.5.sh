#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR=${TOP40_APP_DIR:-/opt/top40-archiver}
DATA_DIR=${TOP40_DATA_DIR:-/var/lib/top40-archiver}
VENV_DIR="$APP_DIR/venv"
VENV_PY="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"
BACKUP_DIR="$DATA_DIR/backups/1.15.5-$(date +%Y%m%d-%H%M%S)"

[[ $EUID -eq 0 ]] || { echo "Start als root: sudo bash ./install-1.15.5.sh"; exit 1; }
cd "$APP_DIR"

rollback(){
  echo "Installatie mislukt; rollback wordt uitgevoerd."
  if [[ -d "$BACKUP_DIR/app" ]]; then
    rm -rf "$APP_DIR/app"
    cp -a "$BACKUP_DIR/app" "$APP_DIR/app"
  fi
  [[ -f "$BACKUP_DIR/VERSION" ]] && cp "$BACKUP_DIR/VERSION" "$APP_DIR/VERSION"
  systemctl disable --now top40-ai-recovery.timer 2>/dev/null || true
  systemctl daemon-reload || true
  systemctl restart top40-archiver-ai.service || true
}
trap rollback ERR

command -v python3 >/dev/null
command -v sqlite3 >/dev/null || { apt-get update; apt-get install -y sqlite3; }

if [[ ! -x "$VENV_PY" ]]; then
  echo "Virtualenv ontbreekt; wordt opnieuw gemaakt in $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

if [[ ! -x "$VENV_PIP" ]]; then
  "$VENV_PY" -m ensurepip --upgrade
fi

# Gebruik altijd dezelfde Python-omgeving als de draaiende web- en AI-services.
if ! "$VENV_PY" - <<'PY'
import importlib.util
missing = [name for name in ('fastapi', 'uvicorn', 'requests') if importlib.util.find_spec(name) is None]
raise SystemExit(1 if missing else 0)
PY
then
  echo "Applicatiepakketten ontbreken in de virtualenv; requirements worden geïnstalleerd."
  "$VENV_PIP" install --upgrade pip wheel
  "$VENV_PIP" install -r "$APP_DIR/requirements.txt"
fi

if ! "$VENV_PY" -c 'import pytest' >/dev/null 2>&1; then
  echo "pytest ontbreekt in de virtualenv; wordt geïnstalleerd voor regressietests."
  "$VENV_PIP" install 'pytest>=8,<10'
fi

"$VENV_PY" - <<'PY'
import fastapi, uvicorn, requests, pytest
print('Python-omgeving: OK')
PY

mkdir -p "$BACKUP_DIR" "$DATA_DIR/ai" "$DATA_DIR/backups"
mkdir -p /etc/systemd/system/top40-archiver-ai.service.d
cp -a app "$BACKUP_DIR/app"
cp VERSION "$BACKUP_DIR/VERSION"

install -m 0755 scripts/top40-safe-action /usr/local/sbin/top40-safe-action
install -m 0644 systemd/top40-log-reader.service /etc/systemd/system/top40-log-reader.service
install -m 0644 systemd/top40-ai-recovery.service /etc/systemd/system/top40-ai-recovery.service
install -m 0644 systemd/top40-ai-recovery.timer /etc/systemd/system/top40-ai-recovery.timer

cat >/etc/systemd/system/top40-archiver-ai.service.d/operations-center.conf <<EOF
[Unit]
After=top40-log-reader.service
Wants=top40-log-reader.service

[Service]
Environment=TOP40_LOG_READER_URL=http://127.0.0.1:8042
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=$DATA_DIR
EOF

SERVICE_USER=top40archiver
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  SERVICE_USER=top40
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR/ai"

TOP40_DATA_DIR="$DATA_DIR" PYTHONPATH="$APP_DIR" "$VENV_PY" - <<'PY'
from app.ai_memory import connect
with connect():
    pass
print('ai_memory.sqlite: OK')
PY

systemctl daemon-reload
systemctl enable --now top40-log-reader.service
systemctl enable --now top40-ai-recovery.timer
systemctl restart top40-archiver-ai.service
systemctl start top40-ai-recovery.service

curl -fsS http://127.0.0.1:8042/healthz >/dev/null
curl -fsS http://127.0.0.1:8041/healthz >/dev/null
TOP40_DATA_DIR="$DATA_DIR" PYTHONPATH="$APP_DIR" "$VENV_PY" -m pytest -q tests/test_operations_center.py

echo "1.15.5 succesvol geïnstalleerd. Backup: $BACKUP_DIR"
echo "AI-herstelcyclus: iedere vijf minuten via top40-ai-recovery.timer"
trap - ERR
