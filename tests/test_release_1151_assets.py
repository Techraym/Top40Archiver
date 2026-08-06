from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_1151():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.15.1"


def test_safe_updater_is_transactional():
    text = (ROOT / "scripts/safe-update.sh").read_text(encoding="utf-8")
    assert "git worktree add" in text
    assert "rollback" in text
    assert "git diff --quiet" in text
    assert "flock -n" in text


def test_id3_worker_uses_apic_without_audio_transcode():
    text = (ROOT / "app/id3_cover.py").read_text(encoding="utf-8")
    assert "APIC" in text
    assert "tags.save" in text
    assert "ffmpeg" not in text.casefold()


def test_id3_service_is_low_priority():
    text = (ROOT / "systemd/top40-archiver-id3-cover.service").read_text(encoding="utf-8")
    assert "User=top40archiver" in text
    assert "Nice=15" in text
    assert "--limit 20" in text
