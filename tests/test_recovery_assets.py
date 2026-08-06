from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_recovery_installer_exists_and_is_guarded():
    text = (ROOT / "scripts" / "recover-1.15.0-alpha.3.sh").read_text(encoding="utf-8")
    assert "git diff --quiet" in text
    assert "recovery_1.15.0-alpha.3" in text
    assert "download_workers','1" in text


def test_light_ui_recovery_scripts_are_retained():
    assert (ROOT / "scripts" / "apply-modern-light-ui.sh").exists()
    assert (ROOT / "scripts" / "apply-light-settings-panel.sh").exists()


def test_cover_recovery_scripts_are_retained():
    cover_install = ROOT / "scripts" / "apply-musicbrainz-cover-art.sh"
    cover_worker = ROOT / "scripts" / "fix-cover-art-worker.sh"
    assert cover_install.exists()
    assert cover_worker.exists()
    assert "MusicBrainz" in cover_install.read_text(encoding="utf-8")
    assert "top40-archiver-cover-art.timer" in cover_worker.read_text(encoding="utf-8")


def test_version_is_recovery_release():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.15.0-alpha.3"
