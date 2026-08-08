import inspect

from app import ai_recovery


def _item(**overrides):
    base = {
        "id": 7,
        "artist": "INXS",
        "title": "Never Tear Us Apart",
        "category": "other",
        "error_message": "provider failure",
        "job_status": "failed",
    }
    base.update(overrides)
    return base


class _Con:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, *args, **kwargs):
        return None


def test_recovery_requeues_download_job_without_restarting_manager(monkeypatch):
    calls = []
    monkeypatch.setattr(ai_recovery, "retry_job", lambda track_id: calls.append(track_id) or True)
    monkeypatch.setattr(ai_recovery, "connect", lambda: _Con())

    released, details = ai_recovery._release_selected([_item()], {"track_recoveries": {}})

    assert released == 1
    assert calls == [7]
    assert details[0]["download_job_requeued"] is True
    assert details[0]["manager_restart_requested"] is False
    assert "restart_download" not in inspect.getsource(ai_recovery.run_cycle)


def test_transient_waiting_retry_is_left_to_download_manager_backoff():
    source = inspect.getsource(ai_recovery.run_cycle)
    assert 'item.get("job_status") == "waiting_retry"' in source
    assert "manager_backoff" in source
    assert "download_manager_restart_requested" in source
