#!/bin/bash
set -Eeuo pipefail
shopt -s nullglob

[ "$(id -u)" -eq 0 ] || { echo "Voer dit script als root uit."; exit 1; }

SRC=$(cd "$(dirname "$0")" && pwd)
APP_ROOT=/opt/top40-archiver
APP_DIR="$APP_ROOT/app"
NEXT_APP="$APP_ROOT/app.next"
DATA_DIR=/var/lib/top40-archiver
STATE_DIR="$DATA_DIR/update-state"
AI_DIR="$DATA_DIR/ai"
BACKUP_ROOT="$DATA_DIR/backups/auto-update"
WEB_SERVICE=top40-archiver-web.service
DOWNLOAD_SERVICE=top40-archiver-download.service
DOWNLOAD_TIMER=top40-archiver-download.timer
AI_SERVICE=top40-archiver-ai.service
LOG_SERVICE=top40-log-reader.service
RECOVERY_SERVICE=top40-ai-recovery.service
RECOVERY_TIMER=top40-ai-recovery.timer
VERSION=$(tr -d '[:space:]' < "$SRC/VERSION" 2>/dev/null || echo unknown)
STAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$BACKUP_ROOT/$STAMP"
BACKUP_APP="$APP_ROOT/app.backup_$STAMP"
VENV_PY="$APP_ROOT/venv/bin/python"
VENV_PIP="$APP_ROOT/venv/bin/pip"
SAFE_ACTION=/usr/local/sbin/top40-safe-action
SAFE_UPDATER=/usr/local/sbin/top40-archiver-safe-update
SWAPPED=0
CONFIG_CHANGED=0
UPDATE_COMPLETE=0

[ -d "$APP_ROOT" ] || { echo "$APP_ROOT bestaat niet."; exit 1; }
[ -d "$SRC/app" ] || { echo "Bronmap $SRC/app ontbreekt."; exit 1; }
[ -x "$VENV_PY" ] || { echo "Python virtualenv ontbreekt: $VENV_PY"; exit 1; }
[ -x "$VENV_PIP" ] || { echo "pip ontbreekt: $VENV_PIP"; exit 1; }
[ -d "$SRC/systemd" ] || { echo "systemd-bronmap ontbreekt."; exit 1; }
[ -f "$SRC/scripts/top40-safe-action" ] || { echo "Veilige actiewrapper ontbreekt."; exit 1; }
[ -f "$SRC/scripts/safe-update.sh" ] || { echo "Veilige updater ontbreekt."; exit 1; }

SOURCE_UNITS=("$SRC"/systemd/*.service "$SRC"/systemd/*.timer)
ROOT_FILES=(requirements.txt VERSION update-timer.sh update-from-github.sh auto-update.sh setup-network-share.sh setup-top40-ca-bundle.sh)

wait_for_url() {
  local name=$1
  local url=$2
  local attempts=${3:-30}
  local delay=${4:-1}
  local i
  echo "Wachten op $name: $url"
  for ((i=1; i<=attempts; i++)); do
    if curl -fsS --connect-timeout 2 --max-time 5 "$url" >/dev/null 2>&1; then
      echo "$name is bereikbaar na poging $i/$attempts."
      return 0
    fi
    sleep "$delay"
  done
  echo "FOUT: $name werd niet bereikbaar binnen $((attempts * delay)) seconden."
  return 1
}

service_diagnostics() {
  echo
  echo "=== Update-diagnostiek ==="
  systemctl status "$WEB_SERVICE" --no-pager -l 2>/dev/null || true
  systemctl status "$LOG_SERVICE" --no-pager -l 2>/dev/null || true
  systemctl status "$AI_SERVICE" --no-pager -l 2>/dev/null || true
  systemctl status "$RECOVERY_TIMER" --no-pager -l 2>/dev/null || true
  systemctl status "$RECOVERY_SERVICE" --no-pager -l 2>/dev/null || true
  journalctl -u "$WEB_SERVICE" -n 60 --no-pager -l 2>/dev/null || true
  journalctl -u "$LOG_SERVICE" -n 60 --no-pager -l 2>/dev/null || true
  journalctl -u "$AI_SERVICE" -n 100 --no-pager -l 2>/dev/null || true
  journalctl -u "$RECOVERY_SERVICE" -n 80 --no-pager -l 2>/dev/null || true
}

backup_configuration() {
  mkdir -p "$BACKUP_DIR/root" "$BACKUP_DIR/systemd"

  for name in "${ROOT_FILES[@]}"; do
    if [ -e "$APP_ROOT/$name" ]; then
      cp -a "$APP_ROOT/$name" "$BACKUP_DIR/root/$name"
    else
      touch "$BACKUP_DIR/root/.missing-$name"
    fi
  done

  for src_unit in "${SOURCE_UNITS[@]}"; do
    local name
    name=$(basename "$src_unit")
    if [ -e "/etc/systemd/system/$name" ]; then
      cp -a "/etc/systemd/system/$name" "$BACKUP_DIR/systemd/$name"
    else
      touch "$BACKUP_DIR/systemd/.missing-$name"
    fi
  done

  if [ -e "$SAFE_ACTION" ]; then
    cp -a "$SAFE_ACTION" "$BACKUP_DIR/top40-safe-action"
  else
    touch "$BACKUP_DIR/.missing-top40-safe-action"
  fi
  if [ -e "$SAFE_UPDATER" ]; then
    cp -a "$SAFE_UPDATER" "$BACKUP_DIR/top40-archiver-safe-update"
  else
    touch "$BACKUP_DIR/.missing-top40-archiver-safe-update"
  fi

  # Een consistente DB-backup is beschikbaar voor handmatig herstel zonder
  # tijdens een rollback nieuwe downloadvoortgang stilzwijgend te overschrijven.
  if [ -f "$DATA_DIR/top40.sqlite3" ]; then
    sqlite3 "$DATA_DIR/top40.sqlite3" ".backup '$BACKUP_DIR/top40.sqlite3'"
  fi
  if [ -f "$DATA_DIR/ai_memory.sqlite" ]; then
    sqlite3 "$DATA_DIR/ai_memory.sqlite" ".backup '$BACKUP_DIR/ai_memory.sqlite'" || true
  fi
}

restore_configuration() {
  [ "$CONFIG_CHANGED" -eq 1 ] || return 0
  echo "Configuratie en systemd-units terugzetten..."

  for name in "${ROOT_FILES[@]}"; do
    if [ -e "$BACKUP_DIR/root/$name" ]; then
      cp -a "$BACKUP_DIR/root/$name" "$APP_ROOT/$name"
    elif [ -e "$BACKUP_DIR/root/.missing-$name" ]; then
      rm -f "$APP_ROOT/$name"
    fi
  done

  for src_unit in "${SOURCE_UNITS[@]}"; do
    local name
    name=$(basename "$src_unit")
    if [ -e "$BACKUP_DIR/systemd/$name" ]; then
      cp -a "$BACKUP_DIR/systemd/$name" "/etc/systemd/system/$name"
    elif [ -e "$BACKUP_DIR/systemd/.missing-$name" ]; then
      rm -f "/etc/systemd/system/$name"
    fi
  done

  if [ -e "$BACKUP_DIR/top40-safe-action" ]; then
    cp -a "$BACKUP_DIR/top40-safe-action" "$SAFE_ACTION"
  elif [ -e "$BACKUP_DIR/.missing-top40-safe-action" ]; then
    rm -f "$SAFE_ACTION"
  fi
  if [ -e "$BACKUP_DIR/top40-archiver-safe-update" ]; then
    cp -a "$BACKUP_DIR/top40-archiver-safe-update" "$SAFE_UPDATER"
  elif [ -e "$BACKUP_DIR/.missing-top40-archiver-safe-update" ]; then
    rm -f "$SAFE_UPDATER"
  fi

  systemctl daemon-reload || true
}

rollback_app() {
  if [ "$SWAPPED" -eq 1 ] && [ -d "$BACKUP_APP" ]; then
    echo "Applicatie terugdraaien naar vorige werkende versie..."
    systemctl stop "$AI_SERVICE" "$LOG_SERVICE" "$WEB_SERVICE" 2>/dev/null || true
    rm -rf "$APP_DIR"
    mv "$BACKUP_APP" "$APP_DIR"
    chown -R top40archiver:top40archiver "$APP_DIR"
  fi
}

recover_previous_services() {
  systemctl daemon-reload 2>/dev/null || true
  systemctl reset-failed "$WEB_SERVICE" "$DOWNLOAD_SERVICE" "$AI_SERVICE" "$LOG_SERVICE" 2>/dev/null || true
  systemctl start "$WEB_SERVICE" 2>/dev/null || true
  systemctl start "$DOWNLOAD_SERVICE" 2>/dev/null || true
  systemctl start "$LOG_SERVICE" 2>/dev/null || true
  systemctl start "$AI_SERVICE" 2>/dev/null || true
}

on_exit() {
  local rc=$?
  trap - EXIT
  if [ "$rc" -ne 0 ] && [ "$UPDATE_COMPLETE" -ne 1 ]; then
    echo "FOUT: update is afgebroken met code $rc."
    service_diagnostics
    rollback_app
    restore_configuration
    recover_previous_services
    echo "Rollback afgerond. Backup voor handmatig herstel: $BACKUP_DIR"
  fi
  rm -rf "$NEXT_APP"
  exit "$rc"
}
trap on_exit EXIT

schedule_reboot() {
  local reboot_unit="top40-archiver-reboot-after-update-${STAMP}"
  if command -v systemd-run >/dev/null 2>&1 && [ -x /usr/bin/systemctl ]; then
    systemd-run --quiet \
      --unit="$reboot_unit" \
      --on-active=1min \
      --timer-property=AccuracySec=1s \
      --collect \
      /usr/bin/systemctl --no-wall reboot
    echo "Automatische herstart is gepland over één minuut."
    return 0
  fi
  if command -v shutdown >/dev/null 2>&1; then
    shutdown -r +1 "Top40Archiver-update $VERSION is geïnstalleerd"
    echo "Automatische herstart is gepland over één minuut."
    return 0
  fi
  echo "WAARSCHUWING: automatisch herstarten kon niet worden ingepland."
  return 1
}

mkdir -p \
  "$DATA_DIR/download-temp" \
  "$STATE_DIR" \
  "$AI_DIR/development/workspaces" \
  "$AI_DIR/development/reports" \
  "$AI_DIR/quarantine" \
  "$BACKUP_ROOT"
chmod 755 "$STATE_DIR" "$BACKUP_ROOT"

SERVICE_USER=top40archiver
id "$SERVICE_USER" >/dev/null 2>&1 || SERVICE_USER=top40
chown -R "$SERVICE_USER:$SERVICE_USER" "$AI_DIR"
chmod 0750 "$AI_DIR/development" "$AI_DIR/quarantine" 2>/dev/null || true

for command in curl sqlite3 systemctl runuser; do
  command -v "$command" >/dev/null 2>&1 || { echo "FOUT: vereist commando ontbreekt: $command"; exit 1; }
done

echo "=== Preflight 1.16.0 ==="
echo "Systeempakketten controleren terwijl dashboard actief blijft..."
apt-get update
apt-get install -y ffmpeg ca-certificates curl unzip util-linux openssl sqlite3
update-ca-certificates

echo "Python-pakketten controleren..."
"$VENV_PIP" install --upgrade -r "$SRC/requirements.txt"
if ! "$VENV_PY" -c 'import pytest' >/dev/null 2>&1; then
  "$VENV_PIP" install 'pytest>=8,<10'
fi

if ! command -v deno >/dev/null 2>&1; then
  echo "Deno installeren..."
  curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/opt/deno sh
  ln -sf /opt/deno/bin/deno /usr/local/bin/deno
fi

if [ ! -f /etc/top40-archiver.env ]; then
  cat >/etc/top40-archiver.env <<'EOF'
# Spotify wordt uitsluitend gebruikt als metadata-controle.
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
SPOTIFY_MARKET=NL
EOF
  chmod 600 /etc/top40-archiver.env
  chown root:root /etc/top40-archiver.env
fi

echo "Shell- en Python-syntax controleren..."
bash -n "$SRC/update-existing.sh" "$SRC/auto-update.sh" "$SRC/install-1.16.0.sh" "$SRC/scripts/safe-update.sh" "$SRC/scripts/install-1.16.0.sh"
"$VENV_PY" -m compileall -q "$SRC/app"

echo "Regressietests in geïsoleerde testdata uitvoeren..."
TEST_DATA=$(mktemp -d /tmp/top40-update-tests.XXXXXX)
(
  cd "$SRC"
  TOP40_DATA_DIR="$TEST_DATA" TOP40_APP_DIR="$SRC" PYTHONPATH="$SRC" \
    "$VENV_PY" -m pytest -q \
      tests/test_operations_center.py \
      tests/test_dev_assistant.py \
      tests/test_ai_recovery_strategies.py \
      tests/test_auto_update_contract.py
)
rm -rf "$TEST_DATA"

backup_configuration

echo "Nieuwe applicatie voorbereiden..."
rm -rf "$NEXT_APP"
cp -a "$SRC/app" "$NEXT_APP"
chown -R "$SERVICE_USER:$SERVICE_USER" "$NEXT_APP"
"$VENV_PY" -m compileall -q "$NEXT_APP"

for name in "${ROOT_FILES[@]}"; do
  cp "$SRC/$name" "$APP_ROOT/$name"
done
chmod 755 \
  "$APP_ROOT/update-timer.sh" \
  "$APP_ROOT/update-from-github.sh" \
  "$APP_ROOT/auto-update.sh" \
  "$APP_ROOT/setup-network-share.sh" \
  "$APP_ROOT/setup-top40-ca-bundle.sh"
chown "$SERVICE_USER:$SERVICE_USER" "$APP_ROOT/requirements.txt" "$APP_ROOT/VERSION"
chown root:root \
  "$APP_ROOT/auto-update.sh" \
  "$APP_ROOT/update-from-github.sh" \
  "$APP_ROOT/setup-top40-ca-bundle.sh"

install -m 0755 "$SRC/scripts/top40-safe-action" "$SAFE_ACTION"
install -m 0755 "$SRC/scripts/safe-update.sh" "$SAFE_UPDATER"
for src_unit in "${SOURCE_UNITS[@]}"; do
  install -m 0644 "$src_unit" "/etc/systemd/system/$(basename "$src_unit")"
done
CONFIG_CHANGED=1
systemctl daemon-reload
"$APP_ROOT/setup-top40-ca-bundle.sh"

# De oude periodieke downloader wordt niet meer gebruikt.
systemctl disable --now "$DOWNLOAD_TIMER" 2>/dev/null || true
systemctl stop "$DOWNLOAD_SERVICE" 2>/dev/null || true

# Korte atomische applicatiewissel. AI/logreader worden ook gestopt zodat geen
# proces oude Python-modules vasthoudt tijdens de mapwissel.
echo "Applicatie atomisch omschakelen..."
systemctl stop "$RECOVERY_TIMER" "$AI_SERVICE" "$LOG_SERVICE" "$WEB_SERVICE" 2>/dev/null || true
rm -rf "$BACKUP_APP"
if [ -d "$APP_DIR" ]; then
  mv "$APP_DIR" "$BACKUP_APP"
fi
mv "$NEXT_APP" "$APP_DIR"
SWAPPED=1
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

cd "$APP_ROOT"
runuser -u "$SERVICE_USER" -- env \
  TOP40_DATA_DIR="$DATA_DIR" \
  PYTHONPATH="$APP_ROOT" \
  "$VENV_PY" -m app.cli init

# AI-memory vooraf als dezelfde gebruiker initialiseren als de AI-service.
runuser -u "$SERVICE_USER" -- env \
  TOP40_DATA_DIR="$DATA_DIR" \
  PYTHONPATH="$APP_ROOT" \
  "$VENV_PY" -c 'from app.ai_memory import connect; c=connect(); c.__enter__(); c.__exit__(None,None,None)'

systemctl reset-failed "$WEB_SERVICE" "$LOG_SERVICE" "$AI_SERVICE" "$DOWNLOAD_SERVICE" 2>/dev/null || true
systemctl enable "$WEB_SERVICE" "$LOG_SERVICE" "$AI_SERVICE" >/dev/null 2>&1
systemctl start "$WEB_SERVICE"
wait_for_url "webinterface 8040" "http://127.0.0.1:8040/health" 30 1

systemctl start "$LOG_SERVICE"
wait_for_url "veilige logreader 8042" "http://127.0.0.1:8042/healthz" 20 1

systemctl start "$AI_SERVICE"
wait_for_url "AI-platform 8041" "http://127.0.0.1:8041/healthz" 30 2

# Niet alleen de poort testen: verifieer dat werkelijk 1.16.0 en beide nieuwe
# onderdelen geladen zijn en productie-writes uit staan.
AI_HEALTH=$(curl -fsS http://127.0.0.1:8041/healthz)
printf '%s' "$AI_HEALTH" | "$VENV_PY" -c '
import json,sys
x=json.load(sys.stdin)
assert x.get("ok") is True
assert x.get("version") == "1.16.0"
assert x.get("operations_center") is True
assert x.get("recovery_dashboard") is True
assert x.get("development_assistant") is True
assert x.get("production_write") is False
'

curl -fsS http://127.0.0.1:8041/api/development/workspaces >/dev/null
curl -fsS http://127.0.0.1:8041/ai-actions >/dev/null
curl -fsS http://127.0.0.1:8041/api/ai/recovery >/dev/null

# De herstelservice moet op een machine die rechtstreeks van 1.15.2 komt ook
# zelfstandig kunnen draaien. Eén echte cyclus is daarom onderdeel van de update.
systemctl enable "$RECOVERY_TIMER" >/dev/null 2>&1
systemctl start "$RECOVERY_SERVICE"
systemctl enable --now "$RECOVERY_TIMER"

[ -f "$AI_DIR/last-recovery-report.json" ] || {
  echo "FOUT: AI-herstelcyclus schreef geen herstelrapport."
  exit 1
}
"$VENV_PY" - "$AI_DIR/last-recovery-report.json" <<'PY'
import json,sys
with open(sys.argv[1], encoding='utf-8') as f:
    report=json.load(f)
assert report.get('ok') is True
assert 'decision' in report
assert 'actions' in report
PY

# Download- en onderhoudsservices pas na geslaagde 8040/8041/8042-validatie
# definitief inschakelen.
systemctl disable --now "$DOWNLOAD_TIMER" 2>/dev/null || true
systemctl enable --now \
  "$DOWNLOAD_SERVICE" \
  top40-archiver-history.timer \
  top40-archiver-check.timer \
  top40-archiver-auto-update.timer \
  "$LOG_SERVICE" \
  "$AI_SERVICE" \
  "$RECOVERY_TIMER"
systemctl restart "$DOWNLOAD_SERVICE"
systemctl restart top40-archiver-history.timer 2>/dev/null || true
systemctl restart top40-archiver-check.timer 2>/dev/null || true
systemctl start --no-block top40-archiver-history.service 2>/dev/null || true

# Finale controle nadat alle services tegelijk actief zijn.
wait_for_url "webinterface finale controle" "http://127.0.0.1:8040/health" 15 1
wait_for_url "AI-platform finale controle" "http://127.0.0.1:8041/healthz" 15 1
wait_for_url "logreader finale controle" "http://127.0.0.1:8042/healthz" 15 1
systemctl is-active --quiet "$DOWNLOAD_SERVICE"
systemctl is-active --quiet "$AI_SERVICE"
systemctl is-active --quiet "$LOG_SERVICE"
systemctl is-active --quiet "$RECOVERY_TIMER"

SOURCE_SHA="${TOP40_SOURCE_SHA:-}"
if [ -z "$SOURCE_SHA" ] && command -v git >/dev/null 2>&1 && [ -d "$SRC/.git" ]; then
  SOURCE_SHA=$(git -C "$SRC" rev-parse HEAD 2>/dev/null || true)
fi
if [[ "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  printf '%s\n' "$SOURCE_SHA" > "$STATE_DIR/installed_commit_sha"
fi
if [[ "${TOP40_ARCHIVE_SHA256:-}" =~ ^[0-9a-f]{64}$ ]]; then
  printf '%s\n' "$TOP40_ARCHIVE_SHA256" > "$STATE_DIR/last_archive_sha256"
fi
printf '%s\n' "$(date -Is)" > "$STATE_DIR/last_success"
printf '%s\n' "$VERSION" > "$STATE_DIR/installed_version"
printf '%s\n' "$BACKUP_DIR" > "$STATE_DIR/last_backup"

chown -R root:root "$STATE_DIR"
chmod 755 "$STATE_DIR"
chmod 644 "$STATE_DIR"/* 2>/dev/null || true

# Vanaf hier zijn code, services, healthchecks én update-status bevestigd.
SWAPPED=0
UPDATE_COMPLETE=1

echo "Top40Archiver $VERSION is volledig bijgewerkt."
echo "8040 webinterface: gezond"
echo "8041 AI-platform: gezond"
echo "8042 veilige logreader: gezond"
echo "AI-herstelcyclus: actief via $RECOVERY_TIMER"
echo "Development Assistant: beschikbaar, productie-writes uit"
echo "Veilige updater: $SAFE_UPDATER"
echo "Rollbackbackup: $BACKUP_DIR"
echo "Na de herstart controleert de auto-updater na twee minuten en daarna iedere 24 uur."

if ! schedule_reboot; then
  echo "De NUC moet handmatig opnieuw worden gestart om de update volledig af te ronden."
fi
