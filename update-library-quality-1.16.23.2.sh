#!/usr/bin/env bash
set -Eeuo pipefail
shopt -s nullglob

ROOT="$(cd "$(dirname "$0")" && pwd)"
EXPECTED_SHA256="6bcdfc0c49df6e4647aec3c44bc39282fd97aa1f8c11d66a40590f22dc091916"
PARTS=("$ROOT"/releases/library-quality-1.16.23.2.chunk-*)

[ "$(id -u)" -eq 0 ] || { echo "Voer deze update uit met sudo/root."; exit 1; }

if [ "${#PARTS[@]}" -ne 9 ]; then
  echo "FOUT: verwacht 9 Library Quality hotfix-chunks, gevonden ${#PARTS[@]}."
  exit 1
fi

if systemctl is-active --quiet top40-library-quality-scan.service; then
  echo "FOUT: Library Quality scan is momenteel actief. Wacht tot deze klaar is."
  exit 1
fi

TMP="$(mktemp -d /tmp/top40-library-quality-1.16.23.2.XXXXXX)"
cleanup(){ rm -rf "$TMP"; }
trap cleanup EXIT

ARCHIVE="$TMP/top40-library-quality-8085-1.16.23.2.tar.gz"
cat "${PARTS[@]}" | base64 --decode > "$ARCHIVE"

ACTUAL_SHA256="$(sha256sum "$ARCHIVE" | awk '{print $1}')"
if [ "$ACTUAL_SHA256" != "$EXPECTED_SHA256" ]; then
  echo "FOUT: SHA-256 van Library Quality hotfix klopt niet."
  echo "Verwacht: $EXPECTED_SHA256"
  echo "Gevonden: $ACTUAL_SHA256"
  exit 1
fi

tar -tzf "$ARCHIVE" >/dev/null
tar -xzf "$ARCHIVE" -C "$TMP"
PKG="$TMP/top40-library-quality-8085-1.16.23.2"
[ -f "$PKG/apply.sh" ] || { echo "FOUT: apply.sh ontbreekt in de hotfix."; exit 1; }

echo "Library Quality hotfix gecontroleerd: $ACTUAL_SHA256"
exec bash "$PKG/apply.sh"
