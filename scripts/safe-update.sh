#!/usr/bin/env bash
set -Eeuo pipefail

APP="/opt/top40-archiver"
REMOTE="${TOP40_UPDATE_REMOTE:-origin}"
BRANCH="${TOP40_UPDATE_BRANCH:-main}"
DB="/var/lib/top40-archiver/top40.sqlite3"
BACKUP_ROOT="/var/lib/top40-archiver/backups"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="$BACKUP_ROOT/update_${STAMP}"
LOCK="/run/lock/top40-archiver-update.lock"

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "FOUT: er draait al een Top40Archiver-update."
  exit 20
fi

cd "$APP"

if [ ! -d .git ]; then
  echo "FOUT: $APP is geen Git-repository; update afgebroken."
  exit 21
fi

if ! git diff --quiet || ! git diff --cached --quiet || [ -n "$(git ls-files --others --exclude-standard)" ]; then
  echo "FOUT: lokale wijzigingen gevonden; update afgebroken."
  git status --short
  exit 22
fi

CURRENT_SHA="$(git rev-parse HEAD)"
CURRENT_BRANCH="$(git branch --show-current)"

mkdir -p "$BACKUP"
cp -a VERSION "$BACKUP/VERSION" 2>/dev/null || true
cp -a "$DB" "$BACKUP/top40.sqlite3" 2>/dev/null || true
systemctl cat top40-archiver-web.service > "$BACKUP/web.service" 2>/dev/null || true
systemctl cat top40-archiver-ai.service > "$BACKUP/ai.service" 2>/dev/null || true
printf '%s\n' "$CURRENT_SHA" > "$BACKUP/previous-sha"
printf '%s\n' "$CURRENT_BRANCH" > "$BACKUP/previous-branch"

echo "=== Remote ophalen ==="
git fetch --prune "$REMOTE" "+refs/heads/$BRANCH:refs/remotes/$REMOTE/$BRANCH"
TARGET_SHA="$(git rev-parse "$REMOTE/$BRANCH")"

if [ "$CURRENT_SHA" = "$TARGET_SHA" ]; then
  echo "Geen update nodig: $CURRENT_SHA"
  exit 0
fi

WORKTREE="$(mktemp -d /tmp/top40-update.XXXXXX)"
cleanup() {
  git worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true
  rm -rf "$WORKTREE" >/dev/null 2>&1 || true
}
trap cleanup EXIT

git worktree add --detach "$WORKTREE" "$TARGET_SHA"

required=(
  app/main.py app/db.py app/service.py app/templates/index.html
  app/static/style.css app/static/live.js VERSION
)
for file in "${required[@]}"; do
  [ -f "$WORKTREE/$file" ] || { echo "FOUT: vereist bestand ontbreekt: $file"; exit 23; }
done

PYTHONDONTWRITEBYTECODE=1 "$APP/venv/bin/python" -m py_compile \
  "$WORKTREE/app/main.py" \
  "$WORKTREE/app/db.py" \
  "$WORKTREE/app/service.py"

if [ -f "$WORKTREE/app/ai_sidecar.py" ]; then
  PYTHONDONTWRITEBYTECODE=1 "$APP/venv/bin/python" -m py_compile \
    "$WORKTREE/app/health_engine.py" \
    "$WORKTREE/app/health_trends.py" \
    "$WORKTREE/app/prediction_engine.py" \
    "$WORKTREE/app/ai_sidecar.py"
fi

NEW_VERSION="$(tr -d '[:space:]' < "$WORKTREE/VERSION")"
[ -n "$NEW_VERSION" ] || { echo "FOUT: lege VERSION in doelcommit"; exit 24; }

echo "=== Services stoppen ==="
systemctl stop top40-archiver-ai.service 2>/dev/null || true
systemctl stop top40-archiver-web.service

rollback() {
  echo "FOUT: update mislukt; rollback naar $CURRENT_SHA"
  git reset --hard "$CURRENT_SHA"
  systemctl daemon-reload || true
  systemctl start top40-archiver-web.service || true
  systemctl start top40-archiver-ai.service 2>/dev/null || true
}
trap rollback ERR

git reset --hard "$TARGET_SHA"

if [ -f scripts/install-1.15.1.sh ]; then
  bash scripts/install-1.15.1.sh --from-updater
fi

systemctl daemon-reload
systemctl start top40-archiver-web.service
systemctl start top40-archiver-ai.service 2>/dev/null || true
sleep 4
curl -fsS http://127.0.0.1:8040/ >/dev/null
if systemctl is-enabled --quiet top40-archiver-ai.service 2>/dev/null; then
  curl -fsS http://127.0.0.1:8041/healthz >/dev/null
fi

trap - ERR
printf '%s\n' "$TARGET_SHA" > "$BACKUP/installed-sha"
echo "KLAAR: $CURRENT_SHA -> $TARGET_SHA (versie $NEW_VERSION)"
echo "Backup: $BACKUP"
