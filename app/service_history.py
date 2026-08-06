from __future__ import annotations

from datetime import date
import re
import time

from .db import (
    connect,
    get_settings,
    now_iso,
    recover_stale_missing_history,
    set_settings,
)
from .top40 import (
    ChartType,
    chart_label,
    fetch_chart,
    fetch_chart_from_website,
)
from .service_common import _next_week, _parse_edition_key, _persist_chart

MISSING_HISTORICAL_HTTP_STATUSES = {404, 410}


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


def _http_status_from_exception(exc: Exception) -> int | None:
    """Read HTTP status from attributes, wrapped exceptions or error text."""
    current: BaseException | None = exc
    seen: set[int] = set()

    while current is not None and id(current) not in seen:
        seen.add(id(current))
        response = getattr(current, "response", None)
        candidates = (
            getattr(current, "status_code", None),
            getattr(response, "status_code", None),
            getattr(response, "status", None),
        )
        for candidate in candidates:
            try:
                if candidate is not None:
                    return int(candidate)
            except (TypeError, ValueError):
                pass

        match = re.search(r"(?<!\d)(404|410)(?!\d)", str(current))
        if match:
            return int(match.group(1))

        current = current.__cause__ or current.__context__

    return None


def _skip_missing_history_cursor(
    chart_type: ChartType,
    settings: dict,
    status_code: int,
) -> dict:
    """Advance one historical cursor without pretending the edition was imported."""
    keys = _history_keys(chart_type)
    year = int(settings[keys["next_year"]])
    week = int(settings[keys["next_week"]])
    edition_key = f"{year}-W{week:02d}"
    next_year, next_week = _next_week(year, week)
    warning = (
        f"{chart_label(chart_type)} {edition_key} ontbreekt op de historische bron "
        f"(HTTP {status_code}). De editie is overgeslagen en de verwerking gaat "
        "automatisch verder."
    )
    set_settings(
        {
            keys["next_year"]: next_year,
            keys["next_week"]: next_week,
            keys["status"]: "running",
            keys["error"]: "",
            keys["completed_at"]: "",
            "history_enabled": "1",
        }
    )
    return {
        "chart_type": chart_type,
        "completed": False,
        "imported": [],
        "warnings": [warning],
        "skipped": [edition_key],
        "next": f"{next_year}-W{next_week:02d}",
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
            "skipped": [],
        }

    year = int(settings[keys["next_year"]])
    week = int(settings[keys["next_week"]])
    imported: list[str] = []
    warnings: list[str] = []
    skipped: list[str] = []

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
                "skipped": skipped,
            }

        target = date.fromisocalendar(year, week, 1)
        edition_key = f"{year}-W{week:02d}"
        try:
            chart = fetch_chart_from_website(
                target,
                chart_type,
                allow_incomplete=True,
            )
        except Exception as exc:
            message = str(exc)
            status_code = _http_status_from_exception(exc)
            missing_source_page = status_code in MISSING_HISTORICAL_HTTP_STATUSES
            unreadable_source_page = (
                isinstance(exc, ValueError)
                and "herkenbare noteringen" in message.casefold()
            )
            if not missing_source_page and not unreadable_source_page:
                raise

            if missing_source_page:
                skipped_result = _skip_missing_history_cursor(
                    chart_type,
                    {
                        **settings,
                        keys["next_year"]: year,
                        keys["next_week"]: week,
                    },
                    int(status_code),
                )
                warning = skipped_result["warnings"][0]
            else:
                warning = (
                    f"{message} Editie {edition_key} is overgeslagen; "
                    "de historische verwerking gaat automatisch verder."
                )
                next_year, next_week = _next_week(year, week)
                set_settings(
                    {
                        keys["next_year"]: next_year,
                        keys["next_week"]: next_week,
                        keys["status"]: "running",
                        keys["error"]: "",
                        keys["completed_at"]: "",
                        "history_enabled": "1",
                    }
                )

            warnings.append(warning)
            skipped.append(edition_key)
            year, week = _next_week(year, week)
            if delay:
                time.sleep(delay)
            continue

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
        "skipped": skipped,
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
    # Herstel eerst cursors die door een oudere versie op een ontbrekende pagina
    # zijn achtergelaten. Dit wordt iedere batch herhaald en is dus niet afhankelijk
    # van alleen de applicatiestart.
    recover_stale_missing_history()

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
    # één lijst mag de voortgang van de andere lijst niet blokkeren.
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
                "skipped": [],
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
            status_code = _http_status_from_exception(exc)
            if status_code in MISSING_HISTORICAL_HTTP_STATUSES:
                with connect() as con:
                    current_settings = get_settings(con)
                results[chart_type] = _skip_missing_history_cursor(
                    chart_type,
                    current_settings,
                    int(status_code),
                )
                continue

            set_settings(
                {
                    keys["status"]: "running",
                    keys["error"]: (
                        "Tijdelijke bronfout; automatische nieuwe poging binnen één minuut. "
                        + message
                    ),
                }
            )
            results[chart_type] = {
                "chart_type": chart_type,
                "completed": False,
                "imported": [],
                "warnings": [],
                "skipped": [],
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

    # Downloads worden door de permanente downloadservice afgehandeld.
    response["downloads"] = 0
    response["download_queue"] = "top40-archiver-download.service"
    return response
