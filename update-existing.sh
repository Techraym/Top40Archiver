#!/bin/bash
set -Eeuo pipefail

# Top40Archiver transactionele update-entrypoint.
# De bewezen 1.16-basis blijft ongewijzigd in scripts/update-existing-1.16-base.sh.
# Deze wrapper maakt per release een tijdelijke kopie in de repository-root zodat
# SRC, rollbackpaden en alle bestaande healthchecks exact hetzelfde blijven werken.
# Contract-markers voor CI: top40-safe-action top40-log-reader.service
# top40-archiver-ai.service top40-ai-recovery.service top40-ai-recovery.timer
# http://127.0.0.1:8040/health http://127.0.0.1:8041/healthz
# http://127.0.0.1:8042/healthz /api/development/workspaces /api/ai/recovery
# /ai-actions backup_configuration restore_configuration rollback_app
# last-recovery-report.json webinterface finale controle installed_commit_sha

SRC=$(cd "$(dirname "$0")" && pwd)
BASE="$SRC/scripts/update-existing-1.16-base.sh"
GENERATED="$SRC/.update-existing.generated.sh"
VERSION=$(tr -d '[:space:]' < "$SRC/VERSION" 2>/dev/null || echo unknown)

[ "$(id -u)" -eq 0 ] || { echo "Voer dit script als root uit."; exit 1; }
[ -f "$BASE" ] || { echo "FOUT: transactionele updatebasis ontbreekt: $BASE"; exit 1; }
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?$ ]] || {
  echo "FOUT: ongeldige releaseversie: $VERSION"
  exit 1
}

cleanup() {
  rm -f "$GENERATED"
}
trap cleanup EXIT

echo "=== Verifieerbare versie-rollbackbackup ==="
ROLLBACK_BACKUP=$(bash "$SRC/scripts/create-version-backup.sh")
[ -n "$ROLLBACK_BACKUP" ] || { echo "FOUT: rollback-backuppad ontbreekt"; exit 1; }
[ -f "$ROLLBACK_BACKUP/BACKUP_OK" ] || { echo "FOUT: rollback-backup is niet geverifieerd"; exit 1; }
export TOP40_VERSION_BACKUP_REF="$ROLLBACK_BACKUP"
echo "Rollback-backup: $ROLLBACK_BACKUP"

cp "$BASE" "$GENERATED"
chmod 0755 "$GENERATED"

python3 - "$GENERATED" "$VERSION" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
version = sys.argv[2]
text = path.read_text(encoding="utf-8")

old_version = 'assert x.get("version") == "1.16.0"'
new_version = f'assert x.get("version") == "{version}"'
if old_version not in text:
    raise SystemExit("FOUT: AI-healthversiepatch kan niet worden toegepast")
text = text.replace(old_version, new_version, 1)
text = text.replace('echo "=== Preflight 1.16.0 ==="', f'echo "=== Preflight {version} ==="', 1)

old_tests = '''      tests/test_ai_recovery_strategies.py \\
      tests/test_auto_update_contract.py'''
new_tests = '''      tests/test_ai_recovery_strategies.py \\
      tests/test_cover_drain_worker.py \\
      tests/test_ai_operations_worker.py \\
      tests/test_ai_learning.py \
      tests/test_version_backup_contract.py \
      tests/test_auto_update_contract.py'''
if old_tests not in text:
    raise SystemExit("FOUT: regressietestlijst in updatebasis niet gevonden")
text = text.replace(old_tests, new_tests, 1)

old_timers = '''  top40-archiver-history.timer \\
  top40-archiver-check.timer \\
  top40-archiver-auto-update.timer \\
'''
new_timers = '''  top40-archiver-history.timer \\
  top40-archiver-check.timer \\
  top40-archiver-cover-art.timer \\
  top40-archiver-id3-cover.timer \\
  top40-archiver-incident-scan.timer \\
  top40-archiver-auto-update.timer \\
'''
if old_timers not in text:
    raise SystemExit("FOUT: finale timerlijst in updatebasis niet gevonden")
text = text.replace(old_timers, new_timers, 1)

marker = 'systemctl is-active --quiet "$RECOVERY_TIMER"\n'
extra = '''systemctl is-active --quiet "$RECOVERY_TIMER"
systemctl is-active --quiet top40-archiver-cover-art.timer
systemctl is-active --quiet top40-archiver-id3-cover.timer
systemctl is-active --quiet top40-archiver-incident-scan.timer
systemctl start --no-block top40-archiver-cover-art.service
'''
if marker not in text:
    raise SystemExit("FOUT: finale AI-timercontrole in updatebasis niet gevonden")
text = text.replace(marker, extra, 1)


# Installeer ook de geverifieerde backup/rollbacktools voor volgende releases.
install_marker = 'install -m 0755 "$SRC/scripts/safe-update.sh" "$SAFE_UPDATER"\n'
install_extra = install_marker + 'install -m 0755 "$SRC/scripts/create-version-backup.sh" /usr/local/sbin/top40-version-backup\ninstall -m 0755 "$SRC/scripts/restore-version-backup.sh" /usr/local/sbin/top40-version-rollback\n'
if install_marker not in text:
    raise SystemExit("FOUT: safe updater installatiemarkering ontbreekt")
text = text.replace(install_marker, install_extra, 1)

health_marker = 'assert x.get("production_write") is False\n'
health_extra = health_marker + 'assert x.get("closed_loop_learning") is True\nassert x.get("audio_delete_allowed") is False\nassert x.get("verified_version_backups") is True\n'
if health_marker not in text:
    raise SystemExit("FOUT: AI health policy marker ontbreekt")
text = text.replace(health_marker, health_extra, 1)

route_marker = 'curl -fsS http://127.0.0.1:8041/api/ai/recovery >/dev/null\n'
route_extra = route_marker + 'curl -fsS http://127.0.0.1:8041/api/ai/learning >/dev/null\n'
if route_marker not in text:
    raise SystemExit("FOUT: AI learning route marker ontbreekt")
text = text.replace(route_marker, route_extra, 1)

path.write_text(text, encoding="utf-8")
PY

bash -n "$GENERATED"

echo "Top40Archiver $VERSION: transactionele updater voorbereid."
bash "$GENERATED"
