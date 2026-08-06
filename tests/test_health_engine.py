from app.health_engine import DEFAULT_THRESHOLDS, _score_and_diagnosis


def base_metrics():
    return {
        "cpu_percent": 20.0,
        "memory_percent": 40.0,
        "disk_percent": 50.0,
        "database_ok": True,
        "database_latency_ms": 10.0,
        "internet_ok": True,
        "queue_pending": 12,
        "queue_failed": 0,
        "worker_count": 1,
        "downloads_paused": False,
    }


def test_healthy_system_scores_good():
    score, status, diagnosis = _score_and_diagnosis(base_metrics(), DEFAULT_THRESHOLDS)
    assert score == 100
    assert status == "good"
    assert "binnen de ingestelde grenzen" in diagnosis


def test_critical_storage_lowers_health():
    metrics = base_metrics()
    metrics["disk_percent"] = 98.0
    score, status, diagnosis = _score_and_diagnosis(metrics, DEFAULT_THRESHOLDS)
    assert score == 70
    assert status == "attention"
    assert "opslag bijna vol" in diagnosis


def test_multiple_failures_become_critical():
    metrics = base_metrics()
    metrics.update(
        {
            "disk_percent": 99.0,
            "database_ok": False,
            "internet_ok": False,
            "queue_failed": 50,
            "worker_count": 4,
        }
    )
    score, status, diagnosis = _score_and_diagnosis(metrics, DEFAULT_THRESHOLDS)
    assert score == 0
    assert status == "critical"
    assert "SQLite-controle mislukt" in diagnosis
    assert "hoge workerparalleliteit" in diagnosis
