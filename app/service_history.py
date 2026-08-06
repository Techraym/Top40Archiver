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
from .history_rules import get_blacklisted_history_rule
from .top40 import (
    ChartType,
    chart_label,
    fetch_chart,
    fetch_chart_from_website,
)
from .service_common import (
    _next_week,
    _normalize_week_cursor,
    _parse_edition_key,
    _persist_chart,
)

# Deze statussen betekenen voor een historische editie dat de bronpagina niet
# bruikbaar is. De editie wordt overgeslagen; de volgende ISO-week gaat door.
SKIPPABLE_HISTORICAL_HTTP_STATUSES = {402, 404, 410}
MISSING_HISTORICAL_HTTP_STATUSES = SKIPPABLE_HISTORICAL_HTTP_STATUSES


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
    return _normalize_week_cursor(chart.year, chart.week)


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


def _http_status_from_exception(exc: BaseException) -> int | None:
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

        match = re.search(r"(?<!\d)(402|404|410)(?!\d)", str(current))
        if match:
            return int(match.group(1))

        current = current.__cause__ or current.__context__

    return None


def _set_running_cursor(
    chart_type: ChartType,
    year: int,
    week: int,
    *,
    clear_error: bool = True,
) -> tuple[int, int]:
    """Store one valid ISO cursor and keep the historical worker enabled."""
    keys = _history_keys(chart_type)
    year, week = _normalize_week_cursor(year, week)
    values: dict[str, object] = {
        keys["next_year"]: year,
        keys["next_week"]: week,
        keys["status"]: "running",
        keys["completed_at"]: "",
        "history_enabled": "1",
    }
    if clear_error:
        values[keys["error"]] = ""
    set_settings(values)
    return year, week


def _skip_missing_history_cursor(
    chart_type: ChartType,
    settings: dict,
    status_code: int,
) -> dict:
    """Advance one historical cursor without pretending the edition was imported."""
    keys = _history_keys(chart_type)
    year, week = _normalize_week_cursor(
        int(settings[keys["next_year"]]),
        int(settings[keys["next_week"]]),
    )
    edition_key = f"{year}-W{week:02d}"
    next_year, next_week = _next_week(year, week)
    _set_running_cursor(chart_type, next_year, next_week)

    warning = (
        f"{chart_label(chart_type)} {edition_key} gaf HTTP {status_code}. "
        f"De editie is overgeslagen; de ISO-kalender gaat verder met "
        f"{next_year}-W{next_week:02d}."
    )
    return {
        "chart_type": chart_type,
        "completed": False,
        "imported": [],
        "warnings": [warning],
        "skipped": [edition_key],
        "next": f"{next_year}-W{next_week:02d}",
        "next_year": next_year,
        "next_week": next_week,
    }


def _skip_blacklisted_history_cursor(
    chart_type: ChartType,
    year: int,
    week: int,
) -> dict | None:
    """Skip a known missing source URL before any network request is made."""
    year, week = _normalize_week_cursor(year, week)
    rule = get_blacklisted_history_rule(chart_type, year, week)
    if rule is None:
        return None

    edition_key = f"{year}-W{week:02d}"
    next_year, next_week = _normalize_week_cursor(
        int(rule["next_year"]),
        int(rule["next_week"]),
    )
    _set_running_cursor(chart_type, next_year, next_week)

    warning = (
        f"{chart_label(chart_type)} {edition_key} staat op de bronblacklist. "
        f"{rule['reason']} De verwerking gaat verder met "
        f"{next_year}-W{next_week:02d}."
    )
    return {
        "chart_type": chart_type,
        "completed": False,
        "imported": [],
        "warnings": [warning],
        "skipped": [edition_key],
        "next": f"{next_year}-W{next_week:02d}",
        "next_year": next_year,
        "next_week": next_week,
    }


def _recover_stored_skippable_errors() -> list[str]:
    """Advance old stored 402/404/410 errors before making another request."""
    with connect() as con:
        settings = get_settings(con)

    recovered: list[str] = []
    for chart_type in ("top40", "tipparade"):
        keys = _history_keys(chart_type)
        if settings.get(keys["status"]) == "completed":
            continue
        error = str(settings.get(keys["error"], ""))
        status_code = _http_status_from_exception(RuntimeError(error)) if error else None
        if status_code not in SKIPPABLE_HISTORICAL_HTTP_STATUSES:
            continue
        result = _skip_missing_history_cursor(chart_type, settings, int(status_code))
        recovered.extend(result["skipped"])
        settings[keys["next_year"]] = str(result["next_year"])
        settings[keys["next_week"]] = str(result["next_week"])
        settings[keys["error"]] = ""
    return recovered


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

    raw_year = int(settings[keys["next_year"]])
    raw_week = int(settings[keys["next_week"]])
    year, week = _normalize_week_cursor(raw_year, raw_week)
    if (year, week) != (raw_year, raw_week):
        _set_running_cursor(chart_type, year, week)

    current_pair = _normalize_week_cursor(*current_pair)
    imported: list[str] = []
    warnings: list[str] = []
    skipped: list[str] = []
    visited: set[tuple[int, int]] = set()

    for _ in range(batch):
        year, week = _normalize_week_cursor(year, week)
        cursor = (year, week)
        edition_key = f"{year}-W{week:02d}"

        # Tweede beveiliging naast de kalender: dezelfde cursor mag binnen één
        # batch nooit nogmaals worden benaderd. Bij herhaling schuift hij door.
        if cursor in visited:
            next_year, next_week = _next_week(year, week)
            warning = (
                f"Herhaalde historische cursor {edition_key} voorkomen. "
                f"De ISO-kalender gaat verder met {next_year}-W{next_week:02d}."
            )
            warnings.append(warning)
            skipped.append(edition_key)
            year, week = _set_running_cursor(
                chart_type,
                next_year,
                next_week,
            )
            continue
        visited.add(cursor)

        blacklisted = _skip_blacklisted_history_cursor(chart_type, year, week)
        if blacklisted is not None:
            warnings.extend(blacklisted["warnings"])
            skipped.extend(blacklisted["skipped"])
            year = int(blacklisted["next_year"])
            week = int(blacklisted["next_week"])
            if delay:
                time.sleep(delay)
            continue

        if cursor > current_pair:
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
        try:
            chart = fetch_chart_from_website(
                target,
                chart_type,
                allow_incomplete=True,
            )
        except Exception as exc:
            message = str(exc)
            status_code = _http_status_from_exception(exc)
            skippable_http = status_code in SKIPPABLE_HISTORICAL_HTTP_STATUSES
            unreadable_source_page = (
                isinstance(exc, ValueError)
                and "herkenbare noteringen" in message.casefold()
            )
            if not skippable_http and not unreadable_source_page:
                raise

            if skippable_http:
                result = _skip_missing_history_cursor(
                    chart_type,
                    {
                        **settings,
                        keys["next_year"]: year,
                        keys["next_week"]: week,
                    },
                    int(status_code),
                )
                warning = result["warnings"][0]
                year = int(result["next_year"])
                week = int(result["next_week"])
            else:
                next_year, next_week = _next_week(year, week)
                warning = (
                    f"{message} Editie {edition_key} is overgeslagen; "
                    f"de ISO-kalender gaat verder met "
                    f"{next_year}-W{next_week:02d}."
                )
                year, week = _set_running_cursor(
                    chart_type,
                    next_year,
                    next_week,
                )

            warnings.append(warning)
            skipped.append(edition_key)
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
    # Herstel oude fouten, verwerk de blacklist en sla eerder opgeslagen
    # 402/404/410-edities over voordat een nieuw netwerkverzoek wordt uitgevoerd.
    recover_stale_missing_history()
    _recover_stored_skippable_errors()

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
            if status_code in SKIPPABLE_HISTORICAL_HTTP_STATUSES:
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

    response["downloads"] = 0
    response["download_queue"] = "top40-archiver-download.service"
    return response
