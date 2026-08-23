from __future__ import annotations

import asyncio
import json
import socket
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .cover_art_state import cover_dashboard_state
from .dashboard import download_chart, history_progress, queue_summary, storage_status
from .download_api import router as download_router
from .db import connect, get_settings, init_db, now_iso, set_settings
from .service import (
    history_pause,
    history_start,
    import_latest,
    organize_downloaded_files,
    process_queue,
    run_history_batch,
)
from .spotify import spotify_configured

BASE = Path(__file__).resolve().parent


def _load_app_version() -> str:
    try:
        return (BASE.parent / "VERSION").read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


APP_VERSION = _load_app_version()
LIVE_INTERVAL_SECONDS = 1.0

app = FastAPI(title="Top 40 Archiver", version=APP_VERSION)
app.include_router(download_router)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")

STATUS_LABELS = {
    "pending": "In wachtrij",
    "downloading": "Bezig",
    "downloaded": "Gedownload",
    "failed": "Mislukt",
    "unavailable": "Niet meer beschikbaar",
}
SPOTIFY_STATUS_LABELS = {
    "unchecked": "Nog niet gecontroleerd",
    "not_configured": "Niet ingesteld",
    "matched": "Overeenkomst",
    "low_confidence": "Twijfel",
    "not_found": "Niet gevonden",
    "error": "Fout",
}


@app.on_event("startup")
def startup() -> None:
    init_db()


def _rows(rows: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _latest_chart(con, edition_table: str, entry_table: str) -> tuple[dict | None, list[dict]]:
    latest_row = con.execute(
        f"SELECT * FROM {edition_table} ORDER BY year DESC,week DESC LIMIT 1"
    ).fetchone()
    latest = dict(latest_row) if latest_row else None
    entries = []
    if latest:
        entries = _rows(
            con.execute(
                f"""
                SELECT ce.position,ce.is_new,t.*
                FROM {entry_table} ce
                JOIN tracks t ON t.id=ce.track_id
                WHERE ce.edition_id=?
                ORDER BY ce.position
                """,
                (latest["id"],),
            ).fetchall()
        )
    return latest, entries


def _dashboard_data(q: str = "") -> dict[str, Any]:
    with connect() as con:
        settings = get_settings(con)
        latest_top40, top40_entries = _latest_chart(con, "editions", "chart_entries")
        latest_tipparade, tipparade_entries = _latest_chart(
            con, "tipparade_editions", "tipparade_entries"
        )

        queue = _rows(
            con.execute(
                """
                SELECT * FROM tracks
                WHERE download_status IN ('pending','downloading')
                ORDER BY CASE download_status WHEN 'downloading' THEN 0 ELSE 1 END,
                         updated_at DESC,id
                LIMIT 30
                """
            ).fetchall()
        )
        success = _rows(
            con.execute(
                """
                SELECT * FROM tracks
                WHERE download_status='downloaded'
                ORDER BY processed_at DESC
                LIMIT 12
                """
            ).fetchall()
        )
        failed = _rows(
            con.execute(
                """
                SELECT * FROM tracks
                WHERE download_status='failed'
                ORDER BY updated_at DESC
                LIMIT 30
                """
            ).fetchall()
        )
        unavailable = _rows(
            con.execute(
                """
                SELECT * FROM tracks
                WHERE download_status='unavailable'
                ORDER BY updated_at DESC
                LIMIT 30
                """
            ).fetchall()
        )
        activity = _rows(
            con.execute(
                """
                SELECT id,artist,title,download_status,spotify_status,updated_at,mp3_filename
                FROM tracks
                ORDER BY updated_at DESC
                LIMIT 10
                """
            ).fetchall()
        )

        status_counts = {key: 0 for key in STATUS_LABELS}
        for row in con.execute(
            "SELECT download_status,COUNT(*) AS c FROM tracks GROUP BY download_status"
        ):
            status_counts[row["download_status"]] = row["c"]

        active_job_count = 0
        has_download_jobs = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='download_jobs'"
        ).fetchone()
        if has_download_jobs:
            active_job_count = con.execute(
                """
                SELECT COUNT(*) AS c
                FROM download_jobs
                WHERE status IN ('searching','downloading','validating','processing')
                  AND cancel_requested=0
                """
            ).fetchone()["c"]

        queue_state = queue_summary(status_counts, active_job_count)

        spotify_counts = {key: 0 for key in SPOTIFY_STATUS_LABELS}
        for row in con.execute(
            "SELECT spotify_status,COUNT(*) AS c FROM tracks GROUP BY spotify_status"
        ):
            spotify_counts[row["spotify_status"]] = row["c"]

        total = con.execute("SELECT COUNT(*) AS c FROM tracks").fetchone()["c"]
        top40_edition_count = con.execute("SELECT COUNT(*) AS c FROM editions").fetchone()["c"]
        tipparade_edition_count = con.execute(
            "SELECT COUNT(*) AS c FROM tipparade_editions"
        ).fetchone()["c"]

        history = []
        if q.strip():
            like = f"%{q.strip().lower()}%"
            history = _rows(
                con.execute(
                    """
                    SELECT * FROM tracks
                    WHERE lower(artist) LIKE ? OR lower(title) LIKE ?
                    ORDER BY artist,title
                    LIMIT 200
                    """,
                    (like, like),
                ).fetchall()
            )

    rendered_at = datetime.now().astimezone().strftime("%d-%m-%Y %H:%M:%S")
    return {
        "settings": settings,
        "latest": latest_top40,
        "entries": top40_entries,
        "latest_top40": latest_top40,
        "top40_entries": top40_entries,
        "latest_tipparade": latest_tipparade,
        "tipparade_entries": tipparade_entries,
        "queue": queue,
        "success": success,
        "failed": failed,
        "unavailable": unavailable,
        "activity": activity,
        "status_counts": status_counts,
        "queue_state": queue_state,
        "status_labels": STATUS_LABELS,
        "spotify_status_labels": SPOTIFY_STATUS_LABELS,
        "spotify_counts": spotify_counts,
        "spotify_configured": spotify_configured(),
        "total": total,
        "edition_count": top40_edition_count + tipparade_edition_count,
        "top40_edition_count": top40_edition_count,
        "tipparade_edition_count": tipparade_edition_count,
        "download_chart": download_chart(status_counts),
        "history_progress": history_progress(settings),
        "cover_progress": cover_dashboard_state(),
        "storage": storage_status(settings["download_dir"]),
        "history": history,
        "q": q,
        "rendered_at": rendered_at,
        "server_time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "app_version": APP_VERSION,
        "network_share_unc": rf"\\{socket.gethostname().split('.')[0]}\Top40Music",
    }


def _live_payload() -> dict[str, Any]:
    data = _dashboard_data()
    return {
        "ok": True,
        "version": APP_VERSION,
        "rendered_at": data["rendered_at"],
        "server_time": data["server_time"],
        "latest": data["latest_top40"],
        "entries": data["top40_entries"],
        "latest_top40": data["latest_top40"],
        "top40_entries": data["top40_entries"],
        "latest_tipparade": data["latest_tipparade"],
        "tipparade_entries": data["tipparade_entries"],
        "queue": data["queue"],
        "success": data["success"],
        "failed": data["failed"],
        "unavailable": data["unavailable"],
        "activity": data["activity"],
        "status_counts": data["status_counts"],
        "queue_state": data["queue_state"],
        "status_labels": STATUS_LABELS,
        "spotify_counts": data["spotify_counts"],
        "spotify_configured": data["spotify_configured"],
        "total": data["total"],
        "edition_count": data["edition_count"],
        "download_chart": data["download_chart"],
        "history_progress": data["history_progress"],
        "cover_progress": data["cover_progress"],
        "history_last_edition": data["settings"].get("history_last_edition", ""),
        "tip_history_last_edition": data["settings"].get("tip_history_last_edition", ""),
        "history_last_error": data["settings"].get("history_last_error", ""),
        "tip_history_last_error": data["settings"].get("tip_history_last_error", ""),
        "storage": data["storage"],
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request, q: str = ""):
    return templates.TemplateResponse(request, "index.html", _dashboard_data(q))


@app.get("/zoeken", response_class=HTMLResponse)
def zoeken_page(request: Request, q: str = ""):
    return templates.TemplateResponse(
        request,
        "zoeken.html",
        _dashboard_data(q),
    )


@app.get("/hitlijsten", response_class=HTMLResponse)
def hitlijsten_page(request: Request):
    return templates.TemplateResponse(
        request,
        "hitlijsten.html",
        {
            "app_version": APP_VERSION,
        },
    )


@app.get("/instellingen", response_class=HTMLResponse)
def instellingen_page(request: Request):
    with connect() as con:
        settings_data = get_settings(con)

    return templates.TemplateResponse(
        request,
        "instellingen.html",
        {
            "settings": settings_data,
            "app_version": APP_VERSION,
        },
    )


@app.get("/api/live")
def live_api():
    return JSONResponse(_live_payload())


@app.get("/events")
async def live_events(request: Request):
    async def stream():
        while True:
            if await request.is_disconnected():
                break
            try:
                payload = json.dumps(
                    _live_payload(), ensure_ascii=False, separators=(",", ":")
                )
                yield f"event: dashboard\ndata: {payload}\n\n"
            except Exception as exc:  # pragma: no cover
                payload = json.dumps(
                    {"ok": False, "error": str(exc), "version": APP_VERSION},
                    ensure_ascii=False,
                )
                yield f"event: dashboard-error\ndata: {payload}\n\n"
            await asyncio.sleep(LIVE_INTERVAL_SECONDS)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/check")
def check(background_tasks: BackgroundTasks):
    background_tasks.add_task(import_latest, False)
    return RedirectResponse("/", 303)


@app.post("/retry")
def retry(background_tasks: BackgroundTasks):
    with connect() as con:
        con.execute(
            """
            UPDATE tracks
            SET download_status='pending',download_attempts=0,error_message=NULL,updated_at=?
            WHERE download_status='failed'
            """,
            (now_iso(),),
        )
    background_tasks.add_task(process_queue)
    return RedirectResponse("/", 303)


@app.post("/organize")
def organize(background_tasks: BackgroundTasks):
    background_tasks.add_task(organize_downloaded_files)
    return RedirectResponse("/", 303)


@app.post("/history/start")
def start_history(background_tasks: BackgroundTasks, reset: bool = Form(False)):
    background_tasks.add_task(history_start, reset)
    return RedirectResponse("/", 303)


@app.post("/history/pause")
def pause_history():
    history_pause()
    return RedirectResponse("/", 303)


@app.post("/history/batch")
def history_batch(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_history_batch)
    return RedirectResponse("/", 303)


@app.post("/settings")
def settings(
    start_date: str = Form(...),
    weekly_day: str = Form(...),
    weekly_time: str = Form(...),
    download_dir: str = Form(...),
    max_download_attempts: int = Form(...),
    search_template: str = Form(...),
    history_start_year: int = Form(...),
    history_start_week: int = Form(...),
    history_batch_weeks: int = Form(...),
    history_delay_seconds: float = Form(...),
    history_download_limit: int = Form(...),
    tipparade_enabled: bool = Form(False),
    spotify_validation_enabled: bool = Form(False),
    spotify_min_match_score: float = Form(0.70),
):
    set_settings(
        {
            "start_date": start_date,
            "weekly_day": weekly_day,
            "weekly_time": weekly_time,
            "download_dir": download_dir,
            "max_download_attempts": max_download_attempts,
            "search_template": search_template,
            "history_start_year": history_start_year,
            "history_start_week": history_start_week,
            "history_batch_weeks": history_batch_weeks,
            "history_delay_seconds": history_delay_seconds,
            "history_download_limit": history_download_limit,
            "tipparade_enabled": "1" if tipparade_enabled else "0",
            "spotify_validation_enabled": "1" if spotify_validation_enabled else "0",
            "spotify_min_match_score": max(0.0, min(1.0, spotify_min_match_score)),
        }
    )
    return RedirectResponse("/instellingen", 303)


@app.post("/track/{track_id}/query")
def track_query(track_id: int, custom_search_query: str = Form(...)):
    with connect() as con:
        con.execute(
            """
            UPDATE tracks
            SET custom_search_query=?,download_status='pending',download_attempts=0,
                youtube_url=NULL,error_message=NULL,updated_at=?
            WHERE id=?
            """,
            (custom_search_query.strip() or None, now_iso(), track_id),
        )
    return RedirectResponse("/", 303)


@app.post("/track/{track_id}/unavailable")
def track_unavailable(track_id: int):
    with connect() as con:
        con.execute(
            """
            UPDATE tracks
            SET download_status='unavailable',custom_search_query=NULL,
                error_message='Handmatig gemarkeerd als niet meer beschikbaar op de downloadbron',
                updated_at=?
            WHERE id=? AND download_status!='downloaded'
            """,
            (now_iso(), track_id),
        )
    return RedirectResponse("/", 303)


@app.post("/track/{track_id}/restore")
def track_restore(track_id: int):
    with connect() as con:
        con.execute(
            """
            UPDATE tracks
            SET download_status='pending',download_attempts=0,youtube_url=NULL,
                error_message=NULL,updated_at=?
            WHERE id=? AND download_status='unavailable'
            """,
            (now_iso(), track_id),
        )
    return RedirectResponse("/", 303)


@app.get("/api/dashboard")
def dashboard_api():
    payload = _live_payload()
    return JSONResponse(
        {
            "ok": True,
            "version": APP_VERSION,
            "latest_top40": payload["latest_top40"]["edition_key"]
            if payload["latest_top40"]
            else None,
            "latest_tipparade": payload["latest_tipparade"]["edition_key"]
            if payload["latest_tipparade"]
            else None,
            "edition_count": payload["edition_count"],
            "download_status": payload["status_counts"],
            "spotify_configured": payload["spotify_configured"],
            "history": payload["history_progress"],
            "covers": payload["cover_progress"],
        }
    )


@app.get("/health")
def health():
    return JSONResponse(
        {
            "ok": True,
            "version": APP_VERSION,
            "live": True,
            "spotify_configured": spotify_configured(),
        }
    )
