from pathlib import Path

import pytest

from app import download_manager

ROOT = Path(__file__).resolve().parents[1]


def test_manager_has_four_global_jobs_and_three_parallel_provider_searches():
    assert download_manager.MAX_GLOBAL_DOWNLOADS == 4
    assert download_manager.MAX_PARALLEL_PROVIDER_SEARCHES == 3
    assert download_manager.PRIMARY_PRIORITY_CUTOFF < 90


def test_manager_fallback_is_priority_driven_and_youtube_not_special_cased_upward():
    source = (ROOT / "app/download_manager.py").read_text(encoding="utf-8")
    assert "PRIMARY_PRIORITY_CUTOFF = 80" in source
    assert "fallback_groups = [[row] for row in fallback]" in source
    assert "No provider" not in source
    assert "requests_per_minute" in source
    assert "min_delay_seconds" in source


def test_download_service_is_independent_from_web_app():
    service = (ROOT / "systemd/top40-download-manager.service").read_text(encoding="utf-8")
    assert "Type=simple" in service
    assert "User=top40archiver" in service
    assert "-m app.cli download-manager" in service
    assert "Restart=always" in service
    assert "NoNewPrivileges=true" in service


def test_main_chart_service_only_enqueues_downloads():
    service = (ROOT / "app/service.py").read_text(encoding="utf-8")
    assert "enqueue_track_ids(all_new_ids)" in service
    assert "queued_download_jobs" in service
    assert "download_track(" not in service


def test_post_download_validation_is_required_before_completion():
    source = (ROOT / "app/download_manager.py").read_text(encoding="utf-8")
    validation = source.index("source_info = _validate_download")
    conversion = source.index("output_info = _convert_to_mp3")
    completion = source.index('set_job_state(int(job["id"]), "completed"')
    assert validation < conversion < completion
    assert "ffprobe" in source
    assert "silencedetect" in source
    assert "MIN_FILE_BYTES" in source


def test_existing_audio_is_never_overwritten(tmp_path):
    source = tmp_path / "new.mp3"
    destination = tmp_path / "existing.mp3"
    source.write_bytes(b"n" * download_manager.MIN_FILE_BYTES)
    original = b"o" * download_manager.MIN_FILE_BYTES
    destination.write_bytes(original)

    with pytest.raises(download_manager.DownloadValidationError, match="existing_target_conflict"):
        download_manager._copy_atomic(source, destination)

    assert destination.read_bytes() == original
    assert not destination.with_suffix(".mp3.partial").exists()


def test_atomic_write_uses_create_only_link_to_close_race_window():
    source = (ROOT / "app/download_manager.py").read_text(encoding="utf-8")
    assert "if destination.exists():" in source
    assert "os.link(temporary, destination)" in source
    assert "existing_target_conflict" in source
    assert "temporary.replace(destination)" not in source


def test_source_quality_is_recorded_separately_from_output_quality():
    source = (ROOT / "app/download_manager.py").read_text(encoding="utf-8")
    assert "source_codec=source_info.get(\"codec\")" in source
    assert "source_bitrate=source_info.get(\"bitrate\")" in source
    assert "source_sample_rate=source_info.get(\"sample_rate\")" in source
    assert "output_codec=output_info.get(\"codec\")" in source
    assert "output_bitrate=output_info.get(\"bitrate\")" in source


def test_download_api_exposes_builder_contract_routes():
    source = (ROOT / "app/download_api.py").read_text(encoding="utf-8")
    for route in (
        "/api/download/status",
        "/api/download/jobs",
        "/api/download/providers",
        "/api/download/retry/{track_id}",
        "/api/download/cancel/{track_id}",
        "/api/download/provider/{provider}/enable",
        "/api/download/provider/{provider}/disable",
        "/download-providers",
    ):
        assert route in source


def test_updater_migrates_from_legacy_daemon_to_manager():
    updater = (ROOT / "update-existing.sh").read_text(encoding="utf-8")
    assert "LEGACY_DOWNLOAD_SERVICE=top40-archiver-download.service" in updater
    assert "DOWNLOAD_SERVICE=top40-download-manager.service" in updater
    assert 'systemctl disable --now "$LEGACY_DOWNLOAD_SERVICE"' in updater
    assert "top40-provider-ai.timer" in updater
    assert "/api/download/providers" in updater
