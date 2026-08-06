#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR=${TOP40_APP_DIR:-/opt/top40-archiver}
DATA_DIR=${TOP40_DATA_DIR:-/var/lib/top40-archiver}
BACKUP_DIR="$DATA_DIR/backups/1.15.5-$(date +%Y%m%d-%H%M%S)"

[[ $EUID -eq 0 ]] || { echo "Start als root: sudo ./install-1.15.5.sh"; exit 1; }
cd "$APP_DIR"

rollback(){
  echo "Installatie mislukt; rollback wordt uitgevoerd."
  if [[ -d "$BACKUP_DIR/app" ]]; then rsync -a --delete "$BACKUP_DIR/app/" "$APP_DIR/app/"; fi
  [[ -f "$BACKUP_DIR/VERSION" ]] && cp "$BACKUP_DIR/VERSION" "$APP_DIR/VERSION"
  systemctl disable --now top40-ai-recovery.timer 2>/dev/null || true
  systemctl daemon-reload || true
  systemctl restart top40-archiver-ai.service || true
}
trap rollback ERR

command -v python3 >/dev/null
command -v sqlite3 >/dev/null || { apt-get update; apt-get install -y sqlite3; }
python3 - <<'PY'
import importlib.util
for name in ('fastapi','uvicorn','requests'):
    assert importlib.util.find_spec(name), f"Python-module ontbreekt: {name}"
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

chown -R top40:top40 "$DATA_DIR/ai" || true
python3 - <<'PY'
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
python3 -m pytest -q tests/test_operations_center.py

echo "1.15.5 succesvol geïnstalleerd. Backup: $BACKUP_DIR"
echo "AI-herstelcyclus: iedere vijf minuten via top40-ai-recovery.timer"
trap - ERR
