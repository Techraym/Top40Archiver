from __future__ import annotations

from datetime import datetime
import re
import subprocess
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from .db import connect

router = APIRouter()

UNITS = (
    "top40-archiver.service",
    "top40-archiver-check.service",
    "top40-archiver-web.service",
)

LEVEL_PATTERNS = {
    "error": re.compile(r"\b(error|fout|failed|failure|exception|traceback|429|403|unavailable|bot|captcha)\b", re.I),
    "warning": re.compile(r"\b(warn|warning|retry|timeout|timed out|niet beschikbaar|sign in)\b", re.I),
}


def _classify(message: str) -> str:
    if LEVEL_PATTERNS["error"].search(message):
        return "error"
    if LEVEL_PATTERNS["warning"].search(message):
        return "warning"
    return "info"


def _journal_lines(limit: int) -> tuple[list[dict[str, Any]], str | None]:
    command = ["journalctl", "--no-pager", "-o", "short-iso", "-n", str(limit)]
    for unit in UNITS:
        command.extend(["-u", unit])

    try:
        process = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=6,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], f"journalctl kon niet worden gelezen: {exc}"

    raw = process.stdout.splitlines()
    if process.returncode not in (0, 1) and not raw:
        return [], (process.stderr or "journalctl gaf een onbekende fout").strip()

    rows = []
    for index, line in enumerate(raw):
        clean = line.rstrip()
        if not clean or clean.startswith("-- No entries --"):
            continue
        rows.append(
            {
                "id": f"journal-{index}-{hash(clean)}",
                "source": "systemd",
                "level": _classify(clean),
                "message": clean,
            }
        )
    return rows, None


def _database_failures(limit: int) -> list[dict[str, Any]]:
    with connect() as con:
        records = con.execute(
            """
            SELECT id,artist,title,download_attempts,error_message,updated_at
            FROM tracks
            WHERE download_status='failed' AND error_message IS NOT NULL
            ORDER BY updated_at DESC,id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [
        {
            "id": f"track-{row['id']}-{row['updated_at']}",
            "source": "download",
            "level": "error",
            "message": (
                f"{row['updated_at']} · {row['artist']} — {row['title']} · "
                f"poging {row['download_attempts']}: {row['error_message']}"
            ),
        }
        for row in records
    ]


@router.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request):
    templates = Jinja2Templates(directory="app/templates")
    return templates.TemplateResponse(
        request,
        "logs.html",
        {"generated_at": datetime.now().astimezone().isoformat(timespec="seconds")},
    )


@router.get("/api/logs")
def logs_api(
    limit: int = Query(300, ge=50, le=1000),
    level: str = Query("all", pattern="^(all|info|warning|error)$"),
    q: str = Query("", max_length=200),
):
    journal, journal_error = _journal_lines(limit)
    rows = _database_failures(min(limit, 200)) + journal

    query = q.strip().casefold()
    if query:
        rows = [row for row in rows if query in row["message"].casefold()]
    if level != "all":
        rows = [row for row in rows if row["level"] == level]

    rows = rows[-limit:]
    counts = {"info": 0, "warning": 0, "error": 0}
    for row in rows:
        counts[row["level"]] = counts.get(row["level"], 0) + 1

    return JSONResponse(
        {
            "ok": journal_error is None,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "rows": rows,
            "counts": counts,
            "journal_error": journal_error,
            "units": list(UNITS),
        }
    )
