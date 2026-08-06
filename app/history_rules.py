from __future__ import annotations

from typing import Any

# Historische bronpagina's waarvan bekend is dat ze niet bestaan en daarom nooit
# meer via HTTP mogen worden opgevraagd. De volgende cursor is expliciet vastgelegd
# zodat een ontbrekende ISO-week de volledige archiefopbouw niet kan blokkeren.
BLACKLISTED_HISTORICAL_EDITIONS: dict[tuple[str, int, int], dict[str, Any]] = {
    ("top40", 1970, 53): {
        "source_url": "https://www.top40.nl/top40/1970/week-53",
        "next_year": 1971,
        "next_week": 1,
        "reason": "Top40.nl heeft geen historische pagina voor deze editie.",
    }
}


def get_blacklisted_history_rule(
    chart_type: str,
    year: int,
    week: int,
) -> dict[str, Any] | None:
    return BLACKLISTED_HISTORICAL_EDITIONS.get(
        (str(chart_type).strip().casefold(), int(year), int(week))
    )


def blacklisted_history_url(value: object) -> dict[str, Any] | None:
    candidate = str(value or "").strip().rstrip("/").casefold()
    if not candidate:
        return None

    for rule in BLACKLISTED_HISTORICAL_EDITIONS.values():
        if candidate == str(rule["source_url"]).rstrip("/").casefold():
            return rule
    return None
