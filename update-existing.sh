#!/bin/bash
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Voer dit script als root uit."; exit 1; }
SRC=$(cd "$(dirname "$0")" && pwd)
[ -d /opt/top40-archiver ] || { echo "/opt/top40-archiver bestaat niet."; exit 1; }

systemctl stop top40-archiver-web.service 2>/dev/null || true
cp -a /opt/top40-archiver/app "/opt/top40-archiver/app.backup_$(date +%Y%m%d_%H%M%S)"
rm -rf /opt/top40-archiver/app
cp -a "$SRC/app" /opt/top40-archiver/app
cp "$SRC/requirements.txt" "$SRC/VERSION" \
  "$SRC/update-timer.sh" "$SRC/update-from-github.sh" \
  "$SRC/auto-update.sh" "$SRC/setup-network-share.sh" \
  "$SRC/setup-top40-ca-bundle.sh" \
  /opt/top40-archiver/

apt-get update
apt-get install -y ffmpeg ca-certificates curl unzip util-linux openssl
update-ca-certificates
/opt/top40-archiver/venv/bin/pip install --upgrade -r /opt/top40-archiver/requirements.txt

chmod 755 \
  /opt/top40-archiver/update-timer.sh \
  /opt/top40-archiver/update-from-github.sh \
  /opt/top40-archiver/auto-update.sh \
  /opt/top40-archiver/setup-network-share.sh \
  /opt/top40-archiver/setup-top40-ca-bundle.sh

/opt/top40-archiver/setup-top40-ca-bundle.sh

if ! command -v deno >/dev/null 2>&1; then
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

mkdir -p /var/lib/top40-archiver/download-temp /var/lib/top40-archiver/update-state
chown -R top40archiver:top40archiver \
  /opt/top40-archiver/app \
  /opt/top40-archiver/requirements.txt \
  /var/lib/top40-archiver
chown root:root \
  /opt/top40-archiver/auto-update.sh \
  /opt/top40-archiver/update-from-github.sh \
  /opt/top40-archiver/setup-top40-ca-bundle.sh
chown -R root:root /var/lib/top40-archiver/update-state
chmod 755 /var/lib/top40-archiver/update-state

cp "$SRC"/systemd/*.service "$SRC"/systemd/*.timer /etc/systemd/system/
cd /opt/top40-archiver
runuser -u top40archiver -- env TOP40_DATA_DIR=/var/lib/top40-archiver PYTHONPATH=/opt/top40-archiver /opt/top40-archiver/venv/bin/python -m app.cli init
systemctl daemon-reload
systemctl enable --now \
  top40-archiver-web.service \
  top40-archiver-history.timer \
  top40-archiver-auto-update.timer
systemctl restart top40-archiver-check.timer 2>/dev/null || true

SOURCE_SHA="${TOP40_SOURCE_SHA:-}"
if [ -z "$SOURCE_SHA" ] && command -v git >/dev/null 2>&1 && [ -d "$SRC/.git" ]; then
  SOURCE_SHA=$(git -C "$SRC" rev-parse HEAD 2>/dev/null || true)
fi
if [[ "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  printf '%s\n' "$SOURCE_SHA" > /var/lib/top40-archiver/update-state/installed_commit_sha
fi
if [[ "${TOP40_ARCHIVE_SHA256:-}" =~ ^[0-9a-f]{64}$ ]]; then
  printf '%s\n' "$TOP40_ARCHIVE_SHA256" > /var/lib/top40-archiver/update-state/last_archive_sha256
fi
printf '%s\n' "$(date -Is)" > /var/lib/top40-archiver/update-state/last_success

chown -R root:root /var/lib/top40-archiver/update-state
chmod 755 /var/lib/top40-archiver/update-state
chmod 644 /var/lib/top40-archiver/update-state/* 2>/dev/null || true

echo "Update naar Top 40 Archiver 1.8.6 gereed."
echo "Automatische GitHub-updatecontrole is actief bij opstarten en iedere 24 uur."
echo "Top40.nl TLS-keten is via een gecontroleerde Sectigo-bundle hersteld."
echo "De actuele en historische Top40.nl-lijststructuur wordt ondersteund."
echo "Genre- en artiestmappen volgen dezelfde regels als GenreSplitter."
echo "De downloadwachtrij gebruikt standaard twee parallelle workers."
echo "De systeemcontrole toont nauwkeurig schijfgebruik en werkelijke MP3-statistieken."
echo "Spotify instellen: nano /etc/top40-archiver.env"
echo "Daarna: systemctl restart top40-archiver-web.service"
echo "Windows-netwerkschijf instellen: /opt/top40-archiver/setup-network-share.sh"
