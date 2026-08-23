from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _update_sources() -> tuple[str, str, str]:
    wrapper = (ROOT / "update-existing.sh").read_text(encoding="utf-8")
    base = (ROOT / "scripts" / "update-existing-1.16-base.sh").read_text(
        encoding="utf-8"
    )
    return wrapper, base, wrapper + "\n" + base


def test_download_service_runs_as_permanent_worker():
    content = (ROOT / "systemd" / "top40-archiver-download.service").read_text(
        encoding="utf-8"
    )

    assert "Type=simple" in content
    assert "User=top40archiver" in content
    assert "-m app.cli download-daemon --limit 20" in content
    assert "Restart=always" in content
    assert "RestartSec=5" in content
    assert "WantedBy=multi-user.target" in content


def test_install_and_update_enable_permanent_download_service():
    install = (ROOT / "install.sh").read_text(encoding="utf-8")
    wrapper, base, combined = _update_sources()

    assert "top40-archiver-download.service" in install
    assert "top40-archiver-download.service" in combined
    assert "disable --now top40-archiver-download.timer" in install
    assert 'disable --now "$DOWNLOAD_TIMER"' in base
    assert "systemctl restart \"$DOWNLOAD_SERVICE\"" in base

    # De release-wrapper moet de bewezen transactionele basis genereren en uitvoeren,
    # niet een tweede onafhankelijke updater implementeren.
    assert "scripts/update-existing-1.16-base.sh" in wrapper
    assert 'bash "$GENERATED"' in wrapper


def test_auto_update_runs_two_minutes_after_activation_and_every_day():
    content = (
        ROOT / "systemd" / "top40-archiver-auto-update.timer"
    ).read_text(encoding="utf-8")

    assert "OnActiveSec=2min" in content
    assert "OnBootSec=2min" not in content
    assert "OnUnitInactiveSec=24h" in content
    assert "OnUnitActiveSec=24h" not in content
    assert "Persistent=true" in content


def test_update_schedules_reboot_only_after_all_healthchecks_and_state_commit():
    wrapper, base, _ = _update_sources()

    assert "schedule_reboot()" in base
    assert "--on-active=1min" in base
    assert "webinterface finale controle" in base
    assert "AI-platform finale controle" in base
    assert "logreader finale controle" in base
    assert "installed_commit_sha" in base
    assert "UPDATE_COMPLETE=1" in base

    reboot = base.index("if ! schedule_reboot")
    assert base.index("webinterface finale controle") < reboot
    assert base.index("AI-platform finale controle") < reboot
    assert base.index("logreader finale controle") < reboot
    assert base.index("installed_commit_sha") < reboot
    assert base.index("UPDATE_COMPLETE=1") < reboot

    # De wrapper mag dit gedrag alleen release-specifiek patchen en moet daarna de
    # gegenereerde transactionele basis uitvoeren.
    assert "old_version" in wrapper
    assert "new_version" in wrapper
    assert 'bash "$GENERATED"' in wrapper
