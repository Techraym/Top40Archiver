from __future__ import annotations

import threading
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .library_quality import (
    RADIO_WRITE_CONFIDENCE,
    COVER_TRACK_BUDGET,
    COVER_LOOKUP_TIMEOUT,
    TOP40_BACKFILL_TIMEOUT,
    current_state,
    init_library_quality_db,
    list_tracks,
    recent_events,
    scan_library,
    summary,
)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=select_autoescape(["html", "xml"]))
app = FastAPI(title="Top40Archiver Library Quality", version="1.16.23.6")
app.mount("/static-quality", StaticFiles(directory=str(STATIC_DIR)), name="static-quality")
_scan_thread: threading.Thread | None = None
_thread_lock = threading.Lock()


@app.on_event("startup")
def startup() -> None:
    init_library_quality_db()


@app.get("/healthz")
def healthz():
    return {
        "ok": True,
        "service": "library-quality",
        "version": "1.16.23.6",
        "port": 8085,
        "aeron_connection": False,
        "dry_run": False,
        "radio_write_confidence": RADIO_WRITE_CONFIDENCE,
        "cover_track_budget": COVER_TRACK_BUDGET,
        "cover_lookup_timeout": COVER_LOOKUP_TIMEOUT,
        "top40_backfill_timeout": TOP40_BACKFILL_TIMEOUT,
    }


@app.get("/", response_class=HTMLResponse)
def index():
    template = env.get_template("library_quality.html")
    return template.render()


@app.get("/api/summary")
def api_summary():
    return summary()


@app.get("/api/tracks")
def api_tracks(
    status: str | None = None,
    q: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    return {"items": list_tracks(status=status, query=q, limit=limit, offset=offset)}


@app.get("/api/events")
def api_events(limit: int = Query(100, ge=1, le=500)):
    return {"items": recent_events(limit)}


@app.get("/api/state")
def api_state():
    return current_state()


@app.get("/api/scan/status")
def api_scan_status():
    """Alias voor UI/CLI clients die een expliciete scanstatus-URL verwachten."""
    return current_state()


def _run_scan(max_files: int, force: bool) -> None:
    try:
        scan_library(trigger="web", force=force, max_files=max_files)
    finally:
        global _scan_thread
        with _thread_lock:
            _scan_thread = None


@app.post("/api/scan")
def api_scan(
    max_files: int = Query(25, ge=1, le=1_000_000),
    force: bool = Query(False),
):
    """Start een begrensde scan. De UI moet expliciet voor een grotere batch kiezen."""
    global _scan_thread
    with _thread_lock:
        if _scan_thread and _scan_thread.is_alive():
            return {"ok": False, "running": True, "message": "Bibliotheekcontrole draait al."}
        state = current_state()
        if state.get("running"):
            return {"ok": False, "running": True, "message": "Bibliotheekcontrole draait al."}
        _scan_thread = threading.Thread(
            target=_run_scan,
            args=(max_files, force),
            name="library-quality-scan",
            daemon=True,
        )
        _scan_thread.start()
    return {
        "ok": True,
        "running": True,
        "max_files": max_files,
        "message": f"Controle & herstel gestart voor maximaal {max_files} bestanden.",
    }
