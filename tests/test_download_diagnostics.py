from contextlib import contextmanager

from app import ai_operator_chat as chat
from app.download_diagnostics import _stage


def test_download_stage_classifier_separates_pipeline_failures():
    assert _stage("forbidden", "HTTP 403", "https://example.invalid/a", 0) == "downloading"
    assert _stage("low_match_score", "candidate rejected", "https://example.invalid/a", 0) == "matching"
    assert _stage("preview_duration", "30 second preview", "https://example.invalid/a", 0) == "validation"
    assert _stage("ffprobe", "invalid audio", "https://example.invalid/a", 0) == "validation"
    assert _stage(None, None, "https://example.invalid/a", 1) == "provider_success"


def test_download_operator_budget_is_small_and_non_thinking():
    assert chat.DOWNLOAD_EVIDENCE_BYTES <= 6500
    assert chat.DOWNLOAD_RETRY_EVIDENCE_BYTES <= 3200
    assert chat.DOWNLOAD_MODEL_TIMEOUT_SECONDS < chat.MODEL_TIMEOUT_SECONDS


def test_download_qwen_call_disables_thinking_and_uses_compact_context(monkeypatch):
    snapshot = {
        "generated_at": "2026-08-08T12:00:00+00:00",
        "ollama": {"reachable": True},
        "services": [],
        "database": {"health": "ok"},
        "backup": {"ok": True},
        "policy": {},
        "downloads": {},
        "recent_errors": [],
    }
    monkeypatch.setattr(
        chat,
        "collect_download_diagnostics",
        lambda **kwargs: {
            "job_status": {"queued": 10, "waiting_retry": 4},
            "completed_jobs_24h": 0,
            "successful_provider_attempts_24h": 0,
            "dominant_failure_stage": "downloading",
            "providers": [],
            "recent_examples": [],
        },
    )

    @contextmanager
    def slot(*args, **kwargs):
        yield {}

    monkeypatch.setattr(chat, "model_slot", slot)
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "response": '{"summary":"ok","diagnosis":[],"evidence":[],"recommended_actions":[],"verification_plan":[]}',
                "prompt_eval_count": 321,
                "eval_count": 42,
                "total_duration": 123,
            }

    def fake_post(url, json, timeout):
        captured["json"] = json
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(chat.requests, "post", fake_post)
    result = chat._call_qwen("onderzoek downloads", snapshot, "diagnose", retry=False)

    assert captured["json"]["think"] is False
    assert captured["json"]["options"]["num_ctx"] == 4096
    assert captured["json"]["options"]["num_predict"] <= 280
    assert captured["timeout"] == chat.DOWNLOAD_MODEL_TIMEOUT_SECONDS
    assert result["model_runtime"]["think"] is False
    assert result["model_runtime"]["prompt_eval_count"] == 321
