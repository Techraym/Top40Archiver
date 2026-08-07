from datetime import datetime, timedelta, timezone

from app import ai_memory
from app.ai_learning import (
    autonomy_report,
    choose_action,
    ingest_cycle_reports,
    record_action,
)


def _memory(tmp_path, monkeypatch):
    path = tmp_path / "ai_memory.sqlite"
    monkeypatch.setattr(ai_memory, "AI_MEMORY_PATH", path)
    return path


def test_every_completed_action_updates_learning(tmp_path, monkeypatch):
    _memory(tmp_path, monkeypatch)
    action_id = record_action(
        cycle_id="cycle-test",
        domain="service",
        problem_key="service:web",
        action="restart_web",
        reason="web was down",
        success=True,
        before={"health": "critical"},
        after={"health": "healthy"},
        effect_score=1.0,
    )
    assert action_id > 0

    with ai_memory.connect() as conn:
        execution = conn.execute("SELECT * FROM action_execution WHERE id=?", (action_id,)).fetchone()
        learned = conn.execute(
            "SELECT * FROM action_learning WHERE problem_key='service:web' AND action='restart_web'"
        ).fetchone()
    assert execution["status"] == "completed"
    assert execution["success"] == 1
    assert learned["evidence_count"] == 1
    assert learned["success_rate"] == 1.0


def test_first_result_immediately_changes_next_strategy_choice(tmp_path, monkeypatch):
    _memory(tmp_path, monkeypatch)
    candidates = ["canonical_search", "audio_fallback"]
    record_action(
        cycle_id="first-result",
        domain="download_track",
        problem_key="download:no_search_results",
        action="audio_fallback",
        reason="first verified result",
        success=True,
        subject="track:1",
        effect_score=1.0,
    )
    # Geen tweemaal-uitproberen of kalenderwachttijd: één geverifieerd resultaat
    # is al bewijs voor de eerstvolgende keuze.
    assert choose_action("download:no_search_results", candidates, 0) == "audio_fallback"


def test_strategy_selection_prefers_verified_winner_after_more_evidence(tmp_path, monkeypatch):
    _memory(tmp_path, monkeypatch)
    candidates = ["canonical_search", "simplified_artist", "title_first", "audio_fallback"]
    for name in candidates:
        for n in range(2):
            success = name == "audio_fallback"
            record_action(
                cycle_id=f"cycle-{name}-{n}",
                domain="download_track",
                problem_key="download:no_search_results",
                action=name,
                reason="strategy test",
                success=success,
                subject=f"track:{name}:{n}",
                effect_score=1.0 if success else 0.0,
            )
    assert choose_action("download:no_search_results", candidates, 99) == "audio_fallback"


def test_cycle_ingest_records_service_operations_and_download_actions(tmp_path, monkeypatch):
    _memory(tmp_path, monkeypatch)
    service_report = {
        "actions": [{"unit": "top40-archiver-web.service", "action": "restart_web", "ok": True, "result": "gelukt"}],
        "services_before": [{"unit": "top40-archiver-web.service", "health": "critical"}],
        "services_after": [{"unit": "top40-archiver-web.service", "health": "healthy"}],
    }
    operations_report = {
        "actions": [{"action": "restart_ollama", "ok": True, "reason": "http down"}],
        "before": {"ollama": {"reachable": False}},
        "after": {"ollama": {"reachable": True}, "covers": {}, "database": {"health": "ok"}},
    }
    recovery_report = {
        "failure_count": 1,
        "categories": {"no_search_results": 1},
        "decision": {"reason": "retry"},
        "verification": {"pending_after": 1},
        "actions": [{
            "action": "retry_failed_downloads",
            "result": "gelukt",
            "restart": {"ok": True},
            "repairs": [{
                "id": 42,
                "artist": "Artist",
                "title": "Title",
                "category": "no_search_results",
                "strategy": "canonical_search",
                "query": None,
                "recovery_number": 1,
            }],
        }],
    }
    result = ingest_cycle_reports("cycle-ingest", service_report, operations_report, recovery_report)
    assert result["ingested"] == 3
    assert result["pending_track_actions"] == 1
    with ai_memory.connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM action_execution WHERE cycle_id='cycle-ingest'").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM action_execution WHERE cycle_id='cycle-ingest' AND status='pending'").fetchone()[0]
    assert total == 4
    assert pending == 1


def test_readiness_is_evidence_driven_not_calendar_driven(tmp_path, monkeypatch):
    _memory(tmp_path, monkeypatch)
    # Vijf patronen, ieder vijf succesvolle acties: voldoende operationeel bewijs
    # terwijl alle acties minuten oud zijn. Readiness mag dus niet zeven dagen wachten.
    for problem in range(5):
        for n in range(5):
            record_action(
                cycle_id=f"recent-{problem}-{n}",
                domain="service",
                problem_key=f"service:test-{problem}",
                action=f"repair-{problem}",
                reason="continuous evidence",
                success=True,
                effect_score=1.0,
            )
    report = autonomy_report(7)
    assert report["trend_window_days"] == 7
    assert report["learning_mode"] == "continuous-online-from-action-1"
    assert report["days_observed"] < 7
    assert report["actions"]["total"] >= 25
    assert report["ready_to_replace_manual_checks"] is True


def test_schema_can_represent_old_successful_learning_history(tmp_path, monkeypatch):
    _memory(tmp_path, monkeypatch)
    old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    with ai_memory.connect() as conn:
        conn.execute(
            """
            INSERT INTO action_execution(
              cycle_id,domain,problem_key,action,reason,status,before_json,after_json,result_json,
              success,effect_score,operator_needed,reversible,started_at,completed_at
            ) VALUES('old','service','service:web','restart_web','old event','completed','{}','{}','{}',1,1,0,1,?,?)
            """,
            (old, old),
        )
    report = autonomy_report(7)
    assert report["days_observed"] >= 7
