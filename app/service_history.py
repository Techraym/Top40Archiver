from __future__ import annotations

from datetime import date
import time

from .db import connect, get_settings, now_iso, set_settings
from .top40 import ChartType, fetch_chart, fetch_chart_from_website
from .service_common import _next_week, _parse_edition_key, _persist_chart


def history_start(reset: bool = False):
    values = {
        "history_enabled": "1",
        "history_status": "running",
        "history_last_error": "",
        "history_completed_at": "",
    }
    if reset:
        with connect() as con:
            settings = get_settings(con)
        values.update(
            {
                "history_next_year": settings["history_start_year"],
                "history_next_week": settings["history_start_week"],
                "history_last_edition": "",
                "tip_history_next_year": settings["tip_history_start_year"],
                "tip_history_next_week": settings["tip_history_start_week"],
                "tip_history_last_edition": "",
                "tip_history_status": "running",
                "tip_history_last_error": "",
                "tip_history_completed_at": "",
            }
        )
    else:
        values["tip_history_status"] = "running"
        values["tip_history_last_error"] = ""
    set_settings(values)
    return run_history_batch()


def history_pause():
    with connect() as con:
        settings = get_settings(con)
    values = {"history_enabled": "0"}
    if settings.get("history_status") != "completed":
        values["history_status"] = "paused"
    if settings.get("tip_history_status") != "completed":
        values["tip_history_status"] = "paused"
    set_settings(values)
    return {"paused": True}


def _known_current_pair(settings: dict, chart_type: ChartType) -> tuple[int, int]:
    key = "last_edition" if chart_type == "top40" else "last_tipparade_edition"
    parsed = _parse_edition_key(settings.get(key, ""))
    if parsed:
        return parsed

    chart = fetch_chart(chart_type=chart_type)
    _persist_chart(chart, False)
    set_settings({key: chart.edition_key})
    return chart.year, chart.week


def _history_keys(chart_type: ChartType) -> dict[str, str]:
    if chart_type == "top40":
        return {
            "next_year": "history_next_year",
            "next_week": "history_next_week",
            "status": "history_status",
            "error": "history_last_error",
            "last": "history_last_edition",
            "completed_at": "history_completed_at",
        }
    return {
        "next_year": "tip_history_next_year",
        "next_week": "tip_history_next_week",
        "status": "tip_history_status",
        "error": "tip_history_last_error",
        "last": "tip_history_last_edition",
        "completed_at": "tip_history_completed_at",
    }


def _run_chart_history(
    chart_type: ChartType,
    settings: dict,
    current_pair: tuple[int, int],
    batch: int,
    delay: float,
) -> dict:
    keys = _history_keys(chart_type)
    if settings.get(keys["status"]) == "completed":
        return {
            "chart_type": chart_type,
            "completed": True,
            "imported": [],
            "warnings": [],
        }

    year = int(settings[keys["next_year"]])
    week = int(settings[keys["next_week"]])
    imported: list[str] = []
    warnings: list[str] = []

    for _ in range(batch):
        if (year, week) > current_pair:
            set_settings(
                {
                    keys["status"]: "completed",
                    keys["error"]: "",
                    keys["completed_at"]: now_iso(),
                }
            )
            return {
                "chart_type": chart_type,
                "completed": True,
                "imported": imported,
                "warnings": warnings,
            }

        target = date.fromisocalendar(year, week, 1)
        chart = fetch_chart_from_website(
            target,
            chart_type,
            allow_incomplete=True,
        )
        _persist_chart(chart, False)
        imported.append(chart.edition_key)
        if chart.warning:
            warnings.append(chart.warning)

        year, week = _next_week(year, week)
        set_settings(
            {
                keys["next_year"]: year,
                keys["next_week"]: week,
                keys["last"]: chart.edition_key,
                keys["status"]: "running",
                keys["error"]: "",
            }
        )
        if delay:
            time.sleep(delay)

    completed = (year, week) > current_pair
    if completed:
        set_settings(
            {
                keys["status"]: "completed",
                keys["error"]: "",
                keys["completed_at"]: now_iso(),
            }
        )
    return {
        "chart_type": chart_type,
        "completed": completed,
        "imported": imported,
        "warnings": warnings,
        "next": f"{year}-W{week:02d}",
    }


def _finish_combined_history() -> dict:
    with connect() as con:
        top = con.execute(
            "SELECT edition_key FROM editions ORDER BY year DESC,week DESC LIMIT 1"
        ).fetchone()
        tip = con.execute(
            "SELECT edition_key FROM tipparade_editions ORDER BY year DESC,week DESC LIMIT 1"
        ).fetchone()
    top_key = top["edition_key"] if top else ""
    tip_key = tip["edition_key"] if tip else ""
    set_settings(
        {
            "history_enabled": "0",
            "history_status": "completed",
            "tip_history_status": "completed",
            "history_last_error": "",
            "tip_history_last_error": "",
            "history_completed_at": now_iso(),
            "tip_history_completed_at": now_iso(),
            "history_last_edition": top_key,
            "tip_history_last_edition": tip_key,
            "last_edition": top_key,
            "last_tipparade_edition": tip_key,
        }
    )
    return {
        "completed": True,
        "top40": top_key,
        "tipparade": tip_key,
        "message": "Top 40- en Tipparadehistorie zijn actueel; de weekcontrole neemt het over.",
    }


def run_history_batch():
    with connect() as con:
        settings = get_settings(con)

    if (
        settings.get("history_status") == "completed"
        and settings.get("tip_history_status") == "completed"
    ):
        return {
            "skipped": True,
            "completed": True,
            "message": "Top 40- en Tipparadehistorie zijn al actueel.",
        }
    if settings.get("history_enabled") != "1":
        return {"skipped": True, "message": "Historische import staat gepauzeerd"}

    batch = max(1, int(settings["history_batch_weeks"]))
    delay = max(0.0, float(settings["history_delay_seconds"]))
    results: dict[str, dict] = {}
    errors: dict[str, str] = {}

    # Top 40 en Tipparade worden onafhankelijk verwerkt. Een tijdelijke fout in
    # één lijst mag de voortgang van de andere lijst niet meer blokkeren.
    for chart_type in ("top40", "tipparade"):
        with connect() as con:
            chart_settings = get_settings(con)
        keys = _history_keys(chart_type)

        if chart_settings.get(keys["status"]) == "completed":
            results[chart_type] = {
                "chart_type": chart_type,
                "completed": True,
                "imported": [],
                "warnings": [],
            }
            continue

        try:
            current_pair = _known_current_pair(chart_settings, chart_type)
            with connect() as con:
                chart_settings = get_settings(con)
            results[chart_type] = _run_chart_history(
                chart_type,
                chart_settings,
                current_pair,
                batch,
                delay,
            )
        except Exception as exc:
            message = str(exc)[-3000:]
            set_settings(
                {
                    keys["status"]: "error",
                    keys["error"]: message,
                }
            )
            results[chart_type] = {
                "chart_type": chart_type,
                "completed": False,
                "imported": [],
                "warnings": [],
                "error": message,
            }
            errors[chart_type] = message

    with connect() as con:
        refreshed = get_settings(con)
    if (
        refreshed.get("history_status") == "completed"
        and refreshed.get("tip_history_status") == "completed"
    ):
        response = _finish_combined_history()
    else:
        response = {"completed": False, "results": results}

    if errors:
        response["errors"] = errors

    # Downloads worden bewust door de permanente downloadtimer afgehandeld.
    # Daardoor kan de historische import zonder wachttijd door naar de volgende batch.
    response["downloads"] = 0
    response["download_queue"] = "top40-archiver-download.timer"
    return response
