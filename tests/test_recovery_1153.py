from pathlib import Path


def test_release_version_and_assets():
    assert Path("VERSION").read_text().strip() == "1.15.3"
    assert Path("app/recovery_engine.py").exists()
    assert Path("scripts/top40-recovery-action").exists()
    assert Path("scripts/install-1.15.3.sh").exists()


def test_recovery_actions_are_allowlisted():
    text = Path("app/recovery_engine.py").read_text()
    for action in (
        "set_workers_one",
        "pause_downloads",
        "resume_downloads",
        "run_test_download",
        "clear_circuit_breaker",
    ):
        assert action in text
    assert "shell=True" not in text
    assert "sudo -n" in text


def test_root_helper_rejects_unknown_actions():
    helper = Path("scripts/top40-recovery-action").read_text()
    assert 'case "$ACTION" in' in helper
    assert "Actie niet toegestaan" in helper
    assert "rm -rf" not in helper
    assert "git reset" not in helper
