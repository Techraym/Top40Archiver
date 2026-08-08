from app import ai_code_improvement as improvement
from app import ai_operator_chat as chat


def test_operator_chat_selects_download_domain_and_uses_deterministic_summary(monkeypatch):
    snapshot = {
        "generated_at": "2026-08-08T10:00:00+00:00",
        "ollama": {"reachable": True},
        "services": [],
        "database": {"health": "ok"},
        "backup": {"ok": True},
        "policy": {},
        "downloads": {"queue": 5000},
        "download_evidence": {
            "job_status": {"queued": 5000, "waiting_retry": 500},
            "recent_provider_attempts": [{"provider": "youtube", "error": "403"}] * 80,
            "recent_ai_actions": [{"action": "retry_failed_downloads"}] * 30,
        },
        "providers": [{"provider": "youtube", "status": "limited"}],
        "recent_errors": [{"message": "youtube provider download 403"}] * 80,
    }
    deterministic = {
        "job_status": {"queued": 5000, "waiting_retry": 500},
        "completed_jobs_24h": 0,
        "successful_provider_attempts_24h": 0,
        "dominant_failure_stage": "downloading",
        "error_counts": [["forbidden", 80]],
        "providers": [{"provider": "youtube", "attempts": 80, "successes": 0}],
        "recent_examples": [],
    }
    monkeypatch.setattr(chat, "collect_download_diagnostics", lambda **kwargs: deterministic)
    compact, domain = chat._compact_snapshot(snapshot, "onderzoek waarom downloader en providers mislukken")
    assert domain == "downloads"
    assert compact["download_diagnostics"] == deterministic
    assert "download_evidence" not in compact
    assert len(compact["recent_errors"]) <= 16


def test_operator_chat_parses_json_code_fence():
    payload = chat._json_payload('```json\n{"summary":"ok","diagnosis":[],"evidence":[],"recommended_actions":[],"verification_plan":[]}\n```')
    assert payload["summary"] == "ok"


def test_operator_chat_timeout_is_visible_in_fallback(monkeypatch):
    snapshot = {"ollama": {"reachable": True}}
    monkeypatch.setattr(
        chat,
        "collect_download_diagnostics",
        lambda **kwargs: {
            "job_status": {},
            "completed_jobs_24h": 0,
            "successful_provider_attempts_24h": 0,
            "dominant_failure_stage": "no_attempt_evidence",
            "error_counts": [],
        },
    )
    plan = chat._fallback_plan(
        "onderzoek downloads",
        snapshot,
        "diagnose",
        chat.OperatorModelError("qwen_timeout", "Qwen antwoordde niet binnen 75 seconden"),
    )
    assert plan["model_error_type"] == "qwen_timeout"
    assert "tijdslimiet" in plan["summary"]
    assert plan["recommended_actions"] == []
    assert any("deterministic_download_summary" in item for item in plan["evidence"])


def test_operator_chat_mobile_refresh_pauses_when_details_are_open():
    html = chat.operator_chat_page().body.decode("utf-8")
    assert "details[open]" in html
    assert "setInterval(autoRefresh,15000)" in html
    assert "setInterval(load,5000)" not in html


def test_download_code_improvement_maps_current_multi_source_engine():
    assert "app/download_manager.py" in improvement.SOURCE_MAP["downloads:"]
    assert "app/download_matching.py" in improvement.SOURCE_MAP["downloads:"]
    assert "app/download_db.py" in improvement.SOURCE_MAP["downloads:"]
    assert "app/downloader.py" not in improvement.SOURCE_MAP["downloads:"]
    assert "service:top40-archiver-download.service" not in improvement.SOURCE_MAP


def test_retry_execution_is_not_counted_as_download_success(monkeypatch):
    monkeypatch.setattr(
        improvement,
        "_ORIGINAL_CANDIDATE",
        lambda: {
            "problem_key": "downloads:retry_failed_downloads",
            "action": "retry_failed_downloads",
            "uses": 10,
            "successes": 10,
            "sources": improvement.DOWNLOAD_SOURCES,
            "lookback_hours": 6,
        },
    )
    monkeypatch.setattr(
        improvement,
        "_download_downstream_metrics",
        lambda cutoff: {
            "completed_jobs": 0,
            "successful_provider_attempts": 0,
            "provider_attempts": 50,
            "waiting_retry_now": 587,
        },
    )
    candidate = improvement._candidate()
    assert candidate["administrative_successes"] == 10
    assert candidate["successes"] == 0
    assert candidate["downstream_successes"] == 0
    assert candidate["downstream_effective"] is False
