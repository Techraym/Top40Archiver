#!/usr/bin/env bash
set -Eeuo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Voer rollback uit als root."; exit 2; }

BACKUP_DIR="${1:-}"
WITH_DB="${2:-}"
APP_ROOT="${TOP40_APP_ROOT:-/opt/top40-archiver}"
DATA_DIR="${TOP40_DATA_DIR:-/var/lib/top40-archiver}"

[ -n "$BACKUP_DIR" ] || { echo "Gebruik: $0 /pad/naar/version-backup [--with-database]"; exit 2; }
[ -d "$BACKUP_DIR" ] || { echo "Backupmap bestaat niet: $BACKUP_DIR"; exit 3; }
[ -f "$BACKUP_DIR/BACKUP_OK" ] || { echo "BACKUP_OK ontbreekt; herstel geweigerd."; exit 4; }
[ -f "$BACKUP_DIR/manifest.sha256" ] || { echo "manifest.sha256 ontbreekt; herstel geweigerd."; exit 5; }

(
  cd "$BACKUP_DIR"
  sha256sum -c manifest.sha256
)
[ -f "$BACKUP_DIR/app.tar.gz" ] && tar -tzf "$BACKUP_DIR/app.tar.gz" >/dev/null
[ ! -f "$BACKUP_DIR/top40.sqlite3" ] || [ "$(sqlite3 "$BACKUP_DIR/top40.sqlite3" 'PRAGMA quick_check;' | head -n1)" = "ok" ]
[ ! -f "$BACKUP_DIR/ai_memory.sqlite" ] || [ "$(sqlite3 "$BACKUP_DIR/ai_memory.sqlite" 'PRAGMA quick_check;' | head -n1)" = "ok" ]

TARGET_SHA="$(cat "$BACKUP_DIR/git-sha" 2>/dev/null || echo unknown)"
TARGET_VERSION="$(cat "$BACKUP_DIR/VERSION" 2>/dev/null || echo unknown)"

echo "=== Rollback naar Top40Archiver $TARGET_VERSION ($TARGET_SHA) ==="
echo "Gedownloade audiobestanden worden niet aangeraakt."

# Eerst alle processen stilzetten die applicatiecode of SQLite kunnen gebruiken.
# Hierdoor kan een expliciete DB-rollback nooit concurreren met cover/history/check workers.
systemctl stop \
  top40-ai-recovery.timer \
  top40-archiver-cover-art.timer \
  top40-archiver-id3-cover.timer \
  top40-archiver-history.timer \
  top40-archiver-check.timer \
  top40-archiver-incident-scan.timer \
  top40-archiver-cover-art.service \
  top40-archiver-id3-cover.service \
  top40-archiver-history.service \
  top40-archiver-check.service \
  top40-archiver-incident-scan.service \
  top40-archiver-ai.service \
  top40-log-reader.service \
  top40-archiver-download.service \
  top40-archiver-web.service \
  2>/dev/null || true

if [ "$TARGET_SHA" != "unknown" ] && [ -d "$APP_ROOT/.git" ] && [ -f "$BACKUP_DIR/repository.bundle" ]; then
  git -C "$APP_ROOT" fetch "$BACKUP_DIR/repository.bundle" "$TARGET_SHA" >/dev/null
  git -C "$APP_ROOT" reset --hard "$TARGET_SHA"
fi

if [ -f "$BACKUP_DIR/app.tar.gz" ]; then
  RESTORE_TMP="$(mktemp -d /tmp/top40-version-restore.XXXXXX)"
  trap 'rm -rf "$RESTORE_TMP"' EXIT
  tar -C "$RESTORE_TMP" -xzf "$BACKUP_DIR/app.tar.gz"
  [ -d "$RESTORE_TMP/app" ] || { echo "app ontbreekt in backup."; exit 7; }
  rm -rf "$APP_ROOT/app.rollback-old"
  [ ! -d "$APP_ROOT/app" ] || mv "$APP_ROOT/app" "$APP_ROOT/app.rollback-old"
  mv "$RESTORE_TMP/app" "$APP_ROOT/app"
fi

for item in "$BACKUP_DIR/root"/*; do
  [ -e "$item" ] && cp -a "$item" "$APP_ROOT/$(basename "$item")"
done
for item in "$BACKUP_DIR/systemd"/*; do
  [ -e "$item" ] && cp -a "$item" "/etc/systemd/system/$(basename "$item")"
done
[ -f "$BACKUP_DIR/top40-safe-action" ] && install -m 0755 "$BACKUP_DIR/top40-safe-action" /usr/local/sbin/top40-safe-action
[ -f "$BACKUP_DIR/top40-archiver-safe-update" ] && install -m 0755 "$BACKUP_DIR/top40-archiver-safe-update" /usr/local/sbin/top40-archiver-safe-update
[ -f "$BACKUP_DIR/top40-archiver.env" ] && install -m 0600 "$BACKUP_DIR/top40-archiver.env" /etc/top40-archiver.env

if [ "$WITH_DB" = "--with-database" ]; then
  echo "Database wordt expliciet teruggezet. Nieuwe voortgang sinds de backup kan daarmee verloren gaan."
  [ -f "$BACKUP_DIR/top40.sqlite3" ] && cp -a "$BACKUP_DIR/top40.sqlite3" "$DATA_DIR/top40.sqlite3"
  [ -f "$BACKUP_DIR/ai_memory.sqlite" ] && cp -a "$BACKUP_DIR/ai_memory.sqlite" "$DATA_DIR/ai_memory.sqlite"
else
  echo "Database wordt niet teruggezet; download- en archiefvoortgang blijft behouden."
fi

SERVICE_USER=top40archiver
id "$SERVICE_USER" >/dev/null 2>&1 || SERVICE_USER=top40
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_ROOT/app" 2>/dev/null || true
[ ! -f "$DATA_DIR/top40.sqlite3" ] || chown "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR/top40.sqlite3" 2>/dev/null || true
[ ! -f "$DATA_DIR/ai_memory.sqlite" ] || chown "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR/ai_memory.sqlite" 2>/dev/null || true

systemctl daemon-reload
systemctl reset-failed \
  top40-archiver-web.service \
  top40-archiver-download.service \
  top40-log-reader.service \
  top40-archiver-ai.service \
  2>/dev/null || true
systemctl start \
  top40-archiver-web.service \
  top40-archiver-download.service \
  top40-log-reader.service \
  top40-archiver-ai.service

for timer in \
  top40-ai-recovery.timer \
  top40-archiver-cover-art.timer \
  top40-archiver-id3-cover.timer \
  top40-archiver-history.timer \
  top40-archiver-check.timer \
  top40-archiver-incident-scan.timer; do
  systemctl enable --now "$timer" 2>/dev/null || true
done

curl -fsS http://127.0.0.1:8040/health >/dev/null
curl -fsS http://127.0.0.1:8041/healthz >/dev/null
curl -fsS http://127.0.0.1:8042/healthz >/dev/null

echo "Rollback naar $TARGET_VERSION voltooid. Audio is niet verwijderd of verplaatst."
