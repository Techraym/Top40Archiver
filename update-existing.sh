#!/bin/bash
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Voer dit script als root uit."; exit 1; }

SRC=$(cd "$(dirname "$0")" && pwd)
APP_ROOT=/opt/top40-archiver
APP_DIR="$APP_ROOT/app"
NEXT_APP="$APP_ROOT/app.next"
STATE_DIR=/var/lib/top40-archiver/update-state
WEB_SERVICE=top40-archiver-web.service
VERSION=$(tr -d '[:space:]' < "$SRC/VERSION" 2>/dev/null || echo unknown)
STAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_APP="$APP_ROOT/app.backup_$STAMP"
SWAPPED=0

[ -d "$APP_ROOT" ] || { echo "$APP_ROOT bestaat niet."; exit 1; }
[ -d "$SRC/app" ] || { echo "Bronmap $SRC/app ontbreekt."; exit 1; }

recover_web() {
  systemctl reset-failed "$WEB_SERVICE" 2>/dev/null || true
  systemctl start --no-block "$WEB_SERVICE" 2>/dev/null || true
}

rollback_app() {
  if [ "$SWAPPED" -eq 1 ] && [ -d "$BACKUP_APP" ]; then
    echo "Update terugdraaien naar vorige applicatie..."
    systemctl stop "$WEB_SERVICE" 2>/dev/null || true
    rm -rf "$APP_DIR"
    mv "$BACKUP_APP" "$APP_DIR"
    chown -R top40archiver:top40archiver "$APP_DIR"
    recover_web
  fi
}

on_exit() {
  rc=$?
  trap - EXIT
  if [ "$rc" -ne 0 ]; then
    echo "FOUT: update is afgebroken met code $rc."
    rollback_app
    recover_web
  fi
  rm -rf "$NEXT_APP"
  exit "$rc"
}
trap on_exit EXIT

mkdir -p /var/lib/top40-archiver/download-temp "$STATE_DIR"
chmod 755 "$STATE_DIR"

# Alle trage voorbereidende stappen gebeuren terwijl de bestaande webinterface
# gewoon blijft draaien. Alleen de uiteindelijke mapwissel veroorzaakt korte downtime.
echo "Systeempakketten controleren terwijl dashboard actief blijft..."
apt-get update
apt-get install -y ffmpeg ca-certificates curl unzip util-linux openssl
update-ca-certificates

echo "Python-pakketten controleren terwijl dashboard actief blijft..."
"$APP_ROOT/venv/bin/pip" install --upgrade -r "$SRC/requirements.txt"

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

rm -rf "$NEXT_APP"
cp -a "$SRC/app" "$NEXT_APP"
chown -R top40archiver:top40archiver "$NEXT_APP"

echo "Nieuwe Python-code controleren..."
"$APP_ROOT/venv/bin/python" -m py_compile "$NEXT_APP"/*.py

cp "$SRC/requirements.txt" "$SRC/VERSION" \
  "$SRC/update-timer.sh" "$SRC/update-from-github.sh" \
  "$SRC/auto-update.sh" "$SRC/setup-network-share.sh" \
  "$SRC/setup-top40-ca-bundle.sh" \
  "$APP_ROOT/"

chmod 755 \
  "$APP_ROOT/update-timer.sh" \
  "$APP_ROOT/update-from-github.sh" \
  "$APP_ROOT/auto-update.sh" \
  "$APP_ROOT/setup-network-share.sh" \
  "$APP_ROOT/setup-top40-ca-bundle.sh"

chown top40archiver:top40archiver "$APP_ROOT/requirements.txt" "$APP_ROOT/VERSION"
chown root:root \
  "$APP_ROOT/auto-update.sh" \
  "$APP_ROOT/update-from-github.sh" \
  "$APP_ROOT/setup-top40-ca-bundle.sh"

"$APP_ROOT/setup-top40-ca-bundle.sh"

cp "$SRC"/systemd/*.service "$SRC"/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload

# Korte, atomische applicatiewissel.
echo "Applicatie kort omschakelen..."
systemctl stop "$WEB_SERVICE" 2>/dev/null || true
rm -rf "$BACKUP_APP"
if [ -d "$APP_DIR" ]; then
  mv "$APP_DIR" "$BACKUP_APP"
fi
mv "$NEXT_APP" "$APP_DIR"
SWAPPED=1
chown -R top40archiver:top40archiver "$APP_DIR"

cd "$APP_ROOT"
runuser -u top40archiver -- env \
  TOP40_DATA_DIR=/var/lib/top40-archiver \
  PYTHONPATH="$APP_ROOT" \
  "$APP_ROOT/venv/bin/python" -m app.cli init

systemctl reset-failed "$WEB_SERVICE" 2>/dev/null || true
systemctl enable "$WEB_SERVICE" >/dev/null 2>&1 || true
systemctl start --no-block "$WEB_SERVICE"

# Wacht hoogstens 30 seconden op een echte healthcheck. Bij mislukking volgt rollback.
echo "Webinterface controleren..."
HEALTH_OK=0
for _ in $(seq 1 30); do
  if curl --fail --silent --max-time 2 http://127.0.0.1:8040/health >/dev/null 2>&1; then
    HEALTH_OK=1
    break
  fi
  sleep 1
done

if [ "$HEALTH_OK" -ne 1 ]; then
  echo "FOUT: webinterface werd niet gezond binnen 30 seconden."
  journalctl -u "$WEB_SERVICE" -n 80 --no-pager -l || true
  exit 1
fi

# De nieuwe versie draait; de oude app blijft als terugvalbackup bewaard.
SWAPPED=0

systemctl enable --now \
  top40-archiver-download.timer \
  top40-archiver-history.timer \
  top40-archiver-auto-update.timer
systemctl restart top40-archiver-download.timer 2>/dev/null || true
systemctl restart top40-archiver-history.timer 2>/dev/null || true
systemctl restart top40-archiver-check.timer 2>/dev/null || true
systemctl start --no-block top40-archiver-history.service 2>/dev/null || true

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

chown -R root:root "$STATE_DIR"
chmod 755 "$STATE_DIR"
chmod 644 "$STATE_DIR"/* 2>/dev/null || true

echo "Update naar Top 40 Archiver $VERSION gereed."
echo "Dashboard-healthcheck is geslaagd."
echo "De permanente downloadtimer is actief en verwerkt maximaal twintig tracks per ronde."
echo "De historie verwerkt Top 40 en Tipparade doorlopend tot de actuele week."
echo "De webinterface was alleen tijdens de korte applicatiewissel offline."
