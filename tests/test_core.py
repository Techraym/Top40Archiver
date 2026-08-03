from app.normalize import normalize, safe_filename

def test_normalize():
    assert normalize('Beyoncé & JAY-Z') == 'beyonce and jay z'

def test_filename():
    assert safe_filename('A/B: C?') == 'A_B_ C_'
