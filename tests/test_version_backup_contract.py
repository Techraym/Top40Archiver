from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_version_backup_is_verified_and_complete():
    script = (ROOT / "scripts/create-version-backup.sh").read_text(encoding="utf-8")
    required = [
        "app.tar.gz",
        "repository.bundle",
        ".backup '$BACKUP_DIR/top40.sqlite3'",
        ".backup '$BACKUP_DIR/ai_memory.sqlite'",
        "PRAGMA quick_check",
        "manifest.sha256",
        "sha256sum -c",
        "BACKUP_OK",
        '"audio_library_touched": False',
    ]
    for marker in required:
        assert marker in script, marker


def test_update_refuses_to_start_without_verified_rollback_backup():
    updater = (ROOT / "update-existing.sh").read_text(encoding="utf-8")
    assert "Verifieerbare versie-rollbackbackup" in updater
    assert "create-version-backup.sh" in updater
    assert "ROLLBACK_BACKUP/BACKUP_OK" in updater
    assert updater.index("Verifieerbare versie-rollbackbackup") < updater.index('cp "$BASE" "$GENERATED"')


def test_safe_updater_deploys_backup_and_rollback_tools():
    updater = (ROOT / "scripts/safe-update.sh").read_text(encoding="utf-8")
    assert "scripts/create-version-backup.sh" in updater
    assert "scripts/restore-version-backup.sh" in updater
    assert "/usr/local/sbin/top40-version-backup" in updater
    assert "/usr/local/sbin/top40-version-rollback" in updater


def test_default_rollback_preserves_current_database_progress():
    restore = (ROOT / "scripts/restore-version-backup.sh").read_text(encoding="utf-8")
    assert "--with-database" in restore
    assert "Database wordt niet teruggezet" in restore
    assert "Gedownloade audiobestanden worden niet aangeraakt" in restore


def test_ai_safe_action_has_no_audio_delete_capability():
    wrapper = (ROOT / "scripts/top40-safe-action").read_text(encoding="utf-8")
    assert 'FORBIDDEN_EXECUTABLES = {"rm", "unlink", "shred"}' in wrapper
    assert '"audio_delete_allowed": False' in wrapper
    action_section = wrapper.split("ACTIONS =", 1)[1].split("FORBIDDEN_EXECUTABLES", 1)[0]
    assert '["rm"' not in action_section
    assert '["unlink"' not in action_section
    assert '["shred"' not in action_section


def test_ai_platform_advertises_hard_safety_and_continuous_learning_contract():
    platform = (ROOT / "app/ai_platform.py").read_text(encoding="utf-8")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert "VERSION = _release_version()" in platform
    assert version and version.count(".") == 2
    assert '"closed_loop_learning": True' in platform
    assert '"continuous_online_learning": True' in platform
    assert '"learning_starts_at_action": 1' in platform
    assert '"chart_freshness_guard": True' in platform
    assert '"autonomous_code_repair": True' in platform
    assert '"code_repair_requires_verified_backup": True' in platform
    assert '"verified_version_backups": True' in platform
    assert '"audio_delete_allowed": False' in platform
    assert '"ai_control_room": True' in platform
    assert '"local_ai_owned_control_room_html_css": True' in platform
    assert '"control_room_safe_runtime": True' in platform
    assert '"ai_session_console": True' in platform
    assert '"operator_guidance": True' in platform
    assert '"operator_domain_hold": True' in platform
    assert '"raw_chain_of_thought_exposed": False' in platform
    assert '"decision_summaries_exposed": True' in platform
    assert '"multi_source_download_engine": True' in platform
    assert '"youtube_max_concurrent": 1' in platform
    assert '"rate_limit_bypass_allowed": False' in platform
    assert '"proxy_rotation_allowed": False' in platform
    assert '/ai-learning' in platform
    assert '/ai-session' in platform
