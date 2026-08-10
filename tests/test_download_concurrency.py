from pathlib import Path

from app import download_concurrency, download_concurrency_ai, download_manager_dynamic_entry

ROOT = Path(__file__).resolve().parents[1]


def _snapshot(successes: int, backlog: int = 100):
    return {
        "downloads_24h": successes,
        "jobs": {"queued": backlog, "waiting_retry": 0},
    }


def test_download_worker_policy_defaults_to_two_and_never_exceeds_six():
    assert download_concurrency.DEFAULT_DOWNLOAD_WORKERS == 2
    assert download_concurrency.MAX_DOWNLOAD_WORKERS == 6
    assert download_concurrency.AI_DECISION_TTL_MINUTES == 35
    assert download_concurrency._bounded_workers(1) == 2
    assert download_concurrency._bounded_workers(2) == 2
    assert download_concurrency._bounded_workers(6) == 6
    assert download_concurrency._bounded_workers(99) == 6


def test_worker_scaling_is_earned_by_real_completed_downloads():
    assert download_concurrency.evidence_worker_ceiling(_snapshot(0)) == 2
    assert download_concurrency.evidence_worker_ceiling(_snapshot(3)) == 2
    assert download_concurrency.evidence_worker_ceiling(_snapshot(4)) == 3
    assert download_concurrency.evidence_worker_ceiling(_snapshot(11)) == 3
    assert download_concurrency.evidence_worker_ceiling(_snapshot(12)) == 4
    assert download_concurrency.evidence_worker_ceiling(_snapshot(30)) == 5
    assert download_concurrency.evidence_worker_ceiling(_snapshot(60)) == 6


def test_no_backlog_means_no_scale_up_even_with_many_successes():
    assert download_concurrency.evidence_worker_ceiling(_snapshot(100, backlog=3)) == 2


def test_dynamic_manager_caps_ai_target_by_deterministic_evidence(monkeypatch):
    monkeypatch.setattr(
        download_manager_dynamic_entry,
        "worker_state",
        lambda: {
            "base": 2,
            "effective": 6,
            "maximum": 6,
            "ai_target": 6,
            "ai_active": True,
            "ai_until": "2099-01-01T00:00:00+00:00",
            "ai_reason": "test",
        },
    )
    config = download_manager_dynamic_entry._worker_configuration(_snapshot(12))
    assert config["effective"] == 4
    assert config["evidence_ceiling"] == 4


def test_system_pressure_can_only_reduce_qwen_ceiling():
    assert download_concurrency_ai._system_worker_ceiling(
        {"load_1m_per_cpu": 0.2, "memory_available_percent": 70.0}
    ) == 6
    assert download_concurrency_ai._system_worker_ceiling(
        {"load_1m_per_cpu": 0.75, "memory_available_percent": 70.0}
    ) == 5
    assert download_concurrency_ai._system_worker_ceiling(
        {"load_1m_per_cpu": 1.25, "memory_available_percent": 70.0}
    ) == 2
    assert download_concurrency_ai._system_worker_ceiling(
        {"load_1m_per_cpu": 0.1, "memory_available_percent": 9.0}
    ) == 2


def test_service_launches_dynamic_manager_and_ai_runner_tunes_workers():
    service = (ROOT / "systemd/top40-download-manager.service").read_text(encoding="utf-8")
    runner = (ROOT / "app/provider_ai_runner.py").read_text(encoding="utf-8")
    ai = (ROOT / "app/download_concurrency_ai.py").read_text(encoding="utf-8")

    assert "-m app.download_manager_dynamic_entry" in service
    assert "run_download_concurrency_ai" in runner
    assert "model_slot(" in ai
    assert "evidence_worker_ceiling" in ai
    assert "MAX_DOWNLOAD_WORKERS" in ai
    assert "YouTube Music blijven maximaal 1" in ai
    assert '"audio_delete_allowed": False' in ai
    assert '"overwrite_existing_audio_allowed": False' in ai
