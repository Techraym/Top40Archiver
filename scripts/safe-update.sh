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
[ -d .git ] || { echo "FOUT: $APP is geen Git-repository; update afgebroken."; exit 21; }
if ! git diff --quiet || ! git diff --cached --quiet || [ -n "$(git ls-files --others --exclude-standard)" ]; then
  echo "FOUT: lokale wijzigingen gevonden; update afgebroken."
  git status --short
  exit 22
fi

CURRENT_SHA="$(git rev-parse HEAD)"
CURRENT_BRANCH="$(git branch --show-current)"
mkdir -p "$BACKUP"
cp -a VERSION "$BACKUP/VERSION" 2>/dev/null || true
if [ -f "$DB" ] && command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "$DB" ".backup '$BACKUP/top40.sqlite3'" || true
else
  cp -a "$DB" "$BACKUP/top40.sqlite3" 2>/dev/null || true
fi
systemctl cat top40-archiver-web.service > "$BACKUP/web.service" 2>/dev/null || true
systemctl cat top40-archiver-ai.service > "$BACKUP/ai.service" 2>/dev/null || true
printf '%s\n' "$CURRENT_SHA" > "$BACKUP/previous-sha"
printf '%s\n' "$CURRENT_BRANCH" > "$BACKUP/previous-branch"

echo "=== Remote ophalen ==="
git fetch --prune "$REMOTE" "+refs/heads/$BRANCH:refs/remotes/$REMOTE/$BRANCH"
TARGET_SHA="$(git rev-parse "$REMOTE/$BRANCH")"
[ "$CURRENT_SHA" != "$TARGET_SHA" ] || { echo "Geen update nodig: $CURRENT_SHA"; exit 0; }

WORKTREE="$(mktemp -d /tmp/top40-update.XXXXXX)"
cleanup() {
  git worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true
  rm -rf "$WORKTREE" >/dev/null 2>&1 || true
}
trap cleanup EXIT
git worktree add --detach "$WORKTREE" "$TARGET_SHA"

required=(
  app/main.py
  app/db.py
  app/service.py
  app/templates/index.html
  app/static/style.css
  app/static/live.js
  VERSION
  update-existing.sh
  scripts/safe-update.sh
  systemd/top40-archiver-web.service
)
for file in "${required[@]}"; do
  [ -f "$WORKTREE/$file" ] || { echo "FOUT: vereist bestand ontbreekt: $file"; exit 23; }
done

NEW_VERSION="$(tr -d '[:space:]' < "$WORKTREE/VERSION")"
[[ "$NEW_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?$ ]] || {
  echo "FOUT: ongeldige VERSION in doelcommit: $NEW_VERSION"; exit 24;
}

echo "=== Doelcommit vooraf controleren ==="
bash -n "$WORKTREE/update-existing.sh" "$WORKTREE/scripts/safe-update.sh"
PYTHONDONTWRITEBYTECODE=1 "$APP/venv/bin/python" -m compileall -q "$WORKTREE/app"

rollback() {
  local rc=$?
  echo "FOUT: update naar $TARGET_SHA is mislukt; git-checkout blijft/gaat terug naar $CURRENT_SHA"
  cd "$APP"
  git reset --hard "$CURRENT_SHA" >/dev/null 2>&1 || true
  systemctl daemon-reload || true
  systemctl start top40-archiver-web.service 2>/dev/null || true
  systemctl start top40-log-reader.service 2>/dev/null || true
  systemctl start top40-archiver-ai.service 2>/dev/null || true
  systemctl start top40-archiver-download.service 2>/dev/null || true
  exit "$rc"
}
trap rollback ERR

# De doelcommit wordt vanuit de geïsoleerde worktree geïnstalleerd. De live git-
# checkout blijft op de oude commit totdat alle applicatie-, systemd- en AI-
# healthchecks in update-existing.sh zijn geslaagd.
echo "=== Transactionele installatie $NEW_VERSION ==="
TOP40_SOURCE_SHA="$TARGET_SHA" \
  bash "$WORKTREE/update-existing.sh"

# Pas na een volledig geslaagde installatie de live checkout administratief op
# dezelfde commit zetten. De geïnstalleerde bestanden zijn dan al gevalideerd.
cd "$APP"
git reset --hard "$TARGET_SHA"

# Nog één externe controle nadat checkout en geïnstalleerde versie gelijklopen.
curl -fsS http://127.0.0.1:8040/health >/dev/null
if [ -f "$APP/app/ai_platform.py" ]; then
  RESPONSE="$(curl -fsS http://127.0.0.1:8041/healthz)"
  printf '%s' "$RESPONSE" | "$APP/venv/bin/python" - "$NEW_VERSION" <<'PY'
import json,sys
expected=sys.argv[1]
data=json.load(sys.stdin)
assert data.get('ok') is True
assert data.get('version') == expected
PY
fi

trap - ERR
printf '%s\n' "$TARGET_SHA" > "$BACKUP/installed-sha"
printf '%s\n' "$NEW_VERSION" > "$BACKUP/installed-version"
echo "KLAAR: $CURRENT_SHA -> $TARGET_SHA (versie $NEW_VERSION)"
echo "Backup: $BACKUP"
