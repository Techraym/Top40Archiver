import pytest

from app import ai_code_improvement, ai_code_repair


def test_autonomous_code_repair_only_allows_python_under_app():
    assert ai_code_repair._safe_touched_files({"proposal": {"files": ["app/downloader.py"]}}) == ["app/downloader.py"]
    with pytest.raises(ValueError):
        ai_code_repair._safe_touched_files({"proposal": {"files": ["scripts/top40-safe-action"]}})
    with pytest.raises(ValueError):
        ai_code_repair._safe_touched_files({"proposal": {"files": ["systemd/top40-ai-recovery.service"]}})
    with pytest.raises(ValueError):
        ai_code_repair._safe_touched_files({"proposal": {"files": ["app/templates/index.html"]}})


def test_autonomous_code_repair_cannot_touch_downloaded_audio():
    for path in (
        "downloads/song.mp3",
        "app/downloads/song.mp3",
        "var/lib/top40-archiver/downloads/song.m4a",
    ):
        with pytest.raises(ValueError):
            ai_code_repair._safe_touched_files({"proposal": {"files": [path]}})


def test_exception_detector_only_accepts_app_python_paths():
    log = """
2026-08-07 Traceback (most recent call last):
  File "/opt/top40-archiver/app/downloader.py", line 100, in run
ValueError: bad source
"""
    candidate = ai_code_repair._exception_candidate(log)
    assert candidate is not None
    assert candidate["files"] == ["app/downloader.py"]

    unsafe = """
Traceback (most recent call last):
  File "/opt/top40-archiver/scripts/safe-update.sh", line 1, in run
RuntimeError: nope
"""
    assert ai_code_repair._exception_candidate(unsafe) is None


def test_improvement_source_map_excludes_monitoring_and_safety_code():
    assert ai_code_improvement._mapped_sources("downloads:retry_failed_downloads")
    assert ai_code_improvement._mapped_sources("charts:current_edition_stale")
    assert ai_code_improvement._mapped_sources("service:top40-archiver-ai.service") == []
    flattened = {item for items in ai_code_improvement.SOURCE_MAP.values() for item in items}
    assert "app/ai_learning.py" not in flattened
    assert "app/service_watchdog.py" not in flattened
    assert not any("safe" in item for item in flattened)
