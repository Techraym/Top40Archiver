from pathlib import Path

from app import cover_art


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


def test_cover_systemd_unit_uses_drain_mode_without_timeout():
    service = Path("systemd/top40-archiver-cover-art.service").read_text(encoding="utf-8")
    timer = Path("systemd/top40-archiver-cover-art.timer").read_text(encoding="utf-8")
    assert "--drain" in service
    assert "TimeoutStartSec=infinity" in service
    assert "Restart=on-failure" in service
    assert "OnUnitInactiveSec=30min" in timer


def test_safe_action_starts_long_cover_worker_non_blocking():
    source = Path("scripts/top40-safe-action").read_text(encoding="utf-8")
    assert '"run_cover_art": ["systemctl", "start", "--no-block", "top40-archiver-cover-art.service"]' in source
    assert '"restart_cover_art": ["systemctl", "restart", "--no-block", "top40-archiver-cover-art.service"]' in source
