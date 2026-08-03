#!/bin/bash
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Voer dit script als root uit."; exit 1; }
SRC=$(cd "$(dirname "$0")" && pwd)
[ -d /opt/top40-archiver ] || { echo "/opt/top40-archiver bestaat niet."; exit 1; }

systemctl stop top40-archiver-web.service 2>/dev/null || true
cp -a /opt/top40-archiver/app "/opt/top40-archiver/app.backup_$(date +%Y%m%d_%H%M%S)"
rm -rf /opt/top40-archiver/app
cp -a "$SRC/app" /opt/top40-archiver/app
cp "$SRC/requirements.txt" "$SRC/VERSION" "$SRC/update-timer.sh" "$SRC/update-from-github.sh" "$SRC/setup-network-share.sh" /opt/top40-archiver/

apt-get update
apt-get install -y ffmpeg ca-certificates curl unzip
update-ca-certificates
/opt/top40-archiver/venv/bin/pip install --upgrade -r /opt/top40-archiver/requirements.txt

if ! command -v deno >/dev/null 2>&1; then
  DENO_INSTALL=/opt/deno curl -fsSL https://deno.land/install.sh | sh
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

mkdir -p /var/lib/top40-archiver/download-temp
chmod 755 /opt/top40-archiver/update-timer.sh /opt/top40-archiver/update-from-github.sh /opt/top40-archiver/setup-network-share.sh
chown -R top40archiver:top40archiver /opt/top40-archiver/app /opt/top40-archiver/requirements.txt /var/lib/top40-archiver
cp "$SRC"/systemd/*.service "$SRC"/systemd/*.timer /etc/systemd/system/
cd /opt/top40-archiver
runuser -u top40archiver -- env TOP40_DATA_DIR=/var/lib/top40-archiver PYTHONPATH=/opt/top40-archiver /opt/top40-archiver/venv/bin/python -m app.cli init
systemctl daemon-reload
systemctl enable --now top40-archiver-web.service top40-archiver-history.timer
systemctl restart top40-archiver-check.timer 2>/dev/null || true

echo "Update naar Top 40 Archiver 1.7 gereed."
echo "Spotify instellen: nano /etc/top40-archiver.env"
echo "Daarna: systemctl restart top40-archiver-web.service"
echo "Windows-netwerkschijf instellen: /opt/top40-archiver/setup-network-share.sh"
