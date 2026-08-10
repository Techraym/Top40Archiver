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
        "top40-archiver-freshness.service",
        "top40-archiver-freshness.timer",
        "top40-archiver-cover-art.service",
        "http://127.0.0.1:8040/health",
        "http://127.0.0.1:8041/healthz",
        "http://127.0.0.1:8042/healthz",
        "/api/development/workspaces",
        "/api/ai/recovery",
        "/api/ai/learning",
        "/api/ai/chart-freshness",
        "/api/ai/code-repair",
        "/api/ai/control-room",
        "/api/ai/session/status",
        "/api/ai/session/events",
        "/api/ai/session/guidance",
        "/ai-session",
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
    assert "top40-archiver-freshness.timer" in updater
    assert "top40-archiver-cover-art.timer" in updater
    assert "top40-archiver-id3-cover.timer" in updater
    assert "top40-archiver-incident-scan.timer" in updater
    assert "tests/test_cover_drain_worker.py" in updater
    assert "tests/test_download_policy.py" in updater
    assert "tests/test_download_concurrency.py" in updater
    assert "tests/test_ai_operations_worker.py" in updater
    assert "tests/test_service_watchdog.py" in updater
    assert "tests/test_chart_freshness.py" in updater
    assert "tests/test_ai_code_repair_policy.py" in updater
    assert "tests/test_ai_control_room.py" in updater
    assert "tests/test_ai_session_console.py" in updater
    assert "systemctl start --no-block top40-ai-recovery.service" in updater
    assert "systemctl enable --now top40-archiver-cover-art.service" in updater
    assert "systemctl is-active --quiet top40-archiver-cover-art.service" in updater
    assert 'assert x.get("ai_control_room") is True' in updater
    assert 'assert x.get("local_ai_owned_control_room_html_css") is True' in updater
    assert 'assert x.get("ai_session_console") is True' in updater
    assert 'assert x.get("operator_guidance") is True' in updater
    assert 'assert x.get("operator_domain_hold") is True' in updater
    assert 'assert x.get("human_approval_per_cycle_required") is False' in updater
    assert 'assert x.get("cover_continuous_worker") is True' in updater
    assert 'assert x.get("youtube_primary_download_source") is True' in updater
    assert 'assert x.get("youtube_last_resort") is False' in updater
    assert 'assert x.get("current_chart_download_priority") is True' in updater
    assert 'assert x.get("transient_candidate_retry") is True' in updater
    assert "http://127.0.0.1:8041/api/ai/control-room?limit=25" in updater
    assert "http://127.0.0.1:8041/api/ai/session/status" in updater
    assert "http://127.0.0.1:8041/ai-session" in updater


def test_generated_updater_quotes_urls_with_query_strings():
    updater = (ROOT / "update-existing.sh").read_text(encoding="utf-8")
    assert 'curl -fsS "http://127.0.0.1:8041/api/ai/control-room?limit=25" >/dev/null' in updater
    assert 'curl -fsS "http://127.0.0.1:8041/api/ai/session/events?limit=10" >/dev/null' in updater
    assert "shopt -s nullglob" in (ROOT / "scripts/update-existing-1.16-base.sh").read_text(encoding="utf-8")


def test_release_promotion_does_not_wait_for_full_ai_recovery_cycle():
    updater = (ROOT / "update-existing.sh").read_text(encoding="utf-8")
    assert "old_recovery_gate" in updater
    assert "new_recovery_gate" in updater
    assert "operationele AI-uitkomst blokkeert softwarepromotie niet" in updater
    assert "systemctl start --no-block top40-ai-recovery.service" in updater


def test_service_watchdog_units_and_entrypoint_are_release_managed():
    cover_service = ROOT / "systemd/top40-archiver-cover-art.service"
    cover_timer = ROOT / "systemd/top40-archiver-cover-art.timer"
    freshness_service = ROOT / "systemd/top40-archiver-freshness.service"
    freshness_timer = ROOT / "systemd/top40-archiver-freshness.timer"
    recovery_service = (ROOT / "systemd/top40-ai-recovery.service").read_text(encoding="utf-8")
    recovery_timer = (ROOT / "systemd/top40-ai-recovery.timer").read_text(encoding="utf-8")
    safe_action = (ROOT / "scripts/top40-safe-action").read_text(encoding="utf-8")
    watchdog = (ROOT / "app/service_watchdog.py").read_text(encoding="utf-8")

    assert cover_service.exists()
    assert cover_timer.exists()
    assert freshness_service.exists()
    assert freshness_timer.exists()
    cover_service_text = cover_service.read_text(encoding="utf-8")
    cover_timer_text = cover_timer.read_text(encoding="utf-8")
    freshness_timer_text = freshness_timer.read_text(encoding="utf-8")
    assert "Type=simple" in cover_service_text
    assert "-m app.cover_watch" in cover_service_text
    assert "--poll-seconds 60" in cover_service_text
    assert "Restart=always" in cover_service_text
    assert "WantedBy=multi-user.target" in cover_service_text
    assert "OnUnitInactiveSec=30min" in cover_timer_text
    assert "OnUnitInactiveSec=10min" in freshness_timer_text
    assert "app.ai_recovery_entry" in recovery_service
    assert "ReadWritePaths=/var/lib/top40-archiver /etc/systemd/system /opt/top40-archiver/app" in recovery_service
    assert "/opt/top40-archiver/downloads" not in recovery_service
    assert "top40-archiver-cover-art.timer" in recovery_timer
    assert "top40-archiver-freshness.timer" in recovery_timer
    assert "repair_cover_timer" in safe_action
    assert "run_cover_art" in safe_action
    assert "restart_cover_art" in safe_action
    assert "repair_freshness_timer" in safe_action
    assert "run_chart_freshness" in safe_action
    assert '"top40-archiver-cover-art.service": {"group": "cover", "kind": "daemon"' in watchdog
    assert "top40-archiver-cover-art.timer" in watchdog
    assert "top40-archiver-freshness.timer" in watchdog
    assert "paired_timer" in watchdog
    assert "retry gepland" in watchdog


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


def test_safe_updater_restores_git_ownership_and_root_safe_directory():
    updater = (ROOT / "scripts/safe-update.sh").read_text(encoding="utf-8")
    assert "restore_git_ownership" in updater
    assert 'REPO_OWNER="$(stat -c \'%U\' "$APP")"' in updater
    assert 'REPO_GROUP="$(stat -c \'%G\' "$APP")"' in updater
    assert 'git config --system --add safe.directory "$APP"' in updater
    assert 'chown -R "$REPO_OWNER:$REPO_GROUP" "$APP/.git"' in updater
    assert "trap restore_git_ownership EXIT" in updater
    assert "restore_git_ownership" in updater[updater.index("cleanup()") :]


def test_safe_updater_recognizes_only_active_ai_managed_dirty_code():
    updater = (ROOT / "scripts/safe-update.sh").read_text(encoding="utf-8")
    assert "is_ai_managed_dirty" in updater
    assert "code-repair-state.json" in updater
    assert "code-improvement-state.json" in updater
    assert "AI_LOCAL_PATCH" in updater
    assert "git diff --binary" in updater
    assert "git apply --check" in updater
    assert "app.ai_update_handoff" in updater
    assert "lokale wijzigingen gevonden die niet aantoonbaar" in updater


def test_legacy_updater_can_bootstrap_116():
    bootstrap = ROOT / "scripts/install-1.16.0.sh"
    assert bootstrap.exists()
    text = bootstrap.read_text(encoding="utf-8")
    assert "git archive" in text
    assert "update-existing.sh" in text
    assert "/usr/local/sbin/top40-archiver-safe-update" in text


def test_github_writes_remain_disabled_for_development_assistant():
    service = (ROOT / "systemd/top40-archiver-ai.service").read_text(encoding="utf-8")
    installer = (ROOT / "install-1.16.0.sh").read_text(encoding="utf-8")
    assert "TOP40_AI_GITHUB_WRITE=0" in service
    assert "TOP40_AI_GITHUB_WRITE=0" in installer
