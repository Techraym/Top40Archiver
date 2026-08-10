from __future__ import annotations

import asyncio
import os
from pathlib import Path
import socket

import requests
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from .ai_control_room import control_room_response, router as control_room_router
from .ai_memory import best_learning, remember_event, timeline
from .ai_ui_admin import router as ui_admin_router
from .ai_ui_policy import page_policy
from .incident_engine import incident_summary, list_incidents, scan_journal
from .operations_center import cover_dashboard, database_dashboard, download_dashboard, health_score, service_monitor


def _release_version() -> str:
    try:
        return (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


VERSION = _release_version()
LOG_READER = os.getenv("TOP40_LOG_READER_URL", "http://127.0.0.1:8042")
app = FastAPI(title="Top40Archiver AI Operations Center", version=VERSION)


def _reader(path: str, params: dict | None = None) -> dict:
    try:
        response = requests.get(LOG_READER + path, params=params, timeout=12)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise HTTPException(503, f"Logreader niet beschikbaar: {exc}") from exc


def _ollama() -> dict[str, object]:
    host = os.getenv("OLLAMA_HOST", "127.0.0.1")
    port = int(os.getenv("OLLAMA_PORT", "11434"))
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return {"reachable": True, "model": os.getenv("TOP40_AI_MODEL", "qwen3:4b")}
    except OSError:
        return {"reachable": False, "model": os.getenv("TOP40_AI_MODEL", "qwen3:4b")}


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    """AI-owned monitoring page on :8041; :8040 is never part of this UI loop."""
    return control_room_response()


@app.get("/api/overview")
def overview():
    return {
        "ok": True,
        "health": health_score(),
        "services": service_monitor(),
        "downloads": download_dashboard(),
        "covers": cover_dashboard(),
        "database": database_dashboard(),
        "incidents": incident_summary(),
        "ollama": _ollama(),
        "page_policy": page_policy(),
    }


@app.get("/api/operations/services")
def services():
    return {"ok": True, "items": service_monitor()}


@app.get("/api/operations/downloads")
def downloads():
    return {"ok": True, **download_dashboard()}


@app.get("/api/operations/covers")
def covers():
    return {"ok": True, **cover_dashboard()}


@app.get("/api/operations/database")
def database():
    return {"ok": True, **database_dashboard()}


@app.get("/api/timeline")
def history(limit: int = Query(100, ge=1, le=500)):
    return {"ok": True, "items": timeline(limit)}


@app.get("/api/incidents")
def incidents(status: str = Query("open", pattern="^(open|all)$"), limit: int = Query(100, ge=1, le=500)):
    return {"ok": True, "summary": incident_summary(), "incidents": list_incidents(limit, status)}


@app.post("/api/incidents/scan")
def scan(minutes: int = Query(20, ge=1, le=240)):
    result = scan_journal(minutes)
    remember_event("scan", "Handmatige incidentscan uitgevoerd", metadata=result)
    return {"ok": True, "result": result}


@app.get("/api/logs/service/{service}")
def logs(service: str, minutes: int = 60, lines: int = 1000):
    return _reader(f"/api/logs/service/{service}", {"minutes": minutes, "lines": lines})


@app.get("/api/logs/errors")
def errors(minutes: int = 1440, lines: int = 500):
    return _reader("/api/logs/errors", {"minutes": minutes, "lines": lines})


@app.get("/api/search")
def search(q: str = Query(..., min_length=2, max_length=200)):
    logs_found = _reader("/api/logs/search", {"q": q, "lines": 500}).get("items", [])
    found = [
        x
        for x in list_incidents(500, "all")
        if q.casefold() in (str(x.get("title", "")) + " " + str(x.get("recommendation", ""))).casefold()
    ]
    return {"ok": True, "logs": logs_found, "incidents": found, "learning": best_learning(q)}


@app.websocket("/ws/logs")
async def ws_logs(ws: WebSocket):
    await ws.accept()
    service = ws.query_params.get("service", "all")
    seen = set()
    try:
        while True:
            data = _reader("/api/logs/live", {"service": service, "minutes": 2, "lines": 250})
            for item in data.get("items", []):
                key = (item.get("time"), item.get("service"), item.get("message"))
                if key not in seen:
                    seen.add(key)
                    await ws.send_json(item)
            await asyncio.sleep(1)
    except (WebSocketDisconnect, RuntimeError):
        return


@app.get("/healthz")
def healthz():
    return {
        "ok": True,
        "service": "top40-ai-sidecar",
        "version": VERSION,
        "port": 8041,
        "log_reader": LOG_READER,
        "control_room": True,
        "operator_ui_controls": True,
        "page_policy": page_policy(),
    }


app.include_router(control_room_router)
app.include_router(ui_admin_router)
