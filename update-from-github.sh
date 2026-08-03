#!/bin/bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Voer dit script als root uit: su -"
  exit 1
fi

REPO="Techraym/Top40Archiver"
BRANCH="main"
TMP_DIR=$(mktemp -d /tmp/top40-archiver-update.XXXXXX)
ARCHIVE="$TMP_DIR/source.zip"
trap 'rm -rf "$TMP_DIR"' EXIT

command -v curl >/dev/null 2>&1 || { apt-get update; apt-get install -y curl; }
command -v unzip >/dev/null 2>&1 || { apt-get update; apt-get install -y unzip; }

echo "Top40Archiver downloaden van GitHub..."
curl --fail --location --retry 3 \
  "https://github.com/${REPO}/archive/refs/heads/${BRANCH}.zip" \
  --output "$ARCHIVE"

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
  "$SOURCE_DIR/update-timer.sh"

"$SOURCE_DIR/update-existing.sh"

echo
echo "Update vanaf GitHub voltooid."
echo "Dashboard: http://$(hostname -I | awk '{print $1}'):8040"
echo "Samba eenmalig instellen: /opt/top40-archiver/setup-network-share.sh"
