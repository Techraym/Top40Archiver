from app import ai_operator_chat as chat


def _snapshot():
    return {
        "ollama": {"reachable": True},
        "services": [
            {"unit": "top40-download-manager.service", "systemd_status": "active", "status": "active"},
            {"unit": "top40-archiver-cover-art.service", "systemd_status": "inactive", "status": "inactive"},
            {"unit": "top40-archiver-freshness.timer", "systemd_status": "inactive", "status": "inactive"},
        ],
        "download_evidence": {
            "stale_active_jobs": [],
            "job_status": {"queued": 100, "waiting_retry": 8, "failed": 2},
        },
        "charts": {"current": {"ok": False, "expected_edition": "2026-W32"}},
        "covers": {"eligible_queue": 42},
        "providers": [
            {"provider": "youtube", "status": "limited"},
            {"provider": "soundcloud", "status": "healthy"},
        ],
    }


def test_operator_chat_has_no_free_shell_or_audio_delete():
    assert "restart_download" in chat.CHAT_ALLOWED_ACTIONS
    assert "run_ai_recovery" in chat.CHAT_ALLOWED_ACTIONS
    assert "run_provider_ai" in chat.CHAT_ALLOWED_ACTIONS
    assert "rm" not in chat.CHAT_ALLOWED_ACTIONS
    assert "shell" not in chat.CHAT_ALLOWED_ACTIONS
    assert chat.MAX_ACTIONS_PER_COMMAND <= 6


def test_restart_download_requires_evidence():
    snapshot = _snapshot()
    allowed, reason = chat.action_precondition("restart_download", snapshot)
    assert allowed is False
    assert "actief" in reason

    snapshot["download_evidence"]["stale_active_jobs"] = [{"id": 1}]
    allowed, _ = chat.action_precondition("restart_download", snapshot)
    assert allowed is True


def test_chart_cover_and_recovery_actions_are_evidence_bounded():
    snapshot = _snapshot()
    assert chat.action_precondition("run_chart_freshness", snapshot)[0] is True
    assert chat.action_precondition("run_cover_art", snapshot)[0] is True
    assert chat.action_precondition("run_ai_recovery", snapshot)[0] is True
    assert chat.action_precondition("run_provider_ai", snapshot)[0] is True


def test_unknown_model_action_is_rejected():
    allowed, reason = chat.action_precondition("totally_free_shell", _snapshot())
    assert allowed is False
    assert "whitelist" in reason


def test_diagnose_mode_forces_zero_actions(monkeypatch):
    before = _snapshot() | {
        "downloads": {},
        "database": {"health": "ok"},
        "backup": {"ok": True},
        "recent_errors": [],
    }
    monkeypatch.setattr(chat, "collect_operator_evidence", lambda: before)
    monkeypatch.setattr(
        chat,
        "_ask_qwen",
        lambda command, snapshot, mode: {
            "summary": "test",
            "diagnosis": ["x"],
            "evidence": ["y"],
            "recommended_actions": [{"action": "restart_download", "reason": "test"}],
            "verification_plan": [],
        },
    )
    monkeypatch.setattr(chat, "log_session_event", lambda **kwargs: 1)
    result = chat.run_operator_command("onderzoek downloads", "diagnose")
    assert result["executed_actions"] == []
    assert result["plan"]["recommended_actions"] == []
    assert result["policy"]["free_shell"] is False
