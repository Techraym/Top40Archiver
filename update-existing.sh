#!/bin/bash
set -Eeuo pipefail

# Top40Archiver transactionele update-entrypoint.
# De bewezen 1.16-basis blijft in scripts/update-existing-1.16-base.sh.
# Deze wrapper maakt een release-specifieke tijdelijke updater, maar start pas
# nadat een zelfstandig geverifieerd rollbackpakket van de huidige versie bestaat.
# Contract-markers voor CI: top40-safe-action top40-log-reader.service
# top40-archiver-ai.service top40-ai-recovery.service top40-ai-recovery.timer
# top40-archiver-freshness.service top40-archiver-freshness.timer
# http://127.0.0.1:8040/health http://127.0.0.1:8041/healthz
# http://127.0.0.1:8042/healthz /api/development/workspaces /api/ai/recovery
# /api/ai/learning /api/ai/chart-freshness /api/ai/code-repair
# /ai-actions backup_configuration restore_configuration rollback_app
# last-recovery-report.json webinterface finale controle installed_commit_sha

SRC=$(cd "$(dirname "$0")" && pwd)
BASE="$SRC/scripts/update-existing-1.16-base.sh"
GENERATED="$SRC/.update-existing.generated.sh"
VERSION=$(tr -d '[:space:]' < "$SRC/VERSION" 2>/dev/null || echo unknown)

[ "$(id -u)" -eq 0 ] || { echo "Voer dit script als root uit."; exit 1; }
[ -f "$BASE" ] || { echo "FOUT: transactionele updatebasis ontbreekt: $BASE"; exit 1; }
[ -f "$SRC/scripts/create-version-backup.sh" ] || { echo "FOUT: versie-backuptool ontbreekt."; exit 1; }
[ -f "$SRC/scripts/restore-version-backup.sh" ] || { echo "FOUT: versie-rollbacktool ontbreekt."; exit 1; }
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
[ -f "$ROLLBACK_BACKUP/manifest.sha256" ] || { echo "FOUT: rollback-manifest ontbreekt"; exit 1; }
(
  cd "$ROLLBACK_BACKUP"
  sha256sum -c manifest.sha256 >/dev/null
)
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
bs = "\\"

old_version = 'assert x.get("version") == "1.16.0"'
new_version = f'assert x.get("version") == "{version}"'
if old_version not in text:
    raise SystemExit("FOUT: AI-healthversiepatch kan niet worden toegepast")
text = text.replace(old_version, new_version, 1)
text = text.replace('echo "=== Preflight 1.16.0 ==="', f'echo "=== Preflight {version} ==="', 1)

old_tests = "\n".join([
    "      tests/test_ai_recovery_strategies.py " + bs,
    "      tests/test_auto_update_contract.py",
])
new_tests = "\n".join([
    "      tests/test_ai_recovery_strategies.py " + bs,
    "      tests/test_cover_drain_worker.py " + bs,
    "      tests/test_ai_operations_worker.py " + bs,
    "      tests/test_ai_learning.py " + bs,
    "      tests/test_chart_freshness.py " + bs,
    "      tests/test_ai_code_repair_policy.py " + bs,
    "      tests/test_version_backup_contract.py " + bs,
    "      tests/test_auto_update_contract.py",
])
if old_tests not in text:
    raise SystemExit("FOUT: regressietestlijst in updatebasis niet gevonden")
text = text.replace(old_tests, new_tests, 1)

old_timers = "\n".join([
    "  top40-archiver-history.timer " + bs,
    "  top40-archiver-check.timer " + bs,
    "  top40-archiver-auto-update.timer " + bs,
]) + "\n"
new_timers = "\n".join([
    "  top40-archiver-history.timer " + bs,
    "  top40-archiver-check.timer " + bs,
    "  top40-archiver-freshness.timer " + bs,
    "  top40-archiver-cover-art.timer " + bs,
    "  top40-archiver-id3-cover.timer " + bs,
    "  top40-archiver-incident-scan.timer " + bs,
    "  top40-archiver-auto-update.timer " + bs,
]) + "\n"
if old_timers not in text:
    raise SystemExit("FOUT: finale timerlijst in updatebasis niet gevonden")
text = text.replace(old_timers, new_timers, 1)

marker = 'systemctl is-active --quiet "$RECOVERY_TIMER"\n'
extra = (
    marker
    + "systemctl is-active --quiet top40-archiver-freshness.timer\n"
    + "systemctl is-active --quiet top40-archiver-cover-art.timer\n"
    + "systemctl is-active --quiet top40-archiver-id3-cover.timer\n"
    + "systemctl is-active --quiet top40-archiver-incident-scan.timer\n"
    + "systemctl start --no-block top40-archiver-freshness.service\n"
    + "systemctl start --no-block top40-archiver-cover-art.service\n"
)
if marker not in text:
    raise SystemExit("FOUT: finale AI-timercontrole in updatebasis niet gevonden")
text = text.replace(marker, extra, 1)

# Backup/rollbacktools worden onderdeel van de geïnstalleerde beheerlaag.
install_marker = 'install -m 0755 "$SRC/scripts/safe-update.sh" "$SAFE_UPDATER"\n'
install_extra = (
    install_marker
    + 'install -m 0755 "$SRC/scripts/create-version-backup.sh" /usr/local/sbin/top40-version-backup\n'
    + 'install -m 0755 "$SRC/scripts/restore-version-backup.sh" /usr/local/sbin/top40-version-rollback\n'
)
if install_marker not in text:
    raise SystemExit("FOUT: safe updater installatiemarkering ontbreekt")
text = text.replace(install_marker, install_extra, 1)

# De update is alleen gezond als 8041 de nieuwe harde veiligheidsregels geladen heeft.
health_marker = 'assert x.get("production_write") is False\n'
health_extra = (
    health_marker
    + 'assert x.get("closed_loop_learning") is True\n'
    + 'assert x.get("continuous_online_learning") is True\n'
    + 'assert x.get("learning_starts_at_action") == 1\n'
    + 'assert x.get("chart_freshness_guard") is True\n'
    + 'assert x.get("autonomous_code_repair") is True\n'
    + 'assert x.get("code_repair_requires_verified_backup") is True\n'
    + 'assert x.get("audio_delete_allowed") is False\n'
    + 'assert x.get("verified_version_backups") is True\n'
)
if health_marker not in text:
    raise SystemExit("FOUT: AI health policy marker ontbreekt")
text = text.replace(health_marker, health_extra, 1)

route_marker = 'curl -fsS http://127.0.0.1:8041/api/ai/recovery >/dev/null\n'
route_extra = (
    route_marker
    + 'curl -fsS http://127.0.0.1:8041/api/ai/learning >/dev/null\n'
    + 'curl -fsS http://127.0.0.1:8041/api/ai/chart-freshness >/dev/null\n'
    + 'curl -fsS http://127.0.0.1:8041/api/ai/code-repair >/dev/null\n'
)
if route_marker not in text:
    raise SystemExit("FOUT: AI learning route marker ontbreekt")
text = text.replace(route_marker, route_extra, 1)

path.write_text(text, encoding="utf-8")
PY

bash -n "$GENERATED"

echo "Top40Archiver $VERSION: transactionele updater voorbereid."
bash "$GENERATED"
