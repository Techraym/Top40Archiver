from __future__ import annotations

from datetime import date

from .db import connect, get_settings, set_settings
from .top40 import fetch_chart
from .service_common import _persist_chart
from .service_queue import process_queue, organize_downloaded_files
from .service_history import history_start, history_pause, run_history_batch


def import_latest(force: bool = False):
    with connect() as con:
        settings = get_settings(con)
    start = date.fromisoformat(settings["start_date"])
    if date.today() < start:
        return {"skipped": True, "message": f"Startdatum is {start.isoformat()}"}

    results: dict[str, dict] = {}
    all_new_ids: list[int] = []
    errors: dict[str, str] = {}

    for chart_type in ("top40", "tipparade"):
        if chart_type == "tipparade" and settings.get("tipparade_enabled", "1") != "1":
            continue
        try:
            chart = fetch_chart(chart_type=chart_type)
            result = _persist_chart(chart, force)
            results[chart_type] = result
            all_new_ids.extend(result.get("new_track_ids", []))
            setting_key = "last_edition" if chart_type == "top40" else "last_tipparade_edition"
            updates = {setting_key: chart.edition_key}
            if settings.get("history_status") == "completed":
                updates[
                    "history_last_edition" if chart_type == "top40" else "tip_history_last_edition"
                ] = chart.edition_key
            set_settings(updates)
        except Exception as exc:
            errors[chart_type] = str(exc)

    # Alleen nummers die wereldwijd nog niet in SQLite stonden worden automatisch gedownload.
    downloads = process_queue(track_ids=all_new_ids) if all_new_ids else []
    if not results:
        raise RuntimeError("Geen actuele lijst kon worden verwerkt: " + " | ".join(errors.values()))
    return {
        "results": results,
        "new_unique_tracks": len(set(all_new_ids)),
        "downloads": len(downloads),
        "errors": errors,
    }


__all__ = [
    "import_latest",
    "process_queue",
    "organize_downloaded_files",
    "history_start",
    "history_pause",
    "run_history_batch",
]
