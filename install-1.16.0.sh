#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR=${TOP40_APP_DIR:-/opt/top40-archiver}
DATA_DIR=${TOP40_DATA_DIR:-/var/lib/top40-archiver}
VENV_PY="$APP_DIR/venv/bin/python"
VENV_PIP="$APP_DIR/venv/bin/pip"
BACKUP_DIR="$DATA_DIR/backups/1.16.0-$(date +%Y%m%d-%H%M%S)"
OLD_DROPIN=/etc/systemd/system/top40-archiver-ai.service.d/1.16-development-assistant.conf
COMPLETE=0

[[ $EUID -eq 0 ]] || { echo "Start als root: sudo bash ./install-1.16.0.sh"; exit 1; }
cd "$APP_DIR"

rollback(){
  local rc=$?
  [[ $COMPLETE -eq 1 ]] && return 0
  echo "Installatie 1.16.0 mislukt; rollback wordt uitgevoerd."
  if [[ -d "$BACKUP_DIR/app" ]]; then rm -rf "$APP_DIR/app"; cp -a "$BACKUP_DIR/app" "$APP_DIR/app"; fi
  [[ -f "$BACKUP_DIR/VERSION" ]] && cp "$BACKUP_DIR/VERSION" "$APP_DIR/VERSION"
  if [[ -f "$BACKUP_DIR/old-dropin" ]]; then
    mkdir -p "$(dirname "$OLD_DROPIN")"
    cp "$BACKUP_DIR/old-dropin" "$OLD_DROPIN"
  fi
  systemctl daemon-reload || true
  systemctl restart top40-log-reader.service 2>/dev/null || true
  systemctl restart top40-archiver-ai.service 2>/dev/null || true
  journalctl -u top40-archiver-ai.service -n 100 --no-pager || true
  exit "$rc"
}
trap rollback ERR

[[ -x "$VENV_PY" ]] || { echo "Virtualenv ontbreekt: $VENV_PY"; exit 1; }
[[ -x "$VENV_PIP" ]] || { echo "pip ontbreekt: $VENV_PIP"; exit 1; }
mkdir -p \
  "$BACKUP_DIR" \
  "$DATA_DIR/ai/development/workspaces" \
  "$DATA_DIR/ai/development/reports" \
  "$DATA_DIR/ai/quarantine"
cp -a app "$BACKUP_DIR/app"
cp VERSION "$BACKUP_DIR/VERSION"
[[ -f "$OLD_DROPIN" ]] && cp "$OLD_DROPIN" "$BACKUP_DIR/old-dropin"

SERVICE_USER=top40archiver
id "$SERVICE_USER" >/dev/null 2>&1 || SERVICE_USER=top40
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR/ai"
chmod 0750 "$DATA_DIR/ai/development" "$DATA_DIR/ai/quarantine" 2>/dev/null || true

echo "Python-dependencies en regressietools controleren..."
"$VENV_PIP" install --upgrade -r requirements.txt
if ! "$VENV_PY" -c 'import pytest' >/dev/null 2>&1; then
  "$VENV_PIP" install 'pytest>=8,<10'
fi

echo "Veilige helpers en systemd-units installeren..."
install -m 0755 scripts/top40-safe-action /usr/local/sbin/top40-safe-action
install -m 0755 scripts/safe-update.sh /usr/local/sbin/top40-archiver-safe-update
for unit in systemd/*.service systemd/*.timer; do
  install -m 0644 "$unit" "/etc/systemd/system/$(basename "$unit")"
done
# De base-unit start vanaf 1.16 rechtstreeks app.ai_platform; deze oude 1.16-
# override is niet meer nodig. Een eventuele 1.15 security-dropin mag blijven.
rm -f "$OLD_DROPIN"

echo "Code en releasecontract testen..."
bash -n update-existing.sh auto-update.sh install-1.16.0.sh scripts/safe-update.sh scripts/install-1.16.0.sh
"$VENV_PY" -m compileall -q app
TEST_DATA=$(mktemp -d /tmp/top40-116-tests.XXXXXX)
(
  TOP40_APP_DIR="$APP_DIR" TOP40_DATA_DIR="$TEST_DATA" PYTHONPATH="$APP_DIR" \
    "$VENV_PY" -m pytest -q \
      tests/test_dev_assistant.py \
      tests/test_operations_center.py \
      tests/test_ai_recovery_strategies.py \
      tests/test_auto_update_contract.py
)
rm -rf "$TEST_DATA"

systemctl daemon-reload
systemctl enable --now top40-log-reader.service
systemctl enable --now top40-archiver-ai.service
systemctl enable --now top40-ai-recovery.timer
systemctl enable --now top40-archiver-auto-update.timer
systemctl restart top40-log-reader.service
systemctl restart top40-archiver-ai.service

for i in $(seq 1 30); do
  if curl -fsS --connect-timeout 2 --max-time 5 http://127.0.0.1:8042/healthz >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS http://127.0.0.1:8042/healthz >/dev/null

for i in $(seq 1 30); do
  if curl -fsS --connect-timeout 2 --max-time 5 http://127.0.0.1:8041/healthz >/tmp/top40-1.16-health.json 2>/dev/null; then break; fi
  sleep 2
done

"$VENV_PY" - /tmp/top40-1.16-health.json <<'PY'
import json,sys
with open(sys.argv[1], encoding='utf-8') as f:
    x=json.load(f)
assert x.get('ok') is True
assert x.get('version') == '1.16.0'
assert x.get('operations_center') is True
assert x.get('recovery_dashboard') is True
assert x.get('development_assistant') is True
assert x.get('production_write') is False
PY
curl -fsS http://127.0.0.1:8041/api/development/workspaces >/dev/null
curl -fsS http://127.0.0.1:8041/api/ai/recovery >/dev/null
curl -fsS http://127.0.0.1:8041/ai-actions >/dev/null

systemctl start top40-ai-recovery.service
[[ -f "$DATA_DIR/ai/last-recovery-report.json" ]]

COMPLETE=1
trap - ERR

echo "Top40Archiver 1.16.0 is geïnstalleerd en auto-update-proof."
echo "Operations Center:      http://$(hostname -I | awk '{print $1}'):8041/"
echo "AI-herstelactiviteiten: http://$(hostname -I | awk '{print $1}'):8041/ai-actions"
echo "Development Assistant:  http://$(hostname -I | awk '{print $1}'):8041/development"
echo "AI-herstelcyclus: iedere vijf minuten via top40-ai-recovery.timer"
echo "Automatische updater: /usr/local/sbin/top40-archiver-safe-update"
echo "GitHub-writes staan standaard uit: TOP40_AI_GITHUB_WRITE=0"
echo "Backup: $BACKUP_DIR"
