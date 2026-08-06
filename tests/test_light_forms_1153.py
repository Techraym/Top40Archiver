from pathlib import Path


def test_main_stylesheet_uses_light_form_controls():
    css = Path('app/static/style.css').read_text(encoding='utf-8')
    assert 'color-scheme:light' in css.replace(' ', '')
    assert 'input,select,textarea' in css.replace('\n', '')
    assert 'background:#fff!important' in css.replace(' ', '')
    assert 'color:var(--text)!important' in css.replace(' ', '')
