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
    base = (ROOT / "scripts/update-existing-1.16-base.sh").read_text(encoding="utf-8")
    combined = updater + "\n" + base
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
        assert marker in combined, f"auto-updatecontract mist: {marker}"

    assert "old_version" in updater
    assert "new_version" in updater
    assert "top40-archiver-cover-art.timer" in updater
    assert "top40-archiver-id3-cover.timer" in updater
    assert "top40-archiver-incident-scan.timer" in updater
    assert "tests/test_cover_drain_worker.py" in updater
    assert "tests/test_ai_operations_worker.py" in updater


def test_service_watchdog_units_and_entrypoint_are_release_managed():
    cover_service = ROOT / "systemd/top40-archiver-cover-art.service"
    cover_timer = ROOT / "systemd/top40-archiver-cover-art.timer"
    recovery_service = (ROOT / "systemd/top40-ai-recovery.service").read_text(encoding="utf-8")
    recovery_timer = (ROOT / "systemd/top40-ai-recovery.timer").read_text(encoding="utf-8")
    safe_action = (ROOT / "scripts/top40-safe-action").read_text(encoding="utf-8")
    watchdog = (ROOT / "app/service_watchdog.py").read_text(encoding="utf-8")

    assert cover_service.exists()
    assert cover_timer.exists()
    cover_service_text = cover_service.read_text(encoding="utf-8")
    cover_timer_text = cover_timer.read_text(encoding="utf-8")
    assert "Type=oneshot" in cover_service_text
    assert "--drain" in cover_service_text
    assert "TimeoutStartSec=infinity" in cover_service_text
    assert "OnUnitInactiveSec=30min" in cover_timer_text
    assert "app.ai_recovery_entry" in recovery_service
    assert "top40-archiver-cover-art.timer" in recovery_timer
    assert "repair_cover_timer" in safe_action
    assert "run_cover_art" in safe_action
    assert "restart_cover_art" in safe_action
    assert "top40-archiver-cover-art.timer" in watchdog
    assert "paired_timer" in watchdog


def test_update_marks_installed_sha_only_after_final_healthchecks():
    base = (ROOT / "scripts/update-existing-1.16-base.sh").read_text(encoding="utf-8")
    final_health = base.index("webinterface finale controle")
    state_write = base.index("installed_commit_sha")
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
