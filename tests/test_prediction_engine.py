from app import prediction_engine


def test_prediction_risk_increases_with_workers_and_failures(monkeypatch):
    monkeypatch.setattr(prediction_engine, "latest_health", lambda: {
        "worker_count": 4,
        "queue_failed": 20,
        "queue_pending": 100,
        "disk_percent": 80,
        "cpu_percent": 40,
        "memory_percent": 45,
        "database_latency_ms": 20,
        "score": 75,
    })
    monkeypatch.setattr(prediction_engine, "health_trends", lambda _range: {
        "raw_sample_count": 20,
        "summary": {"failed_change": 5, "score_direction": "down"},
    })
    result = prediction_engine.build_predictions("24h")
    youtube = next(item for item in result["risks"] if item["key"] == "youtube")
    assert youtube["risk"] >= 70
    assert result["confidence"] == 0.82
    assert result["queue_hours"] > 0


def test_prediction_stays_low_for_stable_system(monkeypatch):
    monkeypatch.setattr(prediction_engine, "latest_health", lambda: {
        "worker_count": 1,
        "queue_failed": 0,
        "queue_pending": 0,
        "disk_percent": 40,
        "cpu_percent": 20,
        "memory_percent": 35,
        "database_latency_ms": 10,
        "score": 100,
    })
    monkeypatch.setattr(prediction_engine, "health_trends", lambda _range: {
        "raw_sample_count": 30,
        "summary": {"failed_change": 0, "score_direction": "stable"},
    })
    result = prediction_engine.build_predictions("24h")
    assert result["headline"] == "Geen direct operationeel risico"
    assert max(item["risk"] for item in result["risks"]) < 40
