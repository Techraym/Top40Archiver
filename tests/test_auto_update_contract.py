from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_auto_update_service_uses_safe_updater():
    service = (ROOT / "systemd/top40-archiver-auto-update.service").read_text(encoding="utf-8")
    assert "ExecStart=/usr/local/sbin/top40-archiver-safe-update" in service
    assert "ConditionPathExists=/usr/local/sbin/top40-archiver-safe-update" in service
    assert "/opt/top40-archiver/auto-update.sh" not in service


def test_installer_deploys_and_enables_auto_update_units():
    installer = (ROOT / "scripts/install-1.15.1.sh").read_text(encoding="utf-8")
    assert "scripts/safe-update.sh" in installer
    assert "/usr/local/sbin/top40-archiver-safe-update" in installer
    assert "top40-archiver-auto-update.service" in installer
    assert "top40-archiver-auto-update.timer" in installer
    assert "enable --now top40-archiver-auto-update.timer" in installer


def test_safe_updater_defaults_to_main_and_validates_version():
    updater = (ROOT / "scripts/safe-update.sh").read_text(encoding="utf-8")
    assert 'BRANCH="${TOP40_UPDATE_BRANCH:-main}"' in updater
    assert 'NEW_VERSION="$(tr -d' in updater
    assert "lege VERSION" in updater
    assert "git worktree add --detach" in updater
    assert "rollback" in updater
