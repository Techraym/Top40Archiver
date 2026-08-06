from pathlib import Path


def test_sidecar_uses_port_8041_and_does_not_patch_dashboard():
    service = Path('systemd/top40-archiver-ai.service').read_text(encoding='utf-8')
    installer = Path('scripts/install-ai-sidecar-1.15.0-alpha.4.sh').read_text(encoding='utf-8')
    assert '--port 8041' in service
    assert 'top40archiver' in service
    assert 'app/templates/index.html' not in installer
    assert 'app/static/style.css' not in installer
    assert 'cover-art' not in installer
