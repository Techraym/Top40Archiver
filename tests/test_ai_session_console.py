from pathlib import Path

from app import ai_memory
from app import ai_session_console as session


def test_ai_session_guidance_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_memory, "AI_MEMORY_PATH", tmp_path / "ai_memory.sqlite")

    item = session.create_operator_guidance(
        "Pas de code niet verder aan totdat ik dit heb gecontroleerd.",
        scope="code",
        mode="hold",
    )
    assert item["status"] == "active"
    assert session.scope_held("code") is True
    assert "HARD HOLD" in session.operator_context("code")
    assert "Pas de code niet verder aan" in session.operator_context("code")

    event_id = session.log_session_event(
        event_type="working",
        title="Testactie",
        message="Ik controleer de huidige toestand.",
        cycle_id="cycle-test",
        domain="code",
    )
    events = session.list_session_events(after_id=0, limit=20)
    assert any(x["id"] == event_id and x["message"] == "Ik controleer de huidige toestand." for x in events)
    assert any(x["role"] == "operator" for x in events)

    closed = session.close_guidance(item["id"])
    assert closed["status"] == "closed"
    assert session.scope_held("code") is False


def test_session_console_is_fixed_human_monitoring_surface():
    source = Path("app/ai_session_console.py").read_text(encoding="utf-8")
    assert '/ai-session' in source
    assert '/api/ai/session/events' in source
    assert '/api/ai/session/guidance' in source
    assert 'raw_chain_of_thought_exposed' in source
    assert 'decision_summaries_exposed' in source
    assert 'Geen input nodig voor autonoom werk.' in source
    assert 'Pauzeer domein' in source
    assert 'Qwen AI Session' in source


def test_recovery_cycle_streams_work_and_respects_operator_holds():
    source = Path("app/ai_recovery_entry.py").read_text(encoding="utf-8")
    assert 'log_session_event' in source
    assert 'cycle_start' in source
    assert 'cycle_complete' in source
    assert 'scope_held("code")' in source
    assert 'scope_held("ui")' in source
    assert 'skipped_operator_hold' in source
    assert 'Bestaande canaries worden altijd geverifieerd' in source
    assert 'report_preview' in source
    assert 'preview_limit = 12_000' in source
    assert '"report": report' not in source


def test_all_exposed_operator_holds_have_real_mutation_guards():
    downloads = Path("app/ai_recovery.py").read_text(encoding="utf-8")
    services = Path("app/service_recovery.py").read_text(encoding="utf-8")
    storage = Path("app/ai_storage_recovery.py").read_text(encoding="utf-8")
    charts = Path("app/chart_freshness.py").read_text(encoding="utf-8")
    operations = Path("app/ai_operations_worker.py").read_text(encoding="utf-8")
    manager = Path("app/download_manager.py").read_text(encoding="utf-8")
    recovery_entry = Path("app/ai_recovery_entry.py").read_text(encoding="utf-8")

    assert 'scope_held("downloads")' in downloads
    assert '"status": "operator_hold"' in downloads
    assert 'scope_held("downloads")' in manager
    assert 'scope_held("services")' in services
    assert 'scope_held("storage")' in storage
    assert 'scope_held("charts")' in charts
    assert 'scope_held("operations")' in operations
    assert 'scope_held("covers")' in operations
    assert 'scope_held("code")' in recovery_entry
    assert 'scope_held("ui")' in recovery_entry


def test_qwen_prompts_receive_operator_guidance():
    operations = Path("app/ai_operations_worker.py").read_text(encoding="utf-8")
    repair = Path("app/ai_code_repair.py").read_text(encoding="utf-8")
    improvement = Path("app/ai_code_improvement.py").read_text(encoding="utf-8")
    services = Path("app/service_recovery.py").read_text(encoding="utf-8")
    provider_ai = Path("app/provider_ai.py").read_text(encoding="utf-8")
    assert 'operator_context("operations")' in operations
    assert 'operator_context("code")' in repair
    assert 'operator_context("code")' in improvement
    assert 'operator_context("services")' in services
    assert 'operator_context("downloads")' in provider_ai
    assert '"app/ai_session_console.py"' in repair


def test_platform_advertises_autonomous_session_and_human_override():
    source = Path("app/ai_platform.py").read_text(encoding="utf-8")
    assert "VERSION = _release_version()" in source
    assert Path("VERSION").read_text(encoding="utf-8").strip() == "1.16.8"
    assert '"ai_session_console": True' in source
    assert '"operator_guidance": True' in source
    assert '"operator_domain_hold": True' in source
    assert '"human_approval_per_cycle_required": False' in source
    assert '"raw_chain_of_thought_exposed": False' in source
    assert '"decision_summaries_exposed": True' in source
