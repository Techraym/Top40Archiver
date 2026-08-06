from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_log_reader_rejects_unknown_service(monkeypatch):
    from app.log_reader_service import app
    client = TestClient(app)
    response = client.get('/api/logs/service/not-allowed')
    assert response.status_code == 404


def test_log_reader_health_has_whitelist():
    from app.log_reader_service import app
    client = TestClient(app)
    response = client.get('/healthz')
    assert response.status_code == 200
    assert 'web' in response.json()['allowed']


def test_ai_memory_schema(tmp_path, monkeypatch):
    import app.ai_memory as memory
    monkeypatch.setattr(memory, 'AI_MEMORY_PATH', tmp_path / 'ai_memory.sqlite')
    memory.remember_event('test', 'regressietest', 'ai', {'ok': True})
    items = memory.timeline()
    assert items[0]['message'] == 'regressietest'
    assert items[0]['metadata']['ok'] is True


def test_health_score_range(monkeypatch):
    import app.operations_center as operations
    monkeypatch.setattr(operations, 'service_monitor', lambda: [])
    monkeypatch.setattr(operations, 'database_dashboard', lambda: {'health': 'ok'})
    monkeypatch.setattr(operations, 'download_dashboard', lambda: {'youtube_errors': 0})
    result = operations.health_score()
    assert 0 <= result['score'] <= 100


def test_safe_action_has_no_shell_or_destructive_commands():
    source = Path('scripts/top40-safe-action').read_text()
    assert 'shell=True' not in source
    assert 'rm ' not in source
    assert 'git ' not in source
    assert 'sudo ' not in source
