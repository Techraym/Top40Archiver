from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _compact_css() -> str:
    css = (ROOT / "app" / "static" / "style.css").read_text(encoding="utf-8")
    return "".join(css.split())


def test_mobile_dashboard_prevents_horizontal_page_overflow():
    css = _compact_css()

    assert "html{min-width:0;overflow-x:hidden" in css
    assert "body{margin:0;overflow-x:hidden" in css
    assert "overflow-wrap:anywhere" in css


def test_mobile_dashboard_uses_compact_cards_and_full_width_controls():
    css = _compact_css()

    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in css
    assert "#history-controls{display:grid" in css
    assert ".header-actionsform,.header-actionsbutton{width:100%}" in css
    assert "env(safe-area-inset-bottom)" in css
    assert "@media(max-width:390px)" in css
