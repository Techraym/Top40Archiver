from app.service_common import (
    _next_week,
    _normalize_week_cursor,
    iso_weeks_in_year,
)
from app.service_history import (
    SKIPPABLE_HISTORICAL_HTTP_STATUSES,
    _http_status_from_exception,
)


def test_iso_calendar_knows_52_and_53_week_years():
    assert iso_weeks_in_year(2020) == 53
    assert iso_weeks_in_year(2021) == 52
    assert iso_weeks_in_year(1970) == 53


def test_next_week_uses_iso_year_boundary():
    assert _next_week(2020, 53) == (2021, 1)
    assert _next_week(2021, 52) == (2022, 1)
    assert _next_week(1970, 53) == (1971, 1)


def test_invalid_stored_week_is_normalized_without_loop():
    assert _normalize_week_cursor(2021, 53) == (2022, 1)
    assert _normalize_week_cursor(2020, 54) == (2021, 1)


def test_402_404_and_410_are_skipped_for_history():
    assert SKIPPABLE_HISTORICAL_HTTP_STATUSES == {402, 404, 410}
    for status in (402, 404, 410):
        exc = RuntimeError(
            f"{status} Client Error for url: "
            "https://www.top40.nl/top40/1970/week-53"
        )
        assert _http_status_from_exception(exc) == status


def test_unrelated_server_error_is_not_skipped():
    assert _http_status_from_exception(RuntimeError("503 Service Unavailable")) is None
