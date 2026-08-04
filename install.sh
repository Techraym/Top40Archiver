#!/bin/bash
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Voer dit script als root uit."; exit 1; }
SRC=$(cd "$(dirname "$0")" && pwd)

apt-get update
apt-get install -y python3 python3-venv python3-pip ffmpeg sqlite3 ca-certificates curl unzip util-linux openssl
id top40archiver >/dev/null 2>&1 || useradd --system --home /var/lib/top40-archiver --shell /usr/sbin/nologin top40archiver
mkdir -p \
  /opt/top40-archiver \
  /var/lib/top40-archiver/downloads \
  /var/lib/top40-archiver/download-temp \
  /var/lib/top40-archiver/update-state
rm -rf /opt/top40-archiver/app
cp -a "$SRC/app" "$SRC/requirements.txt" "$SRC/VERSION" \
  "$SRC/update-timer.sh" "$SRC/update-from-github.sh" \
  "$SRC/auto-update.sh" "$SRC/setup-network-share.sh" \
  "$SRC/setup-top40-ca-bundle.sh" \
  /opt/top40-archiver/
python3 -m venv /opt/top40-archiver/venv
/opt/top40-archiver/venv/bin/pip install --upgrade pip wheel
/opt/top40-archiver/venv/bin/pip install -r /opt/top40-archiver/requirements.txt

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
# Maak een app aan via Spotify for Developers en vul beide waarden in.
# Spotify wordt uitsluitend gebruikt om artiest, titel, speelduur en ISRC te controleren.
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
SPOTIFY_MARKET=NL
EOF
  chmod 600 /etc/top40-archiver.env
  chown root:root /etc/top40-archiver.env
fi

chown -R top40archiver:top40archiver /opt/top40-archiver /var/lib/top40-archiver
chown root:root \
  /opt/top40-archiver/auto-update.sh \
  /opt/top40-archiver/update-from-github.sh \
  /opt/top40-archiver/setup-top40-ca-bundle.sh
cp "$SRC"/systemd/*.service "$SRC"/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
cd /opt/top40-archiver
runuser -u top40archiver -- env TOP40_DATA_DIR=/var/lib/top40-archiver PYTHONPATH=/opt/top40-archiver /opt/top40-archiver/venv/bin/python -m app.cli init
/opt/top40-archiver/update-timer.sh

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

systemctl enable --now \
  top40-archiver-web.service \
  top40-archiver-history.timer \
  top40-archiver-auto-update.timer
printf 'Top 40 Archiver 1.8.4 is klaar. Open: http://%s:8040\n' "$(hostname -I | awk '{print $1}')"
echo "Automatische updates: bij opstarten en iedere 24 uur, met commit-SHA- en SHA-256-controle."
echo "Top40.nl TLS-keten: gecontroleerde Sectigo-bundle geïnstalleerd."
echo "De actuele en historische Top40.nl-lijststructuur wordt ondersteund."
echo "Genre- en artiestmappen volgen dezelfde regels als GenreSplitter."
echo "Spotify instellen: nano /etc/top40-archiver.env && systemctl restart top40-archiver-web.service"
echo "Windows-netwerkschijf instellen: /opt/top40-archiver/setup-network-share.sh"
