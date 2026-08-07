from app import ai_operations_worker as worker


def _snapshot(*, queue=12, running=False, db_health="ok", ollama=True):
    cover_service = {
        "unit": "top40-archiver-cover-art.service",
        "systemd_status": "active" if running else "inactive",
        "health": "healthy",
    }
    return {
        "generated_at": "2026-08-07T12:00:00+00:00",
        "services": {
            "critical": [],
            "attention": [],
            "cover_worker": cover_service,
            "cover_timer": {"unit": "top40-archiver-cover-art.timer", "systemd_status": "active", "health": "healthy"},
            "download": {"unit": "top40-archiver-download.service", "systemd_status": "active", "health": "healthy"},
            "ollama": {"unit": "ollama.service", "systemd_status": "active", "health": "healthy"},
        },
        "covers": {
            "eligible_queue": queue,
            "without_cover": queue,
            "running": running,
            "updated_at": None,
        },
        "database": {"health": db_health},
        "downloads": {"queue": 0, "youtube_errors": 0},
        "disk": {"free_percent": 50.0, "free_gb": 100.0},
        "ollama": {"reachable": ollama, "model": "qwen3:4b"},
        "backup": {"ok": True, "version": "1.16.7"},
    }


def test_operations_worker_starts_cover_drain_when_queue_waits(monkeypatch, tmp_path):
    snapshots = [_snapshot(queue=12, running=False), _snapshot(queue=12, running=True)]
    actions = []
    monkeypatch.setattr(worker, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(worker, "REPORT_FILE", tmp_path / "report.json")
    monkeypatch.setattr(worker, "collect_snapshot", lambda: snapshots.pop(0))
    monkeypatch.setattr(worker, "_safe_action", lambda action: actions.append(action) or {"ok": True, "action": action})
    monkeypatch.setattr(worker, "_model_assessment", lambda *args: {"available": True, "summary": "ok"})

    report = worker.run_operations_worker()

    assert "run_cover_art" in actions
    assert report["after"]["covers"]["running"] is True
    assert report["policy"]["shell_access"] is False


def test_operations_worker_restarts_unreachable_ollama(monkeypatch, tmp_path):
    snapshots = [_snapshot(queue=0, ollama=False), _snapshot(queue=0, ollama=True)]
    actions = []
    monkeypatch.setattr(worker, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(worker, "REPORT_FILE", tmp_path / "report.json")
    monkeypatch.setattr(worker, "collect_snapshot", lambda: snapshots.pop(0))
    monkeypatch.setattr(worker, "_safe_action", lambda action: actions.append(action) or {"ok": True, "action": action})
    monkeypatch.setattr(worker, "_model_assessment", lambda *args: {"available": True, "summary": "ok"})

    worker.run_operations_worker()

    assert "restart_ollama" in actions


def test_healthy_operations_skip_qwen_call(monkeypatch):
    snapshot = _snapshot(queue=0, running=False, db_health="ok", ollama=True)
    monkeypatch.setattr(
        worker.requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Qwen should be skipped for a healthy deterministic cycle")),
    )

    result = worker._model_assessment(snapshot, [], [])

    assert result["available"] is True
    assert result["skipped"] is True
    assert result["risk"] == "low"
    assert worker.MODEL_TIMEOUT_SECONDS <= 45


def test_attention_state_still_requests_bounded_qwen_analysis(monkeypatch):
    snapshot = _snapshot(queue=0, running=False, db_health="ok", ollama=True)
    snapshot["services"]["attention"] = ["top40-archiver-auto-update.service"]
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": '{"summary":"retry gepland","risk":"low","attention":[],"next_check":"timer"}'}

    def fake_post(*args, **kwargs):
        calls.append(kwargs)
        return Response()

    monkeypatch.setattr(worker.requests, "post", fake_post)
    result = worker._model_assessment(snapshot, [], [])

    assert result["available"] is True
    assert calls
    assert calls[0]["timeout"] == worker.MODEL_TIMEOUT_SECONDS
    assert calls[0]["json"]["options"]["num_predict"] <= 320
