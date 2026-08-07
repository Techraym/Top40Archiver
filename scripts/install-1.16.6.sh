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
LEGACY_AI_DROPIN=/etc/systemd/system/top40-archiver-ai.service.d/operations-center.conf
DROPIN_BACKUP=""
DROPIN_REMOVED=0

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
command -v runuser >/dev/null

TARGET_SHA=$(git rev-parse HEAD)
TMP=$(mktemp -d /tmp/top40-1166-bootstrap.XXXXXX)
DROPIN_BACKUP="$TMP/operations-center.conf"

cleanup(){ rm -rf "$TMP"; }
restore_legacy_dropin_on_error() {
  local rc=$?
  if [ "$DROPIN_REMOVED" -eq 1 ] && [ -f "$DROPIN_BACKUP" ]; then
    echo "Mislukte migratie: legacy AI drop-in wordt teruggezet."
    mkdir -p "$(dirname "$LEGACY_AI_DROPIN")"
    cp -a "$DROPIN_BACKUP" "$LEGACY_AI_DROPIN"
    systemctl daemon-reload || true
  fi
  exit "$rc"
}
trap cleanup EXIT
trap restore_legacy_dropin_on_error ERR

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
  mkdir -p "$out/root" "$out/systemd" "$out/systemd-dropins" "$extract"
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
  if [ -f "$LEGACY_AI_DROPIN" ]; then
    cp -a "$LEGACY_AI_DROPIN" "$out/systemd-dropins/operations-center.conf"
  fi
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
    "legacy_ai_dropin_backed_up": True,
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

repair_ai_memory_permissions() {
  local service_user=top40archiver path
  id "$service_user" >/dev/null 2>&1 || service_user=top40

  echo "AI-memory rechten controleren voor gebruiker: $service_user"
  mkdir -p "$DATA_DIR"
  chown "$service_user:$service_user" "$DATA_DIR"
  chmod 0750 "$DATA_DIR"

  for path in \
    "$DATA_DIR/ai_memory.sqlite" \
    "$DATA_DIR/ai_memory.sqlite-wal" \
    "$DATA_DIR/ai_memory.sqlite-shm"; do
    if [ -e "$path" ]; then
      chown "$service_user:$service_user" "$path"
      chmod 0660 "$path"
    fi
  done

  # Test exact het SQLite-writepad dat tijdens de vorige migratie faalde,
  # zonder blijvende schemawijziging. BEGIN IMMEDIATE vereist een schrijf-lock.
  runuser -u "$service_user" -- env TOP40_DATA_DIR="$DATA_DIR" \
    "$APP/venv/bin/python" - "$DATA_DIR/ai_memory.sqlite" <<'PY'
import sqlite3, sys
path = sys.argv[1]
conn = sqlite3.connect(path, timeout=10)
try:
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("CREATE TABLE IF NOT EXISTS __top40_permission_probe(id INTEGER)")
    conn.rollback()
finally:
    conn.close()
print("AI-memory schrijfrechten: OK")
PY

  # SQLite kan tijdens de probe WAL/SHM-bestanden hebben aangemaakt.
  for path in \
    "$DATA_DIR/ai_memory.sqlite" \
    "$DATA_DIR/ai_memory.sqlite-wal" \
    "$DATA_DIR/ai_memory.sqlite-shm"; do
    if [ -e "$path" ]; then
      chown "$service_user:$service_user" "$path"
      chmod 0660 "$path"
    fi
  done
}

make_previous_version_backup

# Immutable bronkopie van exact de doelcommit. update-existing.sh mag daardoor
# /opt/top40-archiver atomisch wijzigen zonder zijn eigen bronbestanden kwijt te raken.
git archive "$TARGET_SHA" | tar -x -C "$TMP"
chmod +x "$TMP/update-existing.sh"

# Voorkom een live app-swap met een onvolledige module-set. Dit vangt precies de
# gemengde-modulefout af die op 2026-08-07 op de NUC zichtbaar werd.
for required in \
  app/__init__.py \
  app/cli.py \
  app/chart_freshness.py \
  app/ai_platform.py \
  app/ai_session_console.py \
  app/service_queue.py; do
  [ -f "$TMP/$required" ] || {
    echo "FOUT: verplichte 1.16.6 module ontbreekt vóór live-swap: $required"
    exit 1
  }
done

# Repareer een bestaande 1.15.x AI-memorydatabase voordat de live applicatie
# wordt omgeschakeld. Op de NUC was deze database reeds vóór de upgrade soms
# read-only voor de 8041-service en blokkeerde daardoor de 1.16.6 migratie.
repair_ai_memory_permissions

# 1.15.5 installeerde een drop-in die ExecStart terugbuigt naar
# app.ai_operations_app:app. Die overschrijft in 1.16.6 de nieuwe hoofd-unit
# app.ai_platform:app en laat daardoor de nieuwe healthcontracten falen.
# Backup + verwijder hem transactioneel; de ERR-trap zet hem terug als de
# migratie ergens daarna faalt.
if [ -f "$LEGACY_AI_DROPIN" ]; then
  cp -a "$LEGACY_AI_DROPIN" "$DROPIN_BACKUP"
  rm -f "$LEGACY_AI_DROPIN"
  rmdir "$(dirname "$LEGACY_AI_DROPIN")" 2>/dev/null || true
  DROPIN_REMOVED=1
  systemctl daemon-reload
  echo "Legacy AI operations-center drop-in verwijderd voor 1.16.6 migratie."
fi

# Zorg dat geen downloadworker Python-modules uit de app-map kan laden terwijl
# de transactionele updater de applicatiemap wisselt.
systemctl stop top40-archiver-download.service 2>/dev/null || true

TOP40_SOURCE_SHA="$TARGET_SHA" bash "$TMP/update-existing.sh"

# De legacy updater waarmee we binnenkwamen blijft anders na deze succesvolle
# migratie op zijn oude implementatie staan. Vervang hem pas ná alle healthchecks.
install -m 0755 "$TMP/scripts/safe-update.sh" /usr/local/sbin/top40-archiver-safe-update
install -m 0755 "$TMP/scripts/create-version-backup.sh" /usr/local/sbin/top40-version-backup
install -m 0755 "$TMP/scripts/restore-version-backup.sh" /usr/local/sbin/top40-version-rollback

trap - ERR
DROPIN_REMOVED=0

echo "$EXPECTED_VERSION legacy bootstrap voltooid; toekomstige updates gebruiken de transactionele updater."
