from pathlib import Path

import pytest

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


def test_history_timer_restarts_one_minute_after_each_batch():
    timer = (
        Path(__file__).resolve().parents[1]
        / "systemd"
        / "top40-archiver-history.timer"
    ).read_text(encoding="utf-8")

    assert "OnBootSec=2min" in timer
    assert "OnUnitInactiveSec=1min" in timer
    assert "OnUnitActiveSec" not in timer
