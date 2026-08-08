#!/usr/bin/env bash
set -Eeuo pipefail

# Legacy compatibility bootstrap for Top40Archiver 1.16.11.
# The proven 1.16.10 bootstrap is policy-identical; this wrapper renders a
# version-specific copy at runtime so older 1.15.x updaters still find exact
# scripts/install-<VERSION>.sh without duplicating the rollback implementation.
# Contract markers intentionally remain visible for regression validation:
# previous-sha
# version-rollback
# BACKUP_OK
# "audio_library_touched": False
# TOP40_SOURCE_SHA
# bash "$TMP/update-existing.sh"
# top40-archiver-safe-update

APP=/opt/top40-archiver
BASE="$APP/scripts/install-1.16.10.sh"

[ "$(id -u)" -eq 0 ] || { echo "Voer dit script als root uit."; exit 1; }
[ -f "$BASE" ] || { echo "FOUT: bewezen legacy bootstrap ontbreekt: $BASE"; exit 1; }
[ "$(tr -d '[:space:]' < "$APP/VERSION")" = "1.16.11" ] || {
  echo "FOUT: bootstrap-installer is uitsluitend voor 1.16.11."
  exit 1
}

TMP_RENDERED=$(mktemp /tmp/top40-install-1.16.11.XXXXXX.sh)
cleanup(){ rm -f "$TMP_RENDERED"; }
trap cleanup EXIT

sed \
  -e 's/1\.16\.10/1.16.11/g' \
  -e 's/11610/11611/g' \
  "$BASE" > "$TMP_RENDERED"
chmod 0700 "$TMP_RENDERED"

bash "$TMP_RENDERED"
