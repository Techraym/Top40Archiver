#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
APP_ROOT=/opt/top40-archiver
DATA_DIR=/var/lib/top40-archiver
STATE_DIR="$DATA_DIR/update-state"
PATCH="$ROOT/scripts/patch-library-quality-cover-performance-v6.py"
VENV_PY="$APP_ROOT/venv/bin/python"
SERVICE=top40-library-quality.service
SCAN_SERVICE=top40-library-quality-scan.service
PATCH_VERSION=1.16.23.5-library-quality-8085
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="$DATA_DIR/backups/library-quality/$STAMP-hotfix-1.16.23.5"

[ "$(id -u)" -eq 0 ] || { echo 'FOUT: voer uit met sudo/root.'; exit 1; }
[ -x "$VENV_PY" ] || { echo "FOUT: virtualenv ontbreekt: $VENV_PY"; exit 1; }
[ -f "$PATCH" ] || { echo "FOUT: patch ontbreekt: $PATCH"; exit 1; }
[ -f "$APP_ROOT/app/library_quality.py" ] || { echo 'FOUT: Library Quality is niet geïnstalleerd.'; exit 1; }

if systemctl is-active --quiet "$SCAN_SERVICE"; then
  echo 'FOUT: er draait nu een Library Quality scan. Wacht tot deze klaar is.'
  exit 1
fi
if curl -fsS --max-time 3 http://127.0.0.1:8085/api/scan/status 2>/dev/null \
  | "$VENV_PY" -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin).get("running") else 1)' 2>/dev/null; then
  echo 'FOUT: er draait nu een webgestarte Library Quality scan. Stop/wacht eerst.'
  exit 1
fi

SERVICE_USER=top40archiver
id "$SERVICE_USER" >/dev/null 2>&1 || SERVICE_USER=top40
id "$SERVICE_USER" >/dev/null 2>&1 || { echo 'FOUT: servicegebruiker ontbreekt.'; exit 1; }

mkdir -p "$BACKUP/app" "$STATE_DIR"
cp -a "$APP_ROOT/app/library_quality.py" "$BACKUP/app/library_quality.py"
cp -a "$APP_ROOT/app/library_quality_app.py" "$BACKUP/app/library_quality_app.py"
printf '%s\n' "$(tr -d '[:space:]' < "$STATE_DIR/library_quality_version" 2>/dev/null || true)" > "$BACKUP/previous-library-quality-version"

echo "Backup: $BACKUP"

rollback(){
  rc=$?
  trap - ERR
  echo "FOUT: 1.16.23.5 update afgebroken (code $rc). Rollback uitvoeren..."
  cp -a "$BACKUP/app/library_quality.py" "$APP_ROOT/app/library_quality.py"
  cp -a "$BACKUP/app/library_quality_app.py" "$APP_ROOT/app/library_quality_app.py"
  systemctl restart "$SERVICE" || true
  exit "$rc"
}
trap rollback ERR

"$VENV_PY" "$PATCH"
chown "$SERVICE_USER:$SERVICE_USER" "$APP_ROOT/app/library_quality.py" "$APP_ROOT/app/library_quality_app.py"
"$VENV_PY" -m py_compile "$APP_ROOT/app/library_quality.py" "$APP_ROOT/app/library_quality_app.py"

runuser -u "$SERVICE_USER" -- env \
  TOP40_DATA_DIR="$DATA_DIR" \
  TOP40_APP_DIR="$APP_ROOT" \
  PYTHONPATH="$APP_ROOT" \
  "$VENV_PY" - <<'PY'
import inspect
import subprocess
import time
import app.library_quality as q
assert q.COVER_VERSION == 6
assert q.COVER_TRACK_BUDGET <= 12.0
assert q.COVER_LOOKUP_TIMEOUT <= 7.0
assert q.TOP40_BACKFILL_TIMEOUT <= 6.0
source = inspect.getsource(q._lookup_cover_bounded)
assert 'subprocess.run' in source and 'timeout=timeout' in source
source2 = inspect.getsource(q._top40_backfill_cover)
assert 'TOP40_BACKFILL_MAX_EDITIONS' in source2 and 'subprocess.run' in source2

# Offline contracttest: TimeoutExpired moet onmiddellijk als gewone "geen match"
# terugkomen en mag de worker niet beschadigen.
old_run = q.subprocess.run
old_lookup = q.lookup_cover
q.lookup_cover = lambda a, t: {}
def fake_run(*args, **kwargs):
    raise subprocess.TimeoutExpired(cmd='cover-helper', timeout=0.1)
q.subprocess.run = fake_run
q._COVER_LOOKUP_CACHE.clear()
started = time.monotonic()
assert q._lookup_cover_bounded('Performance Test', 'Timeout', time.monotonic() + 1.0) == {}
assert time.monotonic() - started < 1.0
q.subprocess.run = old_run
q.lookup_cover = old_lookup
print('Cover performance timeout contract: OK')
PY

systemctl restart "$SERVICE"
for i in $(seq 1 20); do
  curl -fsS --max-time 3 http://127.0.0.1:8085/healthz >/tmp/top40-lq-health-1.16.23.5.json 2>/dev/null && break
  sleep 1
done
curl -fsS http://127.0.0.1:8085/healthz | "$VENV_PY" -c '
import json,sys
x=json.load(sys.stdin)
assert x["ok"] is True
assert x["version"]=="1.16.23.5"
assert float(x["cover_track_budget"])<=12.0
assert float(x["cover_lookup_timeout"])<=7.0
assert float(x["top40_backfill_timeout"])<=6.0
'
curl -fsS http://127.0.0.1:8085/api/summary | "$VENV_PY" -c 'import json,sys; x=json.load(sys.stdin); assert x["versions"]["cover"]==6'
curl -fsS http://127.0.0.1:8085/api/scan/status >/dev/null

printf '%s\n' "$PATCH_VERSION" > "$STATE_DIR/library_quality_version"
printf '%s\n' "$(date -Is)" > "$STATE_DIR/library_quality_installed_at"
printf '%s\n' "$BACKUP" > "$STATE_DIR/library_quality_backup"
chmod 0644 "$STATE_DIR/library_quality_"* 2>/dev/null || true
trap - ERR

echo
echo '=== Library Quality 1.16.23.5 geïnstalleerd ==='
echo 'Totale online coverbudget : 12s per track'
echo 'MusicBrainz/CAA timeout   : max 7s, hard afbreekbaar proces'
echo 'Top40.nl backfill timeout : max 6s, hard afbreekbaar proces'
echo 'Top40-edities per track   : max 1 per poging'
echo 'Dode cover-URL cache      : actief binnen scanrun'
echo 'Resolver-resultaatcache   : actief binnen scanrun'
echo 'Cover analyzer-versie     : 6'
echo '8085 health               : actief'
echo "Backup                    : $BACKUP"
echo 'Er is GEEN scan automatisch gestart.'
