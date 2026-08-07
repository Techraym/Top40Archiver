#!/usr/bin/env bash
set -Eeuo pipefail

# Bootstrap voor de legacy Top40Archiver 1.15.x safe-updater.
# Die updater doet eerst `git reset --hard <target>` en zoekt daarna exact
# scripts/install-<VERSION>.sh. Daarom reconstrueren we vóór de 1.16-installatie
# een rollbackpakket van de vorige commit/configuratie uit de legacy updaterbackup.

APP=/opt/top40-archiver
DATA_DIR=/var/lib/top40-archiver
BACKUP_ROOT="$DATA_DIR/backups/version-rollback"
EXPECTED_VERSION=1.16.6

[ "$(id -u)" -eq 0 ] || { echo "Voer dit script als root uit."; exit 1; }
cd "$APP"
[ -d .git ] || { echo "FOUT: $APP is geen Git-repository."; exit 1; }
[ -f VERSION ] || { echo "FOUT: VERSION ontbreekt."; exit 1; }
[ "$(tr -d '[:space:]' < VERSION)" = "$EXPECTED_VERSION" ] || {
  echo "FOUT: bootstrap-installer is uitsluitend voor $EXPECTED_VERSION."
  exit 1
}
command -v git >/dev/null
command -v tar >/dev/null
command -v sha256sum >/dev/null
command -v sqlite3 >/dev/null

TARGET_SHA=$(git rev-parse HEAD)
TMP=$(mktemp -d /tmp/top40-1166-bootstrap.XXXXXX)
cleanup(){ rm -rf "$TMP"; }
trap cleanup EXIT

find_legacy_backup() {
  local item
  for item in $(find "$DATA_DIR/backups" -maxdepth 1 -mindepth 1 -type d -name 'update_*' -printf '%T@ %p\n' 2>/dev/null | sort -nr | awk '{print $2}'); do
    if [ -f "$item/previous-sha" ]; then
      printf '%s\n' "$item"
      return 0
    fi
  done
  return 1
}

make_previous_version_backup() {
  local legacy previous_sha previous_version stamp short out extract
  legacy=$(find_legacy_backup || true)
  [ -n "$legacy" ] || {
    echo "WAARSCHUWING: geen legacy updatebackup met previous-sha gevonden; de normale 1.16-backup blijft actief."
    return 0
  }

  previous_sha=$(tr -d '[:space:]' < "$legacy/previous-sha")
  [[ "$previous_sha" =~ ^[0-9a-f]{40}$ ]] || {
    echo "FOUT: ongeldige previous-sha in $legacy"
    return 1
  }
  git cat-file -e "$previous_sha^{commit}"
  previous_version=$(tr -d '[:space:]' < "$legacy/VERSION" 2>/dev/null || echo legacy)
  stamp=$(date +%Y%m%d_%H%M%S)
  short=${previous_sha:0:12}
  out="$BACKUP_ROOT/${stamp}_${previous_version}_${short}_legacy-bootstrap"
  extract="$TMP/previous"
  mkdir -p "$out/root" "$out/systemd" "$extract"
  chmod 0700 "$out"

  # Code van exact de vorige commit, niet van de reeds uitgecheckte doelrelease.
  git archive "$previous_sha" app | tar -x -C "$extract"
  tar -C "$extract" -czf "$out/app.tar.gz" app
  tar -tzf "$out/app.tar.gz" >/dev/null
  git bundle create "$out/repository.bundle" --all
  git bundle verify "$out/repository.bundle" >/dev/null

  printf '%s\n' "$previous_version" > "$out/VERSION"
  printf '%s\n' "$previous_sha" > "$out/git-sha"
  printf '%s\n' "legacy-bootstrap" > "$out/git-branch"
  printf '%s\n' "$legacy" > "$out/legacy-update-backup"

  for name in VERSION requirements.txt update-existing.sh update-timer.sh update-from-github.sh auto-update.sh setup-network-share.sh setup-top40-ca-bundle.sh; do
    if git cat-file -e "$previous_sha:$name" 2>/dev/null; then
      git show "$previous_sha:$name" > "$out/root/$name"
    fi
  done

  # De systemd-/rootconfiguratie is op dit moment nog de werkelijk draaiende
  # 1.15.x configuratie; de nieuwe installer heeft die nog niet vervangen.
  for unit in /etc/systemd/system/top40*.service /etc/systemd/system/top40*.timer; do
    [ -e "$unit" ] && cp -a "$unit" "$out/systemd/$(basename "$unit")"
  done
  [ -e /usr/local/sbin/top40-safe-action ] && cp -a /usr/local/sbin/top40-safe-action "$out/top40-safe-action"
  [ -e /usr/local/sbin/top40-archiver-safe-update ] && cp -a /usr/local/sbin/top40-archiver-safe-update "$out/top40-archiver-safe-update"
  [ -e /etc/top40-archiver.env ] && cp -a /etc/top40-archiver.env "$out/top40-archiver.env"

  if [ -f "$legacy/top40.sqlite3" ]; then
    cp -a "$legacy/top40.sqlite3" "$out/top40.sqlite3"
  elif [ -f "$DATA_DIR/top40.sqlite3" ]; then
    sqlite3 "$DATA_DIR/top40.sqlite3" ".backup '$out/top40.sqlite3'"
  fi
  if [ -f "$out/top40.sqlite3" ]; then
    [ "$(sqlite3 "$out/top40.sqlite3" 'PRAGMA quick_check;' | head -n1)" = "ok" ]
  fi
  if [ -f "$DATA_DIR/ai_memory.sqlite" ]; then
    sqlite3 "$DATA_DIR/ai_memory.sqlite" ".backup '$out/ai_memory.sqlite'"
    [ "$(sqlite3 "$out/ai_memory.sqlite" 'PRAGMA quick_check;' | head -n1)" = "ok" ]
  fi

  python3 - "$out/metadata.json" "$previous_version" "$previous_sha" "$TARGET_SHA" <<'PY'
import json, os, socket, sys
from datetime import datetime, timezone
path, version, previous_sha, target_sha = sys.argv[1:]
payload = {
    "created_at": datetime.now(timezone.utc).isoformat(),
    "version": version,
    "git_sha": previous_sha,
    "target_sha": target_sha,
    "hostname": socket.gethostname(),
    "purpose": "Legacy 1.15.x to 1.16.6 verified rollback",
    "database_restore_default": False,
    "audio_library_touched": False,
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2)
os.chmod(path, 0o600)
PY

  (
    cd "$out"
    find . -type f ! -name manifest.sha256 ! -name BACKUP_OK ! -name BACKUP_FAILED -print0 \
      | sort -z | xargs -0 sha256sum > manifest.sha256
    sha256sum -c manifest.sha256 >/dev/null
  )
  printf 'verified_at=%s\nversion=%s\ngit_sha=%s\nlegacy_bootstrap=true\n' \
    "$(date -Is)" "$previous_version" "$previous_sha" > "$out/BACKUP_OK"
  chmod 0600 "$out/BACKUP_OK" "$out/manifest.sha256"
  echo "Legacy rollback-backup: $out"
}

make_previous_version_backup

# Immutable bronkopie van exact de doelcommit. update-existing.sh mag daardoor
# /opt/top40-archiver atomisch wijzigen zonder zijn eigen bronbestanden kwijt te raken.
git archive "$TARGET_SHA" | tar -x -C "$TMP"
chmod +x "$TMP/update-existing.sh"

TOP40_SOURCE_SHA="$TARGET_SHA" bash "$TMP/update-existing.sh"

# De legacy updater waarmee we binnenkwamen blijft anders na deze succesvolle
# migratie op zijn oude implementatie staan. Vervang hem pas ná alle healthchecks.
install -m 0755 "$TMP/scripts/safe-update.sh" /usr/local/sbin/top40-archiver-safe-update
install -m 0755 "$TMP/scripts/create-version-backup.sh" /usr/local/sbin/top40-version-backup
install -m 0755 "$TMP/scripts/restore-version-backup.sh" /usr/local/sbin/top40-version-rollback

echo "$EXPECTED_VERSION legacy bootstrap voltooid; toekomstige updates gebruiken de transactionele updater."
