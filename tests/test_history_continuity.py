from pathlib import Path

import pytest

from app.top40 import parse_chart


def _tipparade_html(count: int) -> str:
    items = []
    for position in range(1, count + 1):
        items.append(
            f"""
            <article data-position="{position}">
              <span class="title">Titel {position}</span>
              <span class="artist">Artiest {position}</span>
            </article>
            """
        )
    return "<html><body>" + "".join(items) + "</body></html>"


def test_strict_parser_rejects_incomplete_historical_tipparade():
    with pytest.raises(ValueError, match="19 herkenbare noteringen"):
        parse_chart(
            _tipparade_html(19),
            "https://www.top40.nl/tipparade/1969/week-37",
            "tipparade",
        )


def test_history_parser_keeps_usable_partial_edition_and_warns():
    chart = parse_chart(
        _tipparade_html(19),
        "https://www.top40.nl/tipparade/1969/week-37",
        "tipparade",
        allow_incomplete=True,
    )

    assert chart.edition_key == "1969-W37"
    assert len(chart.tracks) == 19
    assert chart.warning is not None
    assert "gaat automatisch verder" in chart.warning


def test_history_parser_still_rejects_severely_incomplete_page():
    with pytest.raises(ValueError, match="14 herkenbare noteringen"):
        parse_chart(
            _tipparade_html(14),
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
