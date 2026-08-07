#!/usr/bin/env bash
set -Eeuo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Voer version-backup uit als root."; exit 2; }

APP_ROOT="${TOP40_APP_ROOT:-/opt/top40-archiver}"
DATA_DIR="${TOP40_DATA_DIR:-/var/lib/top40-archiver}"
BACKUP_ROOT="$DATA_DIR/backups/version-rollback"
STAMP="$(date +%Y%m%d_%H%M%S)"
CURRENT_VERSION="$(tr -d '[:space:]' < "$APP_ROOT/VERSION" 2>/dev/null || echo unknown)"
CURRENT_SHA="$(git -C "$APP_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
SHORT_SHA="${CURRENT_SHA:0:12}"
BACKUP_DIR="$BACKUP_ROOT/${STAMP}_${CURRENT_VERSION}_${SHORT_SHA}"
STATUS_FILE="$BACKUP_DIR/BACKUP_OK"

mkdir -p "$BACKUP_DIR/root" "$BACKUP_DIR/systemd"
chmod 0700 "$BACKUP_DIR"

fail() {
  local rc=$?
  printf 'FAILED %s rc=%s\n' "$(date -Is)" "$rc" > "$BACKUP_DIR/BACKUP_FAILED" 2>/dev/null || true
  echo "FOUT: versie-backup niet volledig; update mag niet doorgaan: $BACKUP_DIR" >&2
  exit "$rc"
}
trap fail ERR

printf '%s\n' "$CURRENT_VERSION" > "$BACKUP_DIR/VERSION"
printf '%s\n' "$CURRENT_SHA" > "$BACKUP_DIR/git-sha"
printf '%s\n' "$(git -C "$APP_ROOT" branch --show-current 2>/dev/null || true)" > "$BACKUP_DIR/git-branch"

# Volledige applicatiecode als lokale noodkopie. De downloadbibliotheek staat buiten
# deze map en wordt uitdrukkelijk niet aangeraakt.
tar -C "$APP_ROOT" -czf "$BACKUP_DIR/app.tar.gz" app
tar -tzf "$BACKUP_DIR/app.tar.gz" >/dev/null

# Git-bundle maakt terugrollen naar de exacte broncommit ook zonder GitHub mogelijk.
if [ -d "$APP_ROOT/.git" ] && [ "$CURRENT_SHA" != "unknown" ]; then
  git -C "$APP_ROOT" bundle create "$BACKUP_DIR/repository.bundle" HEAD
  git -C "$APP_ROOT" bundle verify "$BACKUP_DIR/repository.bundle" >/dev/null
fi

for name in VERSION requirements.txt update-existing.sh update-timer.sh update-from-github.sh auto-update.sh setup-network-share.sh setup-top40-ca-bundle.sh; do
  [ -e "$APP_ROOT/$name" ] && cp -a "$APP_ROOT/$name" "$BACKUP_DIR/root/$name"
done

for unit in /etc/systemd/system/top40*.service /etc/systemd/system/top40*.timer; do
  [ -e "$unit" ] && cp -a "$unit" "$BACKUP_DIR/systemd/$(basename "$unit")"
done
[ -e /usr/local/sbin/top40-safe-action ] && cp -a /usr/local/sbin/top40-safe-action "$BACKUP_DIR/top40-safe-action"
[ -e /usr/local/sbin/top40-archiver-safe-update ] && cp -a /usr/local/sbin/top40-archiver-safe-update "$BACKUP_DIR/top40-archiver-safe-update"
[ -e /etc/top40-archiver.env ] && cp -a /etc/top40-archiver.env "$BACKUP_DIR/top40-archiver.env"

if [ -f "$DATA_DIR/top40.sqlite3" ]; then
  sqlite3 "$DATA_DIR/top40.sqlite3" ".backup '$BACKUP_DIR/top40.sqlite3'"
  [ "$(sqlite3 "$BACKUP_DIR/top40.sqlite3" 'PRAGMA quick_check;' | head -n1)" = "ok" ]
fi
if [ -f "$DATA_DIR/ai_memory.sqlite" ]; then
  sqlite3 "$DATA_DIR/ai_memory.sqlite" ".backup '$BACKUP_DIR/ai_memory.sqlite'"
  [ "$(sqlite3 "$BACKUP_DIR/ai_memory.sqlite" 'PRAGMA quick_check;' | head -n1)" = "ok" ]
fi

python3 - "$BACKUP_DIR/metadata.json" "$CURRENT_VERSION" "$CURRENT_SHA" <<'PY'
import json, os, platform, socket, sys
from datetime import datetime, timezone
path, version, sha = sys.argv[1:]
payload = {
    "created_at": datetime.now(timezone.utc).isoformat(),
    "version": version,
    "git_sha": sha,
    "hostname": socket.gethostname(),
    "platform": platform.platform(),
    "purpose": "Top40Archiver verified version rollback",
    "database_restore_default": False,
    "audio_library_touched": False,
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
os.chmod(path, 0o600)
PY

(
  cd "$BACKUP_DIR"
  find . -type f ! -name manifest.sha256 ! -name BACKUP_OK ! -name BACKUP_FAILED -print0 \
    | sort -z \
    | xargs -0 sha256sum > manifest.sha256
  sha256sum -c manifest.sha256 >/dev/null
)

printf 'verified_at=%s\nversion=%s\ngit_sha=%s\n' "$(date -Is)" "$CURRENT_VERSION" "$CURRENT_SHA" > "$STATUS_FILE"
chmod 0600 "$STATUS_FILE" "$BACKUP_DIR/manifest.sha256"
trap - ERR

echo "$BACKUP_DIR"
