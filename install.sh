#!/bin/bash
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Voer dit script als root uit."; exit 1; }
SRC=$(cd "$(dirname "$0")" && pwd)

apt-get update
apt-get install -y python3 python3-venv python3-pip ffmpeg sqlite3 ca-certificates curl unzip
id top40archiver >/dev/null 2>&1 || useradd --system --home /var/lib/top40-archiver --shell /usr/sbin/nologin top40archiver
mkdir -p /opt/top40-archiver /var/lib/top40-archiver/downloads /var/lib/top40-archiver/download-temp
rm -rf /opt/top40-archiver/app
cp -a "$SRC/app" "$SRC/requirements.txt" "$SRC/VERSION" "$SRC/update-timer.sh" "$SRC/update-from-github.sh" "$SRC/setup-network-share.sh" /opt/top40-archiver/
python3 -m venv /opt/top40-archiver/venv
/opt/top40-archiver/venv/bin/pip install --upgrade pip wheel
/opt/top40-archiver/venv/bin/pip install -r /opt/top40-archiver/requirements.txt

if ! command -v deno >/dev/null 2>&1; then
  DENO_INSTALL=/opt/deno curl -fsSL https://deno.land/install.sh | sh
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

chmod 755 /opt/top40-archiver/update-timer.sh /opt/top40-archiver/update-from-github.sh /opt/top40-archiver/setup-network-share.sh
chown -R top40archiver:top40archiver /opt/top40-archiver /var/lib/top40-archiver
cp "$SRC"/systemd/*.service "$SRC"/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
cd /opt/top40-archiver
runuser -u top40archiver -- env TOP40_DATA_DIR=/var/lib/top40-archiver PYTHONPATH=/opt/top40-archiver /opt/top40-archiver/venv/bin/python -m app.cli init
/opt/top40-archiver/update-timer.sh
systemctl enable --now top40-archiver-web.service top40-archiver-history.timer
printf 'Top 40 Archiver 1.7 is klaar. Open: http://%s:8040\n' "$(hostname -I | awk '{print $1}')"
echo "Spotify instellen: nano /etc/top40-archiver.env && systemctl restart top40-archiver-web.service"
echo "Windows-netwerkschijf instellen: /opt/top40-archiver/setup-network-share.sh"
