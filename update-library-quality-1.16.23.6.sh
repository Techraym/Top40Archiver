#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
APP_ROOT=/opt/top40-archiver
DATA_DIR=/var/lib/top40-archiver
STATE_DIR="$DATA_DIR/update-state"
PATCH="$ROOT/scripts/patch-library-quality-interrupt-cleanup-v7.py"
VENV_PY="$APP_ROOT/venv/bin/python"
SERVICE=top40-library-quality.service
SCAN_SERVICE=top40-library-quality-scan.service
PATCH_VERSION=1.16.23.6-library-quality-8085
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="$DATA_DIR/backups/library-quality/$STAMP-hotfix-1.16.23.6"

[ "$(id -u)" -eq 0 ] || { echo 'FOUT: voer uit met sudo/root.'; exit 1; }
[ -x "$VENV_PY" ] || { echo "FOUT: virtualenv ontbreekt: $VENV_PY"; exit 1; }
[ -f "$PATCH" ] || { echo "FOUT: patch ontbreekt: $PATCH"; exit 1; }
[ -f "$APP_ROOT/app/library_quality.py" ] || { echo 'FOUT: Library Quality is niet geïnstalleerd.'; exit 1; }

if systemctl is-active --quiet "$SCAN_SERVICE"; then
  echo 'FOUT: er draait nu een Library Quality scan. Wacht/stop deze eerst.'
  exit 1
fi
if curl -fsS --max-time 3 http://127.0.0.1:8085/api/scan/status 2>/dev/null \
  | "$VENV_PY" -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin).get("running") else 1)' 2>/dev/null; then
  echo 'FOUT: er draait nu een webgestarte Library Quality scan. Wacht/stop deze eerst.'
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
  echo "FOUT: 1.16.23.6 update afgebroken (code $rc). Rollback uitvoeren..."
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
import app.library_quality as q
assert q.COVER_VERSION == 6
assert callable(q._mark_run_interrupted)
assert callable(q._interrupt_signal_handler)
scan_source = inspect.getsource(q.scan_library)
main_source = inspect.getsource(q.main)
assert 'except KeyboardInterrupt' in scan_source
assert '_mark_run_interrupted' in scan_source
assert 'signal.SIGTERM' in main_source
assert 'status veilig opgeslagen' in main_source
print('Ctrl+C/SIGTERM interrupt-cleanup contract: OK')
PY

systemctl restart "$SERVICE"
for i in $(seq 1 20); do
  curl -fsS --max-time 3 http://127.0.0.1:8085/healthz >/tmp/top40-lq-health-1.16.23.6.json 2>/dev/null && break
  sleep 1
done
curl -fsS http://127.0.0.1:8085/healthz | "$VENV_PY" -c '
import json,sys
x=json.load(sys.stdin)
assert x["ok"] is True
assert x["version"]=="1.16.23.6"
assert float(x["cover_track_budget"])<=12.0
'
curl -fsS http://127.0.0.1:8085/api/summary | "$VENV_PY" -c 'import json,sys; x=json.load(sys.stdin); assert x["versions"]["cover"]==6'
curl -fsS http://127.0.0.1:8085/api/scan/status >/dev/null

printf '%s\n' "$PATCH_VERSION" > "$STATE_DIR/library_quality_version"
printf '%s\n' "$(date -Is)" > "$STATE_DIR/library_quality_installed_at"
printf '%s\n' "$BACKUP" > "$STATE_DIR/library_quality_backup"
chmod 0644 "$STATE_DIR/library_quality_"* 2>/dev/null || true
trap - ERR

echo
echo '=== Library Quality 1.16.23.6 geïnstalleerd ==='
echo 'Ctrl+C                   : run wordt automatisch interrupted'
echo 'SIGTERM/systemd stop     : run wordt automatisch interrupted'
echo 'State running            : automatisch false bij onderbreken'
echo 'Run-tabel                : status + tellers worden veilig opgeslagen'
echo 'Cover analyzer-versie    : 6 (ongewijzigd)'
echo 'Cover performancebudget  : 12s (ongewijzigd)'
echo '8085 health              : actief'
echo "Backup                   : $BACKUP"
echo 'Er is GEEN scan automatisch gestart.'
