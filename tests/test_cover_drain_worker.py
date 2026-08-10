from pathlib import Path

import pytest

from app import cover_art, cover_watch


def test_drain_keeps_running_until_queue_is_empty(monkeypatch):
    queue = [80, 40, 0]
    calls = []

    def fake_queue_count():
        return queue[0]

    def fake_fill(limit=40, retry_current=False):
        calls.append((limit, retry_current))
        before = queue.pop(0)
        after = queue[0]
        processed = before - after
        return {"processed": processed, "found": processed, "missing": 0, "transient": 0}

    monkeypatch.setattr(cover_art, "cover_queue_count", fake_queue_count)
    monkeypatch.setattr(cover_art, "total_without_cover", lambda: 0)
    monkeypatch.setattr(cover_art, "fill_missing_covers", fake_fill)
    monkeypatch.setattr(cover_art, "write_cover_state", lambda **kwargs: None)

    result = cover_art.drain_missing_covers(batch_size=40, retry_current=True)

    assert result["status"] == "drained"
    assert result["processed"] == 80
    assert result["queue_remaining"] == 0
    assert calls == [(40, True), (40, False)]


def test_drain_backs_off_when_transient_source_makes_no_progress(monkeypatch):
    queue = [2, 2, 0]
    sleeps = []

    def fake_fill(limit=40, retry_current=False):
        if len(sleeps) == 0:
            return {"processed": 2, "found": 0, "missing": 0, "transient": 2}
        queue[0] = 0
        return {"processed": 2, "found": 2, "missing": 0, "transient": 0}

    monkeypatch.setattr(cover_art, "cover_queue_count", lambda: queue[0])
    monkeypatch.setattr(cover_art, "total_without_cover", lambda: queue[0])
    monkeypatch.setattr(cover_art, "fill_missing_covers", fake_fill)
    monkeypatch.setattr(cover_art, "write_cover_state", lambda **kwargs: None)
    monkeypatch.setattr(cover_art.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = cover_art.drain_missing_covers(batch_size=40, transient_retry_seconds=17)

    assert sleeps == [17]
    assert result["status"] == "drained"


def test_continuous_watcher_drains_new_work_then_remains_watching(monkeypatch):
    queue = [3, 0]
    drains = []
    states = []

    monkeypatch.setattr(cover_watch, "cover_queue_count", lambda: queue[0])
    monkeypatch.setattr(cover_watch, "total_without_cover", lambda: queue[0])

    def fake_drain(**kwargs):
        drains.append(kwargs)
        queue[0] = 0
        return {"ok": True, "status": "drained"}

    monkeypatch.setattr(cover_watch, "drain_missing_covers", fake_drain)
    monkeypatch.setattr(cover_watch, "write_cover_state", lambda **kwargs: states.append(kwargs))

    def stop_after_first_watch(_seconds):
        raise RuntimeError("stop-test-loop")

    monkeypatch.setattr(cover_watch.time, "sleep", stop_after_first_watch)

    with pytest.raises(RuntimeError, match="stop-test-loop"):
        cover_watch.watch_missing_covers(batch_size=40, poll_seconds=60)

    assert len(drains) == 1
    assert drains[0]["batch_size"] == 40
    assert any(state.get("phase") == "starting" for state in states)
    assert states[-1]["phase"] == "watching"
    assert states[-1]["queue_remaining"] == 0
    assert states[-1]["running"] is True


def test_cover_systemd_unit_is_continuous_daemon_with_watch_mode():
    service = Path("systemd/top40-archiver-cover-art.service").read_text(encoding="utf-8")
    timer = Path("systemd/top40-archiver-cover-art.timer").read_text(encoding="utf-8")
    assert "Type=simple" in service
    assert "-m app.cover_watch" in service
    assert "--poll-seconds 60" in service
    assert "Restart=always" in service
    assert "WantedBy=multi-user.target" in service
    # De timer blijft als extra systemd vangnet bestaan, maar is niet meer de
    # uitvoeringscadans van de coverworker zelf.
    assert "top40-archiver-cover-art.service" in timer


def test_dashboard_hides_cover_progress_after_catchup_but_keeps_worker_running():
    state = Path("app/cover_art_state.py").read_text(encoding="utf-8")
    live = Path("app/static/live.js").read_text(encoding="utf-8")
    assert '"visible": bool(remaining > 0 or actively_catching_up)' in state
    assert '"found": found' in state
    assert '"remaining": remaining' in state
    assert "panel.hidden = !covers.visible" in live
    assert "Hoezen gevonden" in live
    assert "blijft daarna nieuwe nummers automatisch volgen" in live


def test_safe_action_starts_long_cover_worker_non_blocking():
    source = Path("scripts/top40-safe-action").read_text(encoding="utf-8")
    assert '"run_cover_art": ["systemctl", "start", "--no-block", "top40-archiver-cover-art.service"]' in source
    assert '"restart_cover_art": ["systemctl", "restart", "--no-block", "top40-archiver-cover-art.service"]' in source
