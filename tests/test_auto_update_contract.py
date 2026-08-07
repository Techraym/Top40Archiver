from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_auto_update_service_uses_safe_updater():
    service = (ROOT / "systemd/top40-archiver-auto-update.service").read_text(encoding="utf-8")
    assert "ExecStart=/usr/local/sbin/top40-archiver-safe-update" in service
    assert "ConditionPathExists=/usr/local/sbin/top40-archiver-safe-update" in service


def test_ai_service_runs_unified_116_platform():
    service = (ROOT / "systemd/top40-archiver-ai.service").read_text(encoding="utf-8")
    assert "app.ai_platform:app" in service
    assert "TOP40_AI_GITHUB_WRITE=0" in service
    assert "TOP40_LOG_READER_URL=http://127.0.0.1:8042" in service
    assert "top40-log-reader.service" in service


def test_normal_updater_installs_and_validates_complete_ai_stack():
    updater = (ROOT / "update-existing.sh").read_text(encoding="utf-8")
    required = [
        "top40-safe-action",
        "top40-log-reader.service",
        "top40-archiver-ai.service",
        "top40-ai-recovery.service",
        "top40-ai-recovery.timer",
        "http://127.0.0.1:8040/health",
        "http://127.0.0.1:8041/healthz",
        "http://127.0.0.1:8042/healthz",
        "/api/development/workspaces",
        "/api/ai/recovery",
        "/ai-actions",
        "backup_configuration",
        "restore_configuration",
        "rollback_app",
        "last-recovery-report.json",
    ]
    for marker in required:
        assert marker in updater, f"auto-updatecontract mist: {marker}"


def test_update_marks_installed_sha_only_after_final_healthchecks():
    updater = (ROOT / "update-existing.sh").read_text(encoding="utf-8")
    final_health = updater.index("webinterface finale controle")
    state_write = updater.index("installed_commit_sha")
    assert final_health < state_write


def test_safe_updater_keeps_live_checkout_on_old_sha_until_install_succeeds():
    updater = (ROOT / "scripts/safe-update.sh").read_text(encoding="utf-8")
    install_call = updater.index('bash "$WORKTREE/update-existing.sh"')
    reset_target = updater.index('git reset --hard "$TARGET_SHA"')
    assert install_call < reset_target
    assert 'BRANCH="${TOP40_UPDATE_BRANCH:-main}"' in updater
    assert "git worktree add --detach" in updater
    assert "rollback" in updater


def test_legacy_updater_can_bootstrap_116():
    bootstrap = ROOT / "scripts/install-1.16.0.sh"
    assert bootstrap.exists()
    text = bootstrap.read_text(encoding="utf-8")
    assert "git archive" in text
    assert "update-existing.sh" in text
    assert "/usr/local/sbin/top40-archiver-safe-update" in text


def test_github_writes_remain_disabled_in_116():
    service = (ROOT / "systemd/top40-archiver-ai.service").read_text(encoding="utf-8")
    installer = (ROOT / "install-1.16.0.sh").read_text(encoding="utf-8")
    assert "TOP40_AI_GITHUB_WRITE=0" in service
    assert "TOP40_AI_GITHUB_WRITE=0" in installer
