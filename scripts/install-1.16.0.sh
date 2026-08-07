#!/usr/bin/env bash
set -Eeuo pipefail

# Bootstrap voor oudere top40-archiver-safe-update versies. Die zoeken een
# versie-installer onder scripts/install-<VERSION>.sh nadat zij de doelcommit
# al in /opt/top40-archiver hebben uitgecheckt.
APP=/opt/top40-archiver

[ "$(id -u)" -eq 0 ] || { echo "Voer dit script als root uit."; exit 1; }
cd "$APP"
[ -f VERSION ] || { echo "VERSION ontbreekt."; exit 1; }
[ "$(tr -d '[:space:]' < VERSION)" = "1.16.0" ] || {
  echo "FOUT: bootstrap-installer is uitsluitend voor 1.16.0."
  exit 1
}

TMP=$(mktemp -d /tmp/top40-116-bootstrap.XXXXXX)
cleanup(){ rm -rf "$TMP"; }
trap cleanup EXIT

# Maak een immutable bronkopie van exact de commit die de oude updater zojuist
# heeft uitgecheckt. update-existing.sh kan daardoor atomisch naar APP schrijven
# zonder dat bron en doel dezelfde bestanden zijn.
if command -v git >/dev/null 2>&1 && [ -d .git ]; then
  SHA=$(git rev-parse HEAD)
  git archive "$SHA" | tar -x -C "$TMP"
else
  SHA=""
  cp -a app systemd scripts tests "$TMP/"
  cp -a requirements.txt VERSION update-existing.sh auto-update.sh \
    update-timer.sh update-from-github.sh setup-network-share.sh \
    setup-top40-ca-bundle.sh install-1.16.0.sh "$TMP/"
fi

chmod +x "$TMP/update-existing.sh"
TOP40_SOURCE_SHA="$SHA" bash "$TMP/update-existing.sh"
