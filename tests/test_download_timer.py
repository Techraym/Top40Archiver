from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_download_service_processes_bounded_queue_batch():
    content = (ROOT / "systemd" / "top40-archiver-download.service").read_text(
        encoding="utf-8"
    )

    assert "Type=oneshot" in content
    assert "User=top40archiver" in content
    assert "-m app.cli retry --limit 20" in content
    assert "TimeoutStartSec=2h" in content


def test_download_timer_runs_after_boot_and_after_previous_batch():
    content = (ROOT / "systemd" / "top40-archiver-download.timer").read_text(
        encoding="utf-8"
    )

    assert "OnBootSec=5min" in content
    assert "OnUnitInactiveSec=5min" in content
    assert "Unit=top40-archiver-download.service" in content
    assert "WantedBy=timers.target" in content


def test_install_and_update_enable_download_timer():
    install = (ROOT / "install.sh").read_text(encoding="utf-8")
    update = (ROOT / "update-existing.sh").read_text(encoding="utf-8")

    assert "top40-archiver-download.timer" in install
    assert "top40-archiver-download.timer" in update
