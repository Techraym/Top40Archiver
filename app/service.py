from __future__ import annotations

from datetime import date
import time

from .db import connect, get_settings, set_settings
from .top40 import fetch_chart
from .service_common import _persist_chart
from .service_queue import (
    organize_downloaded_files,
    process_queue as _process_queue,
)
from .service_history import history_start, history_pause, run_history_batch


def downloads_paused() -> bool:
    return get_settings().get("operations_download_paused", "0") == "1"


def process_queue(limit: int | None = None, track_ids=None):
    if downloads_paused():
        return [{"paused": True, "message": "Downloadwachtrij is door AI Operations gepauzeerd."}]
    return _process_queue(limit=limit, track_ids=track_ids)


def run_download_daemon(
    limit: int = 20,
    idle_seconds: float = 30.0,
    busy_seconds: float = 10.0,
):
    batch_limit = max(1, int(limit or 20))
    idle_wait = max(5.0, float(idle_seconds))
    last_state = ""
    while True:
        if downloads_paused():
            if last_state != "paused":
                print({"state": "paused", "message": "AI Operations heeft downloads veilig gepauzeerd."}, flush=True)
            last_state = "paused"
            time.sleep(idle_wait)
            continue
        results = _process_queue(limit=batch_limit)
        if results:
            print({"state": "processed", "count": len(results), "results": results}, flush=True)
            last_state = "processed"
            time.sleep(1.0)
        else:
            if last_state != "idle":
                print({"state": "idle", "message": "Downloadwachtrij is leeg; de worker blijft actief."}, flush=True)
            last_state = "idle"
            time.sleep(idle_wait)


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
    "run_download_daemon",
    "organize_downloaded_files",
    "history_start",
    "history_pause",
    "run_history_batch",
]
