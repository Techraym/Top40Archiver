from pathlib import Path

import pytest
from fastapi import HTTPException

from app import ai_code_repair, ai_log_control, ai_ui_admin, ai_ui_policy

ROOT = Path(__file__).resolve().parents[1]


def test_only_three_top_level_page_slots_exist_and_8040_is_human_owned():
    policy = ai_ui_policy.page_policy()
    assert policy["max_top_level_pages"] == 3
    assert policy["ports"] == [8040, 8041, 8042]
    assert policy["human_owned_immutable"] == [8040]
    assert policy["ai_mutable"] == [8041, 8042]
    assert set(policy["ai_page_slots"]) == {8041, 8042}
    assert policy["ai_can_create_extra_top_level_pages"] is False
    assert policy["ai_can_modify_its_ui_policy"] is False
    assert policy["trusted_ui_runtime_ai_mutable"] is False


def test_8040_rendering_sources_are_hard_blocked_for_qwen_code_promotion():
    for path in (
        "app/main.py",
        "app/dashboard.py",
        "app/static/live.js",
        "app/templates/index.html",
    ):
        assert ai_ui_policy.is_8040_protected_path(path)
        with pytest.raises(ValueError, match="8040"):
            ai_ui_policy.assert_ai_source_mutation_allowed(path)


def test_ai_cannot_modify_the_guard_or_human_override_mechanism_itself():
    expected = {
        "app/ai_ui_policy.py",
        "app/ai_ui_admin.py",
        "app/ai_ui_operator_overlay.py",
        "app/ai_log_control.py",
        "app/ai_log_ui_designer.py",
        "app/ai_control_room.py",
        "app/ai_sidecar.py",
        "app/log_reader_service.py",
    }
    assert expected.issubset(ai_ui_policy.AI_UI_POLICY_IMMUTABLE_FILES)
    for path in expected:
        assert ai_ui_policy.is_ai_ui_policy_immutable_path(path)
        with pytest.raises(ValueError, match="beveiligings- of operatorcontrolecode"):
            ai_ui_policy.assert_ai_source_mutation_allowed(path)


def test_code_repair_rejects_main_dashboard_and_ui_policy_files():
    for path in (
        "app/main.py",
        "app/dashboard.py",
        "app/ai_ui_policy.py",
        "app/ai_ui_admin.py",
    ):
        with pytest.raises(ValueError):
            ai_code_repair._safe_touched_files({"proposal": {"files": [path]}})


def test_8042_ai_html_contract_is_html_css_only_and_fixed_sections():
    good = """<!doctype html><html><head><style>body{font-family:sans-serif}</style></head><body>
    <section id='lc-status'></section><section id='lc-errors'></section>
    <section id='lc-live'></section><section id='lc-policy'></section></body></html>"""
    assert ai_log_control.validate_log_control_html(good)["ok"] is True
    assert ai_log_control.validate_log_control_html(good.replace("</body>", "<script>x=1</script></body>"))["ok"] is False
    assert ai_log_control.validate_log_control_html(good.replace("id='lc-live'", "id='other'"))["ok"] is False


def test_operator_rollback_endpoint_explicitly_refuses_8040():
    with pytest.raises(HTTPException) as exc:
        ai_ui_admin.ui_rollback(8040, ai_ui_admin.RollbackIn(reason="test rollback"))
    assert exc.value.status_code == 403


def test_8041_has_non_ai_operator_overlay_and_ui_admin_routes():
    sidecar = (ROOT / "app/ai_sidecar.py").read_text(encoding="utf-8")
    overlay = (ROOT / "app/ai_ui_operator_overlay.py").read_text(encoding="utf-8")
    admin = (ROOT / "app/ai_ui_admin.py").read_text(encoding="utf-8")
    assert "inject_operator_overlay(control_room_response())" in sidecar
    assert "Menselijke controle over Qwen UI" in overlay
    assert "Nieuwe UI-wijzigingen pauzeren" in overlay
    assert "8041 terugrollen" in overlay
    assert "8042 terugrollen" in overlay
    assert '"/api/ai/ui-policy"' in admin
    assert '"/api/ai/ui-guidance"' in admin
    assert '"/api/ai/ui-rollback/{port}"' in admin


def test_qwen_ui_designer_can_only_run_for_8041_and_8042_and_hold_blocks_new_revisions():
    source = (ROOT / "app/ai_ui_designer.py").read_text(encoding="utf-8")
    assert 'model_slot("ui-designer-8041"' in source
    assert 'model_slot("ui-designer-8042"' in source
    assert 'model_slot("ui-designer-8040"' not in source
    assert "MAX_TOP_LEVEL_PAGES" in source
    assert 'held = scope_held("ui")' in source
    assert '"action": "skipped_operator_hold", "port": 8041' in source
    assert '"action": "skipped_operator_hold", "port": 8042' in source
    assert "if control_active" in source
    assert "if log_active" in source


def test_root_logreader_remains_localhost_only_despite_8042_page():
    unit = (ROOT / "systemd/top40-log-reader.service").read_text(encoding="utf-8")
    assert "--host 127.0.0.1 --port 8042" in unit
    assert "User=root" in unit
    assert "ProtectSystem=strict" in unit
