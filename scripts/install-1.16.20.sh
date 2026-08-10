#!/usr/bin/env bash
set -Eeuo pipefail

# Legacy compatibility bootstrap for Top40Archiver 1.16.20.
# The proven 1.16.11 bootstrap remains the transaction/rollback base.
# Contract markers: previous-sha version-rollback BACKUP_OK
# "audio_library_touched": False TOP40_SOURCE_SHA
# bash "$TMP/update-existing.sh" top40-archiver-safe-update

APP=/opt/top40-archiver
BASE="$APP/scripts/install-1.16.11.sh"

[ "$(id -u)" -eq 0 ] || { echo "Voer dit script als root uit."; exit 1; }
[ -f "$BASE" ] || { echo "FOUT: bewezen legacy bootstrap ontbreekt: $BASE"; exit 1; }
[ "$(tr -d '[:space:]' < "$APP/VERSION")" = "1.16.20" ] || {
  echo "FOUT: bootstrap-installer is uitsluitend voor 1.16.20."
  exit 1
}

install -d -o top40archiver -g top40archiver -m 0770 /var/lib/top40-archiver/ai
if [ -e /var/lib/top40-archiver/ai/model-runtime.lock ]; then
  chown top40archiver:top40archiver /var/lib/top40-archiver/ai/model-runtime.lock
  chmod 0660 /var/lib/top40-archiver/ai/model-runtime.lock
fi

TMP_RENDERED=$(mktemp /tmp/top40-install-1.16.20.XXXXXX.sh)
cleanup(){ rm -f "$TMP_RENDERED"; }
trap cleanup EXIT

sed \
  -e 's/1\.16\.11/1.16.20/g' \
  -e 's/11611/11620/g' \
  "$BASE" > "$TMP_RENDERED"
chmod 0700 "$TMP_RENDERED"

bash "$TMP_RENDERED"
