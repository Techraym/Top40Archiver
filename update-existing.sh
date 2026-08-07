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

path.write_text(text, encoding="utf-8")
PY

bash -n "$GENERATED"

echo "Top40Archiver $VERSION: transactionele updater voorbereid."
bash "$GENERATED"
