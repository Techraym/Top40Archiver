#!/usr/bin/env bash
set -Eeuo pipefail

APP="/opt/top40-archiver"
DATA_DIR="/var/lib/top40-archiver"
REMOTE="${TOP40_UPDATE_REMOTE:-origin}"
BRANCH="${TOP40_UPDATE_BRANCH:-main}"
DB="$DATA_DIR/top40.sqlite3"
BACKUP_ROOT="$DATA_DIR/backups"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="$BACKUP_ROOT/update_${STAMP}"
LOCK="/run/lock/top40-archiver-update.lock"
AI_LOCAL_PATCH="$BACKUP/ai-local.patch"
AI_MANAGED_DIRTY=0

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "FOUT: er draait al een Top40Archiver-update."
  exit 20
fi

cd "$APP"
[ -d .git ] || { echo "FOUT: $APP is geen Git-repository; update afgebroken."; exit 21; }
mkdir -p "$BACKUP"

is_ai_managed_dirty() {
  [ -z "$(git diff --cached --name-only)" ] || return 1
  [ -z "$(git ls-files --others --exclude-standard)" ] || return 1
  local changed
  changed="$(git diff --name-only)"
  [ -n "$changed" ] || return 1
  TOP40_DIRTY_FILES="$changed" "$APP/venv/bin/python" - <<'PY'
import json, os
from pathlib import Path

root = Path('/var/lib/top40-archiver/ai')
allowed = set()
for name in ('code-repair-state.json', 'code-improvement-state.json'):
    try:
        state = json.loads((root / name).read_text(encoding='utf-8'))
    except Exception:
        continue
    active = state.get('active')
    if isinstance(active, dict):
        allowed.update(str(x) for x in (active.get('files') or []))
changed = {x.strip() for x in os.environ.get('TOP40_DIRTY_FILES', '').splitlines() if x.strip()}
if not changed or not changed.issubset(allowed):
    raise SystemExit(1)
if any(not x.startswith('app/') or not x.endswith('.py') or '..' in Path(x).parts for x in changed):
    raise SystemExit(1)
PY
}

if ! git diff --quiet || ! git diff --cached --quiet || [ -n "$(git ls-files --others --exclude-standard)" ]; then
  if is_ai_managed_dirty; then
    AI_MANAGED_DIRTY=1
    git diff --binary > "$AI_LOCAL_PATCH"
    [ -s "$AI_LOCAL_PATCH" ] || { echo "FOUT: AI-canarypatch kon niet worden vastgelegd."; exit 22; }
    echo "Gevalideerde AI-canarywijzigingen gevonden; officiële update mag deze gecontroleerd vervangen."
    echo "Lokale canarypatch: $AI_LOCAL_PATCH"
  else
    echo "FOUT: lokale wijzigingen gevonden die niet aantoonbaar van een actieve AI-canary zijn; update afgebroken."
    git status --short
    exit 22
  fi
fi

CURRENT_SHA="$(git rev-parse HEAD)"
CURRENT_BRANCH="$(git branch --show-current)"
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
  scripts/create-version-backup.sh
  scripts/restore-version-backup.sh
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
  if [ "$AI_MANAGED_DIRTY" -eq 1 ] && [ -s "$AI_LOCAL_PATCH" ]; then
    if git apply --check "$AI_LOCAL_PATCH" >/dev/null 2>&1; then
      git apply --whitespace=nowarn "$AI_LOCAL_PATCH" || true
      echo "Actieve AI-canary is na mislukte officiële update teruggezet."
    else
      echo "WAARSCHUWING: AI-canarypatch kon niet automatisch opnieuw worden toegepast: $AI_LOCAL_PATCH"
    fi
  fi
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

# De updater die deze update heeft uitgevoerd kan nog de oude versie zijn. Zet
# daarom expliciet de gevalideerde updater uit de nieuwe commit voor de volgende run.
install -m 0755 "$WORKTREE/scripts/safe-update.sh" /usr/local/sbin/top40-archiver-safe-update
install -m 0755 "$WORKTREE/scripts/create-version-backup.sh" /usr/local/sbin/top40-version-backup
install -m 0755 "$WORKTREE/scripts/restore-version-backup.sh" /usr/local/sbin/top40-version-rollback

# Nog één externe controle nadat checkout en geïnstalleerde versie gelijklopen.
curl -fsS http://127.0.0.1:8040/health >/dev/null
if [ -f "$APP/app/ai_platform.py" ]; then
  RESPONSE="$(curl -fsS http://127.0.0.1:8041/healthz)"
  TOP40_AI_HEALTH="$RESPONSE" "$APP/venv/bin/python" - "$NEW_VERSION" <<'PY'
import json,os,sys
expected=sys.argv[1]
data=json.loads(os.environ['TOP40_AI_HEALTH'])
assert data.get('ok') is True
assert data.get('version') == expected
PY
fi

# Een officiële, volledig gezonde release vervangt een eventuele lokale AI-canary.
# Sluit die neutraal af zodat hij geen onterechte succes-/faalscore krijgt en de
# volgende AI-cyclus niet probeert terug te rollen over de nieuwe versie heen.
if [ "$AI_MANAGED_DIRTY" -eq 1 ] && [ -f "$APP/app/ai_update_handoff.py" ]; then
  "$APP/venv/bin/python" -m app.ai_update_handoff "$NEW_VERSION" "$TARGET_SHA" || {
    echo "FOUT: actieve AI-canary kon niet veilig aan de officiële update worden overgedragen."
    false
  }
fi

trap - ERR
printf '%s\n' "$TARGET_SHA" > "$BACKUP/installed-sha"
printf '%s\n' "$NEW_VERSION" > "$BACKUP/installed-version"
echo "KLAAR: $CURRENT_SHA -> $TARGET_SHA (versie $NEW_VERSION)"
echo "Backup: $BACKUP"
