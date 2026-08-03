#!/bin/bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Voer dit script als root uit: su -"
  exit 1
fi

REPO="Techraym/Top40Archiver"
BRANCH="main"
STATE_DIR="/var/lib/top40-archiver/update-state"
TMP_DIR=$(mktemp -d /tmp/top40-archiver-update.XXXXXX)
trap 'rm -rf "$TMP_DIR"' EXIT

command -v curl >/dev/null 2>&1 || { apt-get update; apt-get install -y curl; }
command -v unzip >/dev/null 2>&1 || { apt-get update; apt-get install -y unzip; }
command -v sha256sum >/dev/null 2>&1 || { apt-get update; apt-get install -y coreutils; }

mkdir -p "$STATE_DIR"
chmod 755 "$STATE_DIR"

echo "Actuele commit-SHA van GitHub ophalen..."
REMOTE_SHA=$(
  curl --fail --silent --show-error --location --retry 3 \
    --connect-timeout 15 --max-time 60 \
    -H 'Accept: application/vnd.github+json' \
    -H 'User-Agent: Top40Archiver-ManualUpdater' \
    "https://api.github.com/repos/${REPO}/commits/${BRANCH}" |
  python3 -c 'import json, sys; print(json.load(sys.stdin)["sha"])'
)

if [[ ! "$REMOTE_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "FOUT: ongeldige GitHub commit-SHA: $REMOTE_SHA"
  exit 1
fi

echo "GitHub commit: $REMOTE_SHA"
ARCHIVE="$TMP_DIR/source-${REMOTE_SHA}.zip"

echo "Vastgepinde broncode downloaden..."
curl --fail --location --retry 3 \
  --connect-timeout 15 --max-time 600 \
  "https://github.com/${REPO}/archive/${REMOTE_SHA}.zip" \
  --output "$ARCHIVE"

ARCHIVE_SHA256=$(sha256sum "$ARCHIVE" | awk '{print $1}')
if [[ ! "$ARCHIVE_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
  echo "FOUT: geen geldige SHA-256 voor het updatearchief."
  exit 1
fi

echo "Archief SHA-256: $ARCHIVE_SHA256"
unzip -q "$ARCHIVE" -d "$TMP_DIR"
SOURCE_DIR=$(find "$TMP_DIR" -mindepth 1 -maxdepth 1 -type d -name 'Top40Archiver-*' | head -n 1)

if [ -z "$SOURCE_DIR" ] || [ ! -f "$SOURCE_DIR/update-existing.sh" ]; then
  echo "FOUT: update-existing.sh ontbreekt in de GitHub-download."
  exit 1
fi

chmod +x \
  "$SOURCE_DIR/update-existing.sh" \
  "$SOURCE_DIR/setup-network-share.sh" \
  "$SOURCE_DIR/update-from-github.sh" \
  "$SOURCE_DIR/auto-update.sh" \
  "$SOURCE_DIR/update-timer.sh"

TOP40_SOURCE_SHA="$REMOTE_SHA" \
TOP40_ARCHIVE_SHA256="$ARCHIVE_SHA256" \
  "$SOURCE_DIR/update-existing.sh"

APPLIED_SHA=$(tr -d '[:space:]' < "$STATE_DIR/installed_commit_sha" 2>/dev/null || true)
if [ "$APPLIED_SHA" != "$REMOTE_SHA" ]; then
  echo "FOUT: geïnstalleerde SHA ($APPLIED_SHA) wijkt af van de verwachte SHA ($REMOTE_SHA)."
  exit 1
fi

echo
echo "Update vanaf GitHub voltooid en gecontroleerd."
echo "Geïnstalleerde commit-SHA: $APPLIED_SHA"
echo "Dashboard: http://$(hostname -I | awk '{print $1}'):8040"
echo "Samba eenmalig instellen: /opt/top40-archiver/setup-network-share.sh"
