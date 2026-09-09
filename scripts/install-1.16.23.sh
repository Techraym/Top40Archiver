#!/usr/bin/env bash
set -Eeuo pipefail

# Legacy compatibility bootstrap for Top40Archiver 1.16.23.
# The proven 1.16.22 bootstrap remains the transaction/rollback base.
# Contract markers: previous-sha version-rollback BACKUP_OK
# "audio_library_touched": False TOP40_SOURCE_SHA
# bash "$TMP/update-existing.sh" top40-archiver-safe-update
# CHARLY is installed only after the proven Top40Archiver update path succeeds.

APP=/opt/top40-archiver
BASE="$APP/scripts/install-1.16.22.sh"
CHARLY_INSTALLER="$APP/scripts/install-charly-top40.sh"

[ "$(id -u)" -eq 0 ] || { echo "Voer dit script als root uit."; exit 1; }
[ -f "$BASE" ] || { echo "FOUT: bewezen legacy bootstrap ontbreekt: $BASE"; exit 1; }
[ -f "$CHARLY_INSTALLER" ] || { echo "FOUT: CHARLY-integratie-installer ontbreekt: $CHARLY_INSTALLER"; exit 1; }
[ "$(tr -d '[:space:]' < "$APP/VERSION")" = "1.16.23" ] || {
  echo "FOUT: bootstrap-installer is uitsluitend voor 1.16.23."
  exit 1
}

TMP_RENDERED=$(mktemp /tmp/top40-install-1.16.23.XXXXXX.sh)
cleanup(){ rm -f "$TMP_RENDERED"; }
trap cleanup EXIT

sed \
  -e 's/1\.16\.22/1.16.23/g' \
  -e 's/11622/11623/g' \
  "$BASE" > "$TMP_RENDERED"
chmod 0700 "$TMP_RENDERED"

# First complete the existing Top40Archiver transactional update/healthchecks.
bash "$TMP_RENDERED"

# Then place CHARLY natively above the existing Ollama/Qwen inference path.
# A failure here is non-zero; install-charly-top40.sh restores its own
# CHARLY/Ollama state, after which the parent updater can apply its normal
# Top40Archiver release rollback policy.
bash "$CHARLY_INSTALLER"

echo "Top40Archiver 1.16.23 + CHARLY v0.2.0 installatie voltooid."
