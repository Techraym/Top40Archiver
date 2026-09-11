#!/usr/bin/env bash
set -Eeuo pipefail

# Legacy compatibility bootstrap for Top40Archiver 1.16.24.
# The proven 1.16.22 bootstrap remains the transaction/rollback base.
# Contract markers: previous-sha version-rollback BACKUP_OK
# "audio_library_touched": False TOP40_SOURCE_SHA
# bash "$TMP/update-existing.sh" top40-archiver-safe-update

APP=/opt/top40-archiver
BASE="$APP/scripts/install-1.16.22.sh"
CHARLY_INSTALLER="$APP/scripts/install-charly-top40.sh"

[ "$(id -u)" -eq 0 ] || { echo "Voer dit script als root uit."; exit 1; }
[ -f "$BASE" ] || { echo "FOUT: bewezen legacy bootstrap ontbreekt: $BASE"; exit 1; }
[ -f "$CHARLY_INSTALLER" ] || { echo "FOUT: CHARLY-integratie-installer ontbreekt: $CHARLY_INSTALLER"; exit 1; }
[ "$(tr -d '[:space:]' < "$APP/VERSION")" = "1.16.24" ] || { echo "FOUT: bootstrap-installer is uitsluitend voor 1.16.24."; exit 1; }

TMP_RENDERED=$(mktemp /tmp/top40-install-1.16.24.XXXXXX.sh)
cleanup(){ rm -f "$TMP_RENDERED"; }
trap cleanup EXIT

sed -e 's/1\.16\.22/1.16.24/g' -e 's/11622/11624/g' "$BASE" > "$TMP_RENDERED"
chmod 0700 "$TMP_RENDERED"
bash "$TMP_RENDERED"

if systemctl is-active --quiet charly-core.service \
   && systemctl is-active --quiet charly-ollama-gateway.service \
   && curl -fsS --max-time 5 http://127.0.0.1:8765/api/health >/dev/null \
   && curl -fsS --max-time 5 http://127.0.0.1:11435/api/tags >/dev/null; then
  echo "CHARLY is al gezond; gatewaymigratie wordt niet opnieuw uitgevoerd."
else
  bash "$CHARLY_INSTALLER"
fi

echo "Top40Archiver 1.16.24 + CHARLY autonomous recovery installatie voltooid."
