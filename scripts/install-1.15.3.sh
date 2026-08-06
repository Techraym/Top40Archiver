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

PYTHONDONTWRITEBYTECODE=1 "$APP/venv/bin/python" -m py_compile \
  app/recovery_engine.py app/incident_engine.py app/log_console.py app/ai_sidecar.py

install -m 0755 scripts/top40-recovery-action /usr/local/sbin/top40-recovery-action
cat > /etc/sudoers.d/top40-archiver-recovery <<'EOF'
top40archiver ALL=(root) NOPASSWD: /usr/local/sbin/top40-recovery-action *
EOF
chmod 0440 /etc/sudoers.d/top40-archiver-recovery
visudo -cf /etc/sudoers.d/top40-archiver-recovery

sudo -u top40archiver PYTHONDONTWRITEBYTECODE=1 \
  "$APP/venv/bin/python" -c 'from app.recovery_engine import init_recovery_tables; init_recovery_tables()'

if [ -f scripts/install-1.15.2.sh ]; then
  bash scripts/install-1.15.2.sh --from-updater
fi

systemctl daemon-reload
systemctl restart top40-archiver-ai.service

if [ "$FROM_UPDATER" -eq 0 ]; then
  sleep 3
  curl -fsS http://127.0.0.1:8041/healthz >/dev/null
  curl -fsS http://127.0.0.1:8041/api/recovery/actions >/dev/null
fi

echo "KLAAR: Top40Archiver 1.15.3 geïnstalleerd."
