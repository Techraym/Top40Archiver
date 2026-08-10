from __future__ import annotations

import asyncio
import re
import subprocess
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from .ai_log_control import log_control_response
from .ai_ui_policy import page_policy

VERSION = "1.16.19"
app = FastAPI(title="Top40 Log Reader", version=VERSION, docs_url=None, redoc_url=None)

SERVICE_UNITS = {
    "web": ["top40-archiver-web.service"],
    "download": ["top40-archiver-download.service", "top40-download-manager.service"],
    "cover": [
        "top40-archiver-cover-art.service", "top40-archiver-cover-art.timer",
        "top40-archiver-id3-cover.service", "top40-archiver-id3-cover.timer",
    ],
    "ai": ["top40-archiver-ai.service", "top40-ai-recovery.service", "top40-ai-recovery.timer"],
    "ollama": ["ollama.service"],
    "database": [
        "top40-archiver-check.service", "top40-archiver-check.timer",
        "top40-archiver-history.service", "top40-archiver-history.timer",
    ],
    "updater": ["top40-archiver-auto-update.service", "top40-archiver-auto-update.timer"],
    "system": [
        "top40-log-reader.service",
        "top40-archiver-incident-scan.service", "top40-archiver-incident-scan.timer",
    ],
}
LEVEL_RE = re.compile(r"\b(error|failed|failure|critical|exception|traceback|warning|warn|429)\b", re.I)


def _units(service: str) -> list[str]:
    if service == "all":
        return sorted({unit for units in SERVICE_UNITS.values() for unit in units})
    if service not in SERVICE_UNITS:
        raise HTTPException(404, "Onbekende servicegroep")
    return SERVICE_UNITS[service]


def _journal(service: str, minutes: int, limit: int, grep: str | None = None) -> list[dict[str, Any]]:
    cmd = ["journalctl", "--no-pager", "--output=json", "--since", f"-{minutes} minutes", "-n", str(limit)]
    for unit in _units(service):
        cmd += ["-u", unit]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)
    rows: list[dict[str, Any]] = []
    import json
    for raw in proc.stdout.splitlines():
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        message = str(item.get("MESSAGE", ""))
        if grep and grep.casefold() not in message.casefold():
            continue
        priority = int(item.get("PRIORITY", 6) or 6)
        level = "critical" if priority <= 2 else "error" if priority <= 3 else "warning" if priority <= 4 else "info"
        ts = item.get("__REALTIME_TIMESTAMP")
        try:
            timestamp = datetime.fromtimestamp(int(ts) / 1_000_000, timezone.utc).isoformat()
        except Exception:
            timestamp = datetime.now(timezone.utc).isoformat()
        unit = str(item.get("_SYSTEMD_UNIT", "system"))
        rows.append({
            "time": timestamp, "service": unit, "level": level, "message": message,
            "file": item.get("CODE_FILE"), "function": item.get("CODE_FUNC"),
            "line": item.get("CODE_LINE"), "pid": item.get("_PID"),
        })
    return rows


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    # Only HTML/CSS in the bounded data-file slot may evolve. The root logreader
    # process, API and trusted JavaScript remain fixed policy-code.
    return log_control_response()


@app.get("/api/logs/live")
def live(service: str = Query("all"), minutes: int = Query(2, ge=1, le=10), lines: int = Query(200, ge=1, le=1000)):
    return {"ok": True, "items": _journal(service, minutes, lines)}


@app.get("/api/logs/service/{service}")
def service_logs(service: str, minutes: int = Query(60, ge=1, le=10080), lines: int = Query(1000, ge=1, le=5000)):
    return {"ok": True, "service": service, "items": _journal(service, minutes, lines)}


@app.get("/api/logs/errors")
def errors(minutes: int = Query(1440, ge=1, le=10080), lines: int = Query(500, ge=1, le=5000)):
    items = _journal("all", minutes, lines)
    return {"ok": True, "items": [x for x in items if x["level"] in {"critical", "error", "warning"} or LEVEL_RE.search(x["message"])]}


@app.get("/api/logs/search")
def search(q: str = Query(..., min_length=2, max_length=200), service: str = Query("all"), minutes: int = Query(1440, ge=1, le=43200), lines: int = Query(1000, ge=1, le=5000)):
    return {"ok": True, "query": q, "items": _journal(service, minutes, lines, q)}


@app.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    await websocket.accept()
    service = websocket.query_params.get("service", "all")
    try:
        _units(service)
        seen: set[tuple[str, str, str]] = set()
        while True:
            for item in _journal(service, 2, 250):
                key = (item["time"], item["service"], item["message"])
                if key not in seen:
                    seen.add(key)
                    await websocket.send_json(item)
            if len(seen) > 5000:
                seen = set(list(seen)[-2000:])
            await asyncio.sleep(1)
    except (WebSocketDisconnect, RuntimeError):
        return


@app.get("/healthz")
def healthz():
    return {
        "ok": True,
        "service": "top40-log-reader",
        "version": VERSION,
        "port": 8042,
        "allowed": sorted(SERVICE_UNITS),
        "ai_mutable_html_css": True,
        "trusted_runtime_mutable_by_ai": False,
        "page_policy": page_policy(),
    }
