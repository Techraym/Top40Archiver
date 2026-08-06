from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from .health_engine import (
    collect_health_snapshot,
    health_events,
    health_history,
    latest_health,
    start_health_collector,
)
from .health_trends import health_trends

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
start_health_collector()


@router.get("/ai-health", response_class=HTMLResponse)
def health_page(request: Request):
    return templates.TemplateResponse(request, "ai_health.html", {})


@router.get("/api/health")
def health_api(refresh: bool = Query(False)):
    snapshot = collect_health_snapshot() if refresh else latest_health()
    return JSONResponse({"ok": True, "health": snapshot})


@router.get("/api/health/score")
def health_score_api():
    snapshot = latest_health()
    return JSONResponse(
        {
            "ok": True,
            "score": snapshot["score"],
            "status": snapshot["status"],
            "diagnosis": snapshot["diagnosis"],
            "captured_at": snapshot["captured_at"],
        }
    )


@router.get("/api/health/history")
def health_history_api(
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(500, ge=10, le=2000),
):
    return JSONResponse({"ok": True, "hours": hours, "rows": health_history(hours, limit)})


@router.get("/api/health/trends")
def health_trends_api(range: str = Query("24h", pattern="^(1h|24h|7d)$")):
    return JSONResponse({"ok": True, **health_trends(range)})


@router.get("/api/health/events")
def health_events_api(limit: int = Query(100, ge=1, le=500)):
    return JSONResponse({"ok": True, "events": health_events(limit)})
