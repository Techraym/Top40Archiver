from app.health_trends import _bucket_rows, _summary


def row(index: int, *, score: int = 90, failed: int = 0):
    return {
        "captured_at": f"2026-08-06T20:{index:02d}:00+02:00",
        "score": score,
        "status": "good",
        "cpu_percent": 20.0 + index,
        "memory_percent": 40.0,
        "disk_percent": 50.0,
        "database_latency_ms": 10.0,
        "database_ok": 1,
        "internet_ok": 1,
        "queue_pending": index,
        "queue_downloading": 0,
        "queue_failed": failed,
        "worker_count": 1,
        "downloads_paused": 0,
    }


def test_summary_detects_declining_health_and_failures():
    rows = [row(0, score=95, failed=1), row(1, score=88, failed=3)]
    summary = _summary(rows)
    assert summary["score_direction"] == "down"
    assert summary["failed_change"] == 2
    assert summary["availability_percent"] == 100.0
    assert "daalt" in summary["diagnosis"]


def test_bucket_rows_respects_maximum_points():
    rows = [row(index) for index in range(12)]
    bucketed = _bucket_rows(rows, 4)
    assert len(bucketed) == 4
    assert bucketed[-1]["captured_at"] == rows[-1]["captured_at"]


def test_empty_summary_is_safe():
    summary = _summary([])
    assert summary["sample_count"] == 0
    assert summary["score_direction"] == "stable"
