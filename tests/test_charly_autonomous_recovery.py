from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import charly_download_control as control

ROOT = Path(__file__).resolve().parents[1]


def test_recovery_has_hard_active_budgets():
    assert control.MAX_AI_ROUNDS_PER_CYCLE == 5
    assert control.MAX_NO_PROGRESS_ROUNDS == 3
    assert control.MAX_CYCLE_WALL_SECONDS == 2 * 60 * 60
    assert control.MAX_RECOVERY_SLOTS == 1


def test_cycle_exhausts_on_round_budget():
    state = {"cycle_started_at": datetime.now(timezone.utc).isoformat(),"ai_rounds": control.MAX_AI_ROUNDS_PER_CYCLE,"no_progress_rounds": 0}
    assert control._cycle_exhausted(state)


def test_cycle_exhausts_on_wallclock_budget():
    state = {"cycle_started_at": (datetime.now(timezone.utc)-timedelta(seconds=control.MAX_CYCLE_WALL_SECONDS + 1)).isoformat(),"ai_rounds": 0,"no_progress_rounds": 0}
    assert control._cycle_exhausted(state)


def test_retry_delay_is_adaptive_and_bounded():
    early = control.retry_delay_seconds(attempts=2,queue_class="current",state={"status": "active","last_action": "prepared","ai_rounds": 1,"no_progress_rounds": 0})
    later = control.retry_delay_seconds(attempts=5,queue_class="archive",state={"status": "active","last_action": "duplicate_query","ai_rounds": 4,"no_progress_rounds": 2})
    assert control.MIN_RETRY_SECONDS <= early <= 120
    assert later > early
    assert later <= control.MAX_ACTIVE_RETRY_SECONDS


def test_recovery_qwen_call_is_batch_priority_through_charly_gateway():
    source = (ROOT / "app/charly_download_control.py").read_text(encoding="utf-8")
    assert 'http://127.0.0.1:11434/api/generate' in source
    assert '"charly_priority": "BATCH"' in source
    assert 'priority="background"' in source


def test_recovery_only_changes_search_query_not_match_acceptance():
    source = (ROOT / "app/charly_download_control.py").read_text(encoding="utf-8")
    assert "custom_search_query" in source
    assert "score_candidate(" not in source
    assert "_try_candidate(" not in source


def test_service_starts_control_layer_entrypoint():
    service = (ROOT / "systemd/top40-download-manager.service").read_text(encoding="utf-8")
    assert "-m app.charly_download_manager_entry" in service


def test_background_recovery_slot_is_explicitly_limited():
    source = (ROOT / "app/charly_download_control.py").read_text(encoding="utf-8")
    assert "MAX_RECOVERY_SLOTS = 1" in source
    assert "fresh_current[:wanted]" in source
    assert "recovery[: min(MAX_RECOVERY_SLOTS, remaining)]" in source


def test_parking_is_not_terminal_and_reopens_without_operator_input():
    source = (ROOT / "app/charly_download_control.py").read_text(encoding="utf-8")
    assert 'status="parked"' in source
    assert "_begin_new_cycle" in source
    assert 'last_action="cycle_reopened"' in source
