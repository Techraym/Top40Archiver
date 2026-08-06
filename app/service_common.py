from __future__ import annotations

from datetime import date
import re

from .db import connect, now_iso
from .normalize import normalize
from .top40 import ChartEdition, ChartType

CHART_TABLES = {
    "top40": ("editions", "chart_entries"),
    "tipparade": ("tipparade_editions", "tipparade_entries"),
}


def iso_weeks_in_year(year: int) -> int:
    """Return the number of ISO weeks in a calendar year (52 or 53)."""
    year = int(year)
    if year < 1:
        raise ValueError("ISO-jaar moet minimaal 1 zijn")
    return date(year, 12, 28).isocalendar().week


def _normalize_week_cursor(year: int, week: int) -> tuple[int, int]:
    """Normalize a stored cursor with the ISO calendar, across year boundaries."""
    year = int(year)
    week = int(week)
    if year < 1:
        raise ValueError("ISO-jaar moet minimaal 1 zijn")

    while week < 1:
        year -= 1
        if year < 1:
            raise ValueError("Historische weekcursor valt vóór ISO-jaar 1")
        week += iso_weeks_in_year(year)

    while week > iso_weeks_in_year(year):
        week -= iso_weeks_in_year(year)
        year += 1

    return year, week


def _next_week(year: int, week: int) -> tuple[int, int]:
    """Advance exactly one ISO week without ever producing an invalid week."""
    year, week = _normalize_week_cursor(year, week)
    last_week = iso_weeks_in_year(year)
    if week < last_week:
        return year, week + 1
    return year + 1, 1


def _parse_edition_key(value: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"(\d{4})-W(\d{1,2})", str(value or ""))
    if not match:
        return None

    year = int(match.group(1))
    week = int(match.group(2))
    try:
        normalized = _normalize_week_cursor(year, week)
    except ValueError:
        return None
    return normalized if normalized == (year, week) else None


def _chart_fields(chart_type: ChartType) -> dict[str, str]:
    if chart_type == "top40":
        return {
            "seen": "seen_top40",
            "peak": "top40_peak_position",
            "last": "top40_last_position",
        }
    return {
        "seen": "seen_tipparade",
        "peak": "tipparade_peak_position",
        "last": "tipparade_last_position",
    }


def _persist_chart(chart: ChartEdition, force: bool = False) -> dict:
    edition_table, entry_table = CHART_TABLES[chart.chart_type]
    fields = _chart_fields(chart.chart_type)

    with connect() as con:
        existing = con.execute(
            f"SELECT id FROM {edition_table} WHERE edition_key=?",
            (chart.edition_key,),
        ).fetchone()
        if existing and not force:
            return {
                "skipped": True,
                "chart_type": chart.chart_type,
                "edition": chart.edition_key,
                "new_count": 0,
                "new_track_ids": [],
            }
        if existing:
            con.execute(f"DELETE FROM {edition_table} WHERE id=?", (existing["id"],))

        cursor = con.execute(
            f"""
            INSERT INTO {edition_table}(
                edition_key,chart_date,year,week,source_url,checked_at,track_count,status
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                chart.edition_key,
                chart.chart_date,
                chart.year,
                chart.week,
                chart.source_url,
                now_iso(),
                len(chart.tracks),
                "completed",
            ),
        )
        edition_id = cursor.lastrowid
        new_count = 0
        new_track_ids: list[int] = []

        for item in chart.tracks:
            normalized_artist = normalize(item.artist)
            normalized_title = normalize(item.title)
            track = con.execute(
                """
                SELECT * FROM tracks
                WHERE normalized_artist=? AND normalized_title=?
                """,
                (normalized_artist, normalized_title),
            ).fetchone()

            if track is None:
                new_count += 1
                seen_top40 = 1 if chart.chart_type == "top40" else 0
                seen_tipparade = 1 if chart.chart_type == "tipparade" else 0
                top_peak = item.position if chart.chart_type == "top40" else None
                tip_peak = item.position if chart.chart_type == "tipparade" else None
                cursor = con.execute(
                    """
                    INSERT INTO tracks(
                        artist,title,normalized_artist,normalized_title,
                        first_chart_date,first_edition,first_position,first_chart_type,
                        peak_position,last_position,processed_at,download_status,youtube_url,
                        updated_at,seen_top40,seen_tipparade,
                        top40_peak_position,top40_last_position,
                        tipparade_peak_position,tipparade_last_position
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        item.artist,
                        item.title,
                        normalized_artist,
                        normalized_title,
                        chart.chart_date,
                        chart.edition_key,
                        item.position,
                        chart.chart_type,
                        item.position,
                        item.position,
                        now_iso(),
                        "pending",
                        item.youtube_url,
                        now_iso(),
                        seen_top40,
                        seen_tipparade,
                        top_peak,
                        top_peak,
                        tip_peak,
                        tip_peak,
                    ),
                )
                track_id = int(cursor.lastrowid)
                new_track_ids.append(track_id)
                is_new = 1
            else:
                track_id = int(track["id"])
                is_new = 0
                if chart.chart_date < track["first_chart_date"]:
                    con.execute(
                        """
                        UPDATE tracks
                        SET first_chart_date=?,first_edition=?,first_position=?,first_chart_type=?
                        WHERE id=?
                        """,
                        (
                            chart.chart_date,
                            chart.edition_key,
                            item.position,
                            chart.chart_type,
                            track_id,
                        ),
                    )
                con.execute(
                    f"""
                    UPDATE tracks
                    SET peak_position=MIN(peak_position,?),
                        last_position=?,
                        youtube_url=COALESCE(youtube_url,?),
                        {fields['seen']}=1,
                        {fields['peak']}=CASE
                            WHEN {fields['peak']} IS NULL THEN ?
                            ELSE MIN({fields['peak']},?)
                        END,
                        {fields['last']}=?,
                        updated_at=?
                    WHERE id=?
                    """,
                    (
                        item.position,
                        item.position,
                        item.youtube_url,
                        item.position,
                        item.position,
                        item.position,
                        now_iso(),
                        track_id,
                    ),
                )

            con.execute(
                f"INSERT INTO {entry_table}(edition_id,track_id,position,is_new) VALUES(?,?,?,?)",
                (edition_id, track_id, item.position, is_new),
            )

        con.execute(
            f"UPDATE {edition_table} SET new_count=? WHERE id=?",
            (new_count, edition_id),
        )

    return {
        "skipped": False,
        "chart_type": chart.chart_type,
        "edition": chart.edition_key,
        "new_count": new_count,
        "new_track_ids": new_track_ids,
    }
