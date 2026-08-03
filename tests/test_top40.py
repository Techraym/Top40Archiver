from datetime import date

from app.top40 import edition_url, expected_track_count


def test_chart_urls():
    target = date.fromisocalendar(2026, 31, 1)
    assert edition_url("top40", target).endswith("/top40/2026/week-31")
    assert edition_url("tipparade", target).endswith("/tipparade/2026/week-31")


def test_tipparade_changed_from_20_to_30():
    assert expected_track_count("tipparade", date(1968, 1, 1)) == 20
    assert expected_track_count("tipparade", date.fromisocalendar(1969, 38, 1)) == 30
    assert expected_track_count("tipparade", date(1970, 1, 1)) == 30
    assert expected_track_count("top40", date(1965, 1, 2)) == 40
