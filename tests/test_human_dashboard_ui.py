from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_loads_current_uncached_assets_and_human_copy():
    template = (ROOT / "app" / "templates" / "index.html").read_text(
        encoding="utf-8"
    )

    assert "/static/style.css?v=32" in template
    assert "/static/live.js?v=32" in template
    assert "Een lokaal muziekarchief" in template
    assert "Mislukte downloads opnieuw proberen" in template
    assert "Niet online beschikbaar" in template
    assert "AI-herstel bekijken" in template


def test_dashboard_uses_flat_editorial_layout_and_mobile_rules():
    css = (ROOT / "app" / "static" / "style.css").read_text(encoding="utf-8")

    assert 'Georgia, "Times New Roman", serif' in css
    assert ".metric-grid" in css
    assert "border-top: 1px solid var(--line)" in css
    assert "@media (max-width: 760px)" in css
    assert "overflow-x: hidden" in css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in css
