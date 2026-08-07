from pathlib import Path

import pytest

from app import ai_code_repair, ai_control_room

ROOT = Path(__file__).resolve().parents[1]


def test_fallback_control_room_contains_every_required_section_and_safe_runtime():
    html = ai_control_room._fallback_html()
    validation = ai_control_room.validate_control_room_html(html)
    assert validation["ok"] is True
    assert validation["structural_score"] >= 90
    for section in ai_control_room.REQUIRED_SECTION_IDS:
        assert f"id='{section}'" in html or f'id="{section}"' in html

    response = ai_control_room.control_room_response()
    body = response.body.decode("utf-8")
    assert "/api/ai/control-room?limit=250" in body
    assert "/api/ai/control-room/telemetry" in body
    assert "setInterval(load,5000)" in body
    assert response.headers["x-frame-options"] == "DENY"
    assert "form-action 'none'" in response.headers["content-security-policy"]


def test_local_ai_html_contract_rejects_scripts_external_urls_and_event_handlers():
    base = ai_control_room._fallback_html()
    assert ai_control_room.validate_control_room_html(base)["ok"] is True

    for injected in (
        "<script>alert(1)</script>",
        "<img src='https://example.com/a.png'>",
        "<button onclick='danger()'>x</button>",
        "<iframe src='/development'></iframe>",
    ):
        bad = base.replace("</body>", injected + "</body>")
        result = ai_control_room.validate_control_room_html(bad)
        assert result["ok"] is False
        assert result["forbidden_markers"]


def test_local_ai_html_contract_rejects_missing_observability_section():
    html = ai_control_room._fallback_html().replace("id='cr-code'", "id='removed-code-section'")
    result = ai_control_room.validate_control_room_html(html)
    assert result["ok"] is False
    assert "cr-code" in result["missing_sections"]


def test_control_room_routes_and_ai_platform_contract_are_release_managed():
    sidecar = (ROOT / "app/ai_sidecar.py").read_text(encoding="utf-8")
    platform = (ROOT / "app/ai_platform.py").read_text(encoding="utf-8")
    recovery = (ROOT / "app/ai_recovery_entry.py").read_text(encoding="utf-8")
    memory = (ROOT / "app/ai_memory.py").read_text(encoding="utf-8")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

    assert version and version.count(".") == 2
    assert "VERSION = _release_version()" in sidecar
    assert "control_room_response()" in sidecar
    assert "app.include_router(control_room_router)" in sidecar
    assert "VERSION = _release_version()" in platform
    assert '"local_ai_owned_control_room_html_css": True' in platform
    assert '"control_room_safe_runtime": True' in platform
    assert '"control_room_browser_telemetry": True' in platform
    assert '"control_room_continuous_ui_learning": True' in platform
    assert '"ai_session_console": True' in platform
    assert '"multi_source_download_engine": True' in platform
    assert "run_ui_designer(cycle_id)" in recovery
    assert "control_room_ui" in recovery
    assert "CREATE TABLE IF NOT EXISTS ui_revision" in memory
    assert "CREATE TABLE IF NOT EXISTS ui_telemetry" in memory
    assert "CREATE TABLE IF NOT EXISTS ai_session_event" in memory
    assert "CREATE TABLE IF NOT EXISTS operator_guidance" in memory


def test_control_room_policy_code_cannot_be_self_rewritten_by_code_repair():
    for blocked in (
        "app/ai_control_room.py",
        "app/ai_ui_designer.py",
        "app/ai_session_console.py",
        "app/ai_platform.py",
        "app/ai_sidecar.py",
        "app/ai_recovery_entry.py",
        "app/ai_learning_api.py",
    ):
        assert blocked in ai_code_repair.BLOCKED_PRODUCTION_FILES
        with pytest.raises(ValueError):
            ai_code_repair._safe_touched_files({"proposal": {"files": [blocked]}})


def test_ai_ui_designer_is_declarative_html_css_only():
    designer = (ROOT / "app/ai_ui_designer.py").read_text(encoding="utf-8")
    assert "Jij bezit de HTML en CSS van de hoofdpagina op poort 8041" in designer
    assert "GEEN JavaScript" in designer
    assert "REQUIRED_SECTION_IDS" in designer
    assert "promoted_ui_canary" in designer
    assert "ai_ui_rollback" in designer
    assert "ui:control_room" in designer
    assert "browsertelemetrie" in designer
