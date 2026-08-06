from pathlib import Path


def test_version_and_installer_assets():
    assert Path('VERSION').read_text().strip() == '1.15.4'
    assert Path('scripts/install-1.15.4.sh').exists()
    assert Path('systemd/top40-ai-diagnostics.service').exists()
    assert Path('systemd/top40-ai-diagnostics.timer').exists()


def test_quality_engine_is_read_only():
    text = Path('app/quality_diagnostics.py').read_text()
    assert 'mode=ro' in text
    assert 'DELETE FROM' not in text.upper()
    assert 'DROP TABLE' not in text.upper()


def test_sidecar_exposes_diagnostics_routes():
    text = Path('app/ai_sidecar.py').read_text()
    for route in ('/api/status','/api/quality-check','/api/diagnostics','/healthz'):
        assert route in text
