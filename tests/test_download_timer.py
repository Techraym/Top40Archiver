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


def test_update_schedules_reboot_only_after_successful_install():
    content = (ROOT / "update-existing.sh").read_text(encoding="utf-8")

    assert "schedule_reboot()" in content
    assert "--on-active=1min" in content
    assert "Dashboard-healthcheck is geslaagd" in content
    assert content.index("Dashboard-healthcheck is geslaagd") < content.index(
        "if ! schedule_reboot"
    )
