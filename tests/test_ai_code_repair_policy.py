import pytest

from app import ai_code_improvement, ai_code_repair


def test_autonomous_code_repair_only_allows_functional_python_under_app():
    assert ai_code_repair._safe_touched_files({"proposal": {"files": ["app/downloader.py"]}}) == ["app/downloader.py"]
    for blocked in (
        "scripts/top40-safe-action",
        "systemd/top40-ai-recovery.service",
        "app/templates/index.html",
        "app/ai_code_repair.py",
        "app/ai_code_improvement.py",
        "app/ai_learning.py",
        "app/ai_learning_api.py",
        "app/ai_recovery_entry.py",
        "app/ai_platform.py",
        "app/ai_sidecar.py",
        "app/ai_control_room.py",
        "app/ai_ui_designer.py",
        "app/ai_session_console.py",
        "app/ai_update_handoff.py",
        "app/service_watchdog.py",
        "app/config.py",
        "app/db.py",
    ):
        with pytest.raises(ValueError):
            ai_code_repair._safe_touched_files({"proposal": {"files": [blocked]}})


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


def test_code_repair_model_context_and_runtime_are_bounded(monkeypatch, tmp_path):
    app_root = tmp_path / "repo"
    source_dir = app_root / "app"
    source_dir.mkdir(parents=True)
    (source_dir / "big.py").write_text("x = 1\n" * 20_000, encoding="utf-8")
    monkeypatch.setattr(ai_code_repair, "APP_DIR", app_root)

    text = ai_code_repair._read_sources(["app/big.py"])

    assert len(text) <= ai_code_repair.MODEL_SOURCE_BUDGET
    assert ai_code_repair.MODEL_SOURCE_BUDGET <= 32_000
    assert ai_code_repair.MODEL_SOURCE_FILE_LIMIT <= 14_000
    assert ai_code_repair.MODEL_EVIDENCE_LIMIT <= 16_000
    assert ai_code_repair.MODEL_TIMEOUT_SECONDS <= 60


def test_improvement_source_map_excludes_monitoring_and_safety_code():
    assert ai_code_improvement._mapped_sources("downloads:retry_failed_downloads")
    assert ai_code_improvement._mapped_sources("download:no_search_results")
    assert ai_code_improvement._mapped_sources("charts:current_edition_stale") == ["app/top40.py", "app/service.py"]
    assert ai_code_improvement._mapped_sources("service:top40-archiver-ai.service") == []
    flattened = {item for items in ai_code_improvement.SOURCE_MAP.values() for item in items}
    for forbidden in (
        "app/ai_learning.py",
        "app/service_watchdog.py",
        "app/chart_freshness.py",
        "app/ai_code_repair.py",
        "app/ai_control_room.py",
        "app/ai_ui_designer.py",
        "app/ai_session_console.py",
        "app/db.py",
    ):
        assert forbidden not in flattened
    assert not any("safe" in item for item in flattened)
