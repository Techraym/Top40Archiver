#!/bin/bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Voer dit script als root uit: su -"
  exit 1
fi

SHARE_PATH="${1:-/mnt/top40-music}"
SHARE_NAME="${2:-Top40Music}"
WINDOWS_USER="${3:-top40}"
SMB_CONF="/etc/samba/smb.conf"
BEGIN_MARKER="# BEGIN TOP40-ARCHIVER-SHARE"
END_MARKER="# END TOP40-ARCHIVER-SHARE"

if ! id top40archiver >/dev/null 2>&1; then
  echo "FOUT: servicegebruiker top40archiver bestaat niet. Installeer de app eerst."
  exit 1
fi

if ! id "$WINDOWS_USER" >/dev/null 2>&1; then
  echo "FOUT: Linux-gebruiker '$WINDOWS_USER' bestaat niet."
  echo "Gebruik bijvoorbeeld: $0 '$SHARE_PATH' '$SHARE_NAME' top40"
  exit 1
fi

mkdir -p "$SHARE_PATH"
MOUNT_TARGET=$(findmnt -n -o TARGET --target "$SHARE_PATH" 2>/dev/null || true)
if [ -z "$MOUNT_TARGET" ] || [ "$MOUNT_TARGET" = "/" ]; then
  echo "FOUT: $SHARE_PATH staat niet op een afzonderlijk gekoppeld opslagmedium."
  echo "De share wordt niet gemaakt, zodat Windows nooit per ongeluk op de interne systeemschijf schrijft."
  echo "Controleer met: findmnt --target '$SHARE_PATH'"
  exit 1
fi

if ! mountpoint -q "$MOUNT_TARGET"; then
  echo "FOUT: het gevonden koppelpunt '$MOUNT_TARGET' is niet actief."
  exit 1
fi

if ! runuser -u top40archiver -- test -w "$SHARE_PATH"; then
  echo "FOUT: top40archiver kan niet schrijven naar $SHARE_PATH."
  echo "Herstel eerst de uid/gid-mountopties van de externe schijf."
  exit 1
fi

apt-get update
apt-get install -y samba

cp -a "$SMB_CONF" "${SMB_CONF}.backup_top40_$(date +%Y%m%d_%H%M%S)"

python3 - "$SMB_CONF" "$BEGIN_MARKER" "$END_MARKER" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
begin = sys.argv[2]
end = sys.argv[3]
text = path.read_text(encoding="utf-8") if path.exists() else ""
start = text.find(begin)
if start >= 0:
    stop = text.find(end, start)
    if stop < 0:
        raise SystemExit("FOUT: beginmarkering gevonden zonder eindmarkering in smb.conf")
    stop += len(end)
    text = text[:start].rstrip() + "\n" + text[stop:].lstrip("\n")
path.write_text(text.rstrip() + "\n", encoding="utf-8")
PY

cat >> "$SMB_CONF" <<EOF_SHARE

$BEGIN_MARKER
[$SHARE_NAME]
   comment = Top 40 Archiver externe muziekopslag
   path = $SHARE_PATH
   browseable = yes
   read only = no
   guest ok = no
   valid users = $WINDOWS_USER
   force user = top40archiver
   force group = top40archiver
   create mask = 0664
   directory mask = 0775
   force create mode = 0660
   force directory mode = 0770
   delete readonly = yes
   hide dot files = yes
   follow symlinks = no
   wide links = no
   root preexec = /usr/bin/mountpoint -q $MOUNT_TARGET
   root preexec close = yes
$END_MARKER
EOF_SHARE

if ! testparm -s "$SMB_CONF" >/tmp/top40-samba-test.txt 2>&1; then
  cat /tmp/top40-samba-test.txt
  echo "FOUT: Samba-configuratie is ongeldig. De back-up staat naast $SMB_CONF."
  exit 1
fi

systemctl enable --now smbd.service
if systemctl list-unit-files nmbd.service >/dev/null 2>&1; then
  systemctl enable --now nmbd.service || true
fi

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
  ufw allow Samba
fi

echo
echo "Stel nu het Samba-wachtwoord in voor Windows-gebruiker '$WINDOWS_USER'."
echo "Dit mag hetzelfde zijn als het Linux-wachtwoord, maar hoeft niet."
smbpasswd -a "$WINDOWS_USER"
smbpasswd -e "$WINDOWS_USER"

systemctl restart smbd.service
systemctl restart nmbd.service 2>/dev/null || true

HOST=$(hostname -s)
IP=$(hostname -I | awk '{print $1}')

echo
echo "Netwerkschijf is ingesteld."
echo "Windows-pad via hostnaam: \\\\$HOST\\$SHARE_NAME"
if [ -n "$IP" ]; then
  echo "Windows-pad via IP:       \\\\$IP\\$SHARE_NAME"
fi
echo "Gebruiker: $WINDOWS_USER"
echo
echo "Belangrijk: de SQLite-database blijft op de interne schijf staan."
echo "MP3-bestanden mogen via Windows worden verwijderd; tracks met status 'downloaded' worden niet opnieuw gedownload."
