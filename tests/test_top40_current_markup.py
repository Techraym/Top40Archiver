from app.top40 import parse_chart


def _chart_html(count: int, year: int, week: int) -> str:
    items = []
    for position in range(1, count + 1):
        track_id = 44000 + position
        items.append(
            f"""
            <div class="top40-list__item">
              <div class="top40-list__item__info__position">{position}</div>
              <a href="/artist-{position}/title-{track_id}"></a>
              <a href="https://www.top40.nl/artist-{position}/title-{track_id}">
                Titel {position}
              </a>
              <a href="https://www.top40.nl/artist-{position}/title-{track_id}">
                Artiest {position}
              </a>
            </div>
            """
        )
    return (
        f"<html><head><title>Tipparade-lijst van week {week}, {year}</title></head>"
        f"<body>{''.join(items)}</body></html>"
    )


def test_current_tipparade_markup_uses_detail_links():
    chart = parse_chart(
        _chart_html(30, 2026, 31),
        "https://www.top40.nl/tipparade/2026/week-31",
        "tipparade",
    )

    assert chart.edition_key == "2026-W31"
    assert len(chart.tracks) == 30
    assert chart.tracks[0].position == 1
    assert chart.tracks[0].title == "Titel 1"
    assert chart.tracks[0].artist == "Artiest 1"
    assert chart.tracks[0].source_track_id == "44001"


def test_historical_year_and_twenty_item_tipparade():
    chart = parse_chart(
        _chart_html(20, 1967, 28),
        "https://www.top40.nl/tipparade/1967/week-28",
        "tipparade",
    )

    assert chart.edition_key == "1967-W28"
    assert len(chart.tracks) == 20
    assert chart.tracks[-1].position == 20
    assert chart.tracks[-1].title == "Titel 20"
    assert chart.tracks[-1].artist == "Artiest 20"
