from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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
    update = (ROOT / "update-existing.sh").read_text(encoding="utf-8")

    assert "top40-archiver-download.service" in install
    assert "top40-archiver-download.service" in update
    assert "disable --now top40-archiver-download.timer" in install
    assert 'disable --now "$DOWNLOAD_TIMER"' in update
    assert "systemctl restart \"$DOWNLOAD_SERVICE\"" in update


def test_auto_update_runs_two_minutes_after_boot_and_every_day():
    content = (
        ROOT / "systemd" / "top40-archiver-auto-update.timer"
    ).read_text(encoding="utf-8")

    assert "OnBootSec=2min" in content
    assert "OnUnitActiveSec=24h" in content
    assert "Persistent=true" in content


def test_update_schedules_reboot_only_after_all_healthchecks_and_state_commit():
    content = (ROOT / "update-existing.sh").read_text(encoding="utf-8")

    assert "schedule_reboot()" in content
    assert "--on-active=1min" in content
    assert "webinterface finale controle" in content
    assert "AI-platform finale controle" in content
    assert "logreader finale controle" in content
    assert "installed_commit_sha" in content
    assert "UPDATE_COMPLETE=1" in content

    reboot = content.index("if ! schedule_reboot")
    assert content.index("webinterface finale controle") < reboot
    assert content.index("AI-platform finale controle") < reboot
    assert content.index("logreader finale controle") < reboot
    assert content.index("installed_commit_sha") < reboot
    assert content.index("UPDATE_COMPLETE=1") < reboot
