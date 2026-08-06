from app import prediction_engine


def test_prediction_risk_increases_with_workers(monkeypatch):
    monkeypatch.setattr(prediction_engine, 'latest_health', lambda: {
        'worker_count': 4, 'queue_failed': 5, 'queue_pending': 100,
        'disk_percent': 50, 'cpu_percent': 20, 'memory_percent': 30,
        'database_latency_ms': 10, 'score': 80,
    })
    monkeypatch.setattr(prediction_engine, 'health_trends', lambda _range: {
        'raw_sample_count': 20,
        'summary': {'failed_change': 2, 'score_direction': 'down'},
    })
    result = prediction_engine.build_predictions('24h')
    youtube = next(item for item in result['risks'] if item['key'] == 'youtube')
    assert youtube['risk'] >= 70
    assert result['confidence'] == 0.82


def test_prediction_is_calm_for_one_worker(monkeypatch):
    monkeypatch.setattr(prediction_engine, 'latest_health', lambda: {
        'worker_count': 1, 'queue_failed': 0, 'queue_pending': 0,
        'disk_percent': 40, 'cpu_percent': 10, 'memory_percent': 20,
        'database_latency_ms': 5, 'score': 98,
    })
    monkeypatch.setattr(prediction_engine, 'health_trends', lambda _range: {
        'raw_sample_count': 2,
        'summary': {'failed_change': 0, 'score_direction': 'stable'},
    })
    result = prediction_engine.build_predictions('24h')
    assert result['headline'] == 'Geen direct operationeel risico'
    assert result['queue_hours'] == 0.0
