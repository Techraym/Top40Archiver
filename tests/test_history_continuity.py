from pathlib import Path

import pytest
from requests import Response
from requests.exceptions import HTTPError

from app import service_history
from app.top40 import parse_chart


def _tipparade_html(count: int, *, start: int = 1) -> str:
    items = []
    for position in range(start, start + count):
        items.append(
            f"""
            <article data-position="{position}">
              <span class="title">Titel {position}</span>
              <span class="artist">Artiest {position}</span>
            </article>
            """
        )
    return "<html><body>" + "".join(items) + "</body></html>"


def test_strict_current_parser_still_requires_complete_positions():
    with pytest.raises(ValueError, match="19 herkenbare noteringen"):
        parse_chart(
            _tipparade_html(19),
            "https://www.top40.nl/tipparade/1969/week-37",
            "tipparade",
        )


def test_history_parser_keeps_every_available_partial_notation():
    chart = parse_chart(
        _tipparade_html(7),
        "https://www.top40.nl/tipparade/1969/week-37",
        "tipparade",
        allow_incomplete=True,
    )

    assert chart.edition_key == "1969-W37"
    assert len(chart.tracks) == 7
    assert chart.warning is not None
    assert "zonder een vast vereist aantal" in chart.warning


def test_history_parser_accepts_more_entries_than_reference_count():
    chart = parse_chart(
        _tipparade_html(24),
        "https://www.top40.nl/tipparade/1969/week-37",
        "tipparade",
        allow_incomplete=True,
    )

    assert len(chart.tracks) == 24
    assert chart.tracks[-1].position == 24
    assert chart.warning is not None


def test_history_parser_preserves_non_contiguous_positions():
    html = (
        _tipparade_html(2, start=1).replace("</body></html>", "")
        + _tipparade_html(1, start=5).replace("<html><body>", "")
    )
    chart = parse_chart(
        html,
        "https://www.top40.nl/tipparade/1969/week-37",
        "tipparade",
        allow_incomplete=True,
    )

    assert [track.position for track in chart.tracks] == [1, 2, 5]


def test_history_parser_rejects_only_a_page_without_any_recognizable_entry():
    with pytest.raises(ValueError, match="Geen herkenbare noteringen"):
        parse_chart(
            "<html><body><p>Geen gegevens aanwezig</p></body></html>",
            "https://www.top40.nl/tipparade/1969/week-37",
            "tipparade",
            allow_incomplete=True,
        )


@pytest.mark.parametrize("status_code", [404, 410])
def test_missing_historical_page_advances_to_next_iso_week(
    monkeypatch,
    status_code: int,
):
    response = Response()
    response.status_code = status_code
    response.url = "https://www.top40.nl/top40/1970/week-53"
    error = HTTPError(
        f"{status_code} Client Error",
        response=response,
    )

    def missing_page(*args, **kwargs):
        raise error

    updates: list[dict[str, object]] = []
    monkeypatch.setattr(
        service_history,
        "fetch_chart_from_website",
        missing_page,
    )
    monkeypatch.setattr(
        service_history,
        "set_settings",
        lambda values: updates.append(dict(values)),
    )

    result = service_history._run_chart_history(
        "top40",
        {
            "history_status": "running",
            "history_next_year": "1970",
            "history_next_week": "53",
            "history_last_edition": "1970-W52",
        },
        current_pair=(1971, 1),
        batch=1,
        delay=0,
    )

    assert result["skipped"] == ["1970-W53"]
    assert result["next"] == "1971-W01"
    assert result["completed"] is False
    assert f"HTTP {status_code}" in result["warnings"][0]

    cursor_update = updates[-1]
    assert cursor_update["history_next_year"] == 1971
    assert cursor_update["history_next_week"] == 1
    assert cursor_update["history_status"] == "running"
    assert cursor_update["history_last_error"] == ""
    assert "history_last_edition" not in cursor_update


def test_history_timer_restarts_one_minute_after_each_batch():
    timer = (
        Path(__file__).resolve().parents[1]
        / "systemd"
        / "top40-archiver-history.timer"
    ).read_text(encoding="utf-8")

    assert "OnBootSec=2min" in timer
    assert "OnUnitInactiveSec=1min" in timer
    assert "OnUnitActiveSec" not in timer
