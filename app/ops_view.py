from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .db import get_settings
from .learning_engine import auto_heal_cycle, policy_snapshot
from .ops_engine import execute_repair, init_ops, list_incidents, resume_downloads, scan_failed_tracks

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/ai-operations", response_class=HTMLResponse)
def operations_page(request: Request):
    init_ops()
    return templates.TemplateResponse(request, "ai_operations.html", {})


@router.get("/api/ai-operations")
def operations_api():
    scan = scan_failed_tracks()
    settings = get_settings()
    incidents = list_incidents()
    return JSONResponse({
        "ok": True,
        "scan": scan,
        "paused": settings.get("operations_download_paused", "0") == "1",
        "incidents": incidents,
        "open_count": sum(1 for item in incidents if item["status"] == "open"),
        "policies": policy_snapshot(),
    })


@router.post("/ai-operations/scan")
def operations_scan():
    scan_failed_tracks()
    return RedirectResponse("/ai-operations", 303)


@router.post("/ai-operations/learn")
def operations_learn():
    auto_heal_cycle()
    return RedirectResponse("/ai-operations", 303)


@router.post("/ai-operations/incident/{incident_id}/repair")
def repair_incident(incident_id: int, action_name: str = Form("")):
    execute_repair(incident_id, action_name.strip() or None)
    return RedirectResponse("/ai-operations", 303)


@router.post("/ai-operations/resume")
def resume_queue():
    resume_downloads()
    return RedirectResponse("/ai-operations", 303)
