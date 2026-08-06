#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR=${TOP40_APP_DIR:-/opt/top40-archiver}
DATA_DIR=${TOP40_DATA_DIR:-/var/lib/top40-archiver}
VENV_DIR="$APP_DIR/venv"
VENV_PY="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"
BACKUP_DIR="$DATA_DIR/backups/1.15.5-$(date +%Y%m%d-%H%M%S)"
INSTALL_COMPLETE=0

[[ $EUID -eq 0 ]] || { echo "Start als root: sudo bash ./install-1.15.5.sh"; exit 1; }
cd "$APP_DIR"

service_diagnostics(){
  echo
  echo "=== Diagnostiek na mislukte service-start ==="
  systemctl status top40-log-reader.service --no-pager -l || true
  systemctl status top40-archiver-ai.service --no-pager -l || true
  journalctl -u top40-log-reader.service -n 80 --no-pager || true
  journalctl -u top40-archiver-ai.service -n 120 --no-pager || true
}

rollback(){
  local rc=$?
  [[ $INSTALL_COMPLETE -eq 1 ]] && return 0
  service_diagnostics
  echo "Installatie mislukt; rollback wordt uitgevoerd."
  if [[ -d "$BACKUP_DIR/app" ]]; then
    rm -rf "$APP_DIR/app"
    cp -a "$BACKUP_DIR/app" "$APP_DIR/app"
  fi
  [[ -f "$BACKUP_DIR/VERSION" ]] && cp "$BACKUP_DIR/VERSION" "$APP_DIR/VERSION"
  systemctl disable --now top40-ai-recovery.timer 2>/dev/null || true
  systemctl daemon-reload || true
  systemctl restart top40-archiver-ai.service || true
  exit "$rc"
}
trap rollback ERR

wait_for_url(){
  local name=$1
  local url=$2
  local attempts=${3:-30}
  local delay=${4:-2}
  local i

  echo "Wachten op $name: $url"
  for ((i=1; i<=attempts; i++)); do
    if curl -fsS --connect-timeout 2 --max-time 5 "$url" >/dev/null 2>&1; then
      echo "$name: bereikbaar na poging $i/$attempts"
      return 0
    fi
    sleep "$delay"
  done

  echo "FOUT: $name werd niet bereikbaar binnen $((attempts * delay)) seconden."
  return 1
}

command -v python3 >/dev/null
command -v sqlite3 >/dev/null || { apt-get update; apt-get install -y sqlite3; }

if [[ ! -x "$VENV_PY" ]]; then
  echo "Virtualenv ontbreekt; wordt opnieuw gemaakt in $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

if [[ ! -x "$VENV_PIP" ]]; then
  "$VENV_PY" -m ensurepip --upgrade
fi

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
systemctl reset-failed top40-archiver-ai.service top40-log-reader.service || true
systemctl restart top40-archiver-ai.service

wait_for_url "logreader" "http://127.0.0.1:8042/healthz" 20 1
wait_for_url "AI Operations Center" "http://127.0.0.1:8041/healthz" 30 2

TOP40_DATA_DIR="$DATA_DIR" PYTHONPATH="$APP_DIR" "$VENV_PY" -m pytest -q tests/test_operations_center.py

# Start de eerste herstelcyclus pas nadat API, logreader en tests gezond zijn.
systemctl start top40-ai-recovery.service

INSTALL_COMPLETE=1
trap - ERR

echo "1.15.5 succesvol geïnstalleerd. Backup: $BACKUP_DIR"
echo "AI-herstelcyclus: iedere vijf minuten via top40-ai-recovery.timer"
