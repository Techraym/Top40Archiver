from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import DATA_DIR
from .db import connect, get_settings
from .service import import_latest
from .service_common import _parse_edition_key, _persist_chart
from .service_queue import process_queue
from .top40 import fetch_chart_from_website

TZ = ZoneInfo("Europe/Amsterdam")
STATE_FILE = DATA_DIR / "ai" / "chart-freshness.json"
RETRY_MINUTES = 20
PUBLISH_WEEKDAY = 4  # vrijdag
PUBLISH_HOUR = 12


def _now() -> datetime:
    return datetime.now(TZ)


def expected_latest_pair(now: datetime | None = None) -> tuple[int, int]:
    current = (now or _now()).astimezone(TZ)
    iso = current.date().isocalendar()
    published_this_week = current.weekday() > PUBLISH_WEEKDAY or (
        current.weekday() == PUBLISH_WEEKDAY and current.hour >= PUBLISH_HOUR
    )
    if published_this_week:
        return iso.year, iso.week
    previous = current.date() - timedelta(days=7)
    prev_iso = previous.isocalendar()
    return prev_iso.year, prev_iso.week


def _edition_pair(value: str | None) -> tuple[int, int] | None:
    return _parse_edition_key(str(value or ""))


def _state() -> dict:
    with connect() as con:
        settings = get_settings(con)
    expected = expected_latest_pair()
    top40 = _edition_pair(settings.get("last_edition"))
    tipparade = _edition_pair(settings.get("last_tipparade_edition"))
    enabled_tip = settings.get("tipparade_enabled", "1") == "1"
    stale = []
    if top40 is None or top40 < expected:
        stale.append("top40")
    if enabled_tip and (tipparade is None or tipparade < expected):
        stale.append("tipparade")
    return {
        "expected_year": expected[0],
        "expected_week": expected[1],
        "expected_edition": f"{expected[0]}-W{expected[1]:02d}",
        "top40": f"{top40[0]}-W{top40[1]:02d}" if top40 else None,
        "tipparade": f"{tipparade[0]}-W{tipparade[1]:02d}" if tipparade else None,
        "tipparade_enabled": enabled_tip,
        "stale": stale,
        "ok": not stale,
    }


def _write(payload: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def _recent_attempt(now: datetime) -> bool:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        stamp = datetime.fromisoformat(str(data.get("attempted_at") or ""))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=TZ)
        return now - stamp.astimezone(TZ) < timedelta(minutes=RETRY_MINUTES)
    except Exception:
        return False


def _website_fallback(chart_type: str, expected: tuple[int, int]) -> dict:
    chart = fetch_chart_from_website(None, chart_type)  # current website edition
    actual = (chart.year, chart.week)
    if actual < expected:
        return {"ok": False, "chart_type": chart_type, "actual": chart.edition_key, "reason": "source_still_old"}
    result = _persist_chart(chart, False)
    ids = result.get("new_track_ids", [])
    downloads = process_queue(track_ids=ids) if ids else []
    return {
        "ok": True,
        "chart_type": chart_type,
        "actual": chart.edition_key,
        "new_track_ids": ids,
        "downloads": len(downloads),
    }


def run_freshness_check(force: bool = False) -> dict:
    now = _now()
    before = _state()
    if before["ok"]:
        payload = {"ok": True, "action": "none", "before": before, "after": before, "checked_at": now.isoformat()}
        _write(payload)
        return payload
    if not force and _recent_attempt(now):
        return {"ok": False, "action": "cooldown", "before": before, "after": before, "checked_at": now.isoformat()}

    result: dict = {"ok": False, "action": "refresh_current_charts", "before": before, "attempted_at": now.isoformat(), "steps": []}
    try:
        normal = import_latest(False)
        result["steps"].append({"source": "normal", "ok": True, "result": normal})
    except Exception as exc:
        result["steps"].append({"source": "normal", "ok": False, "error": str(exc)[-1500:]})

    middle = _state()
    expected = (middle["expected_year"], middle["expected_week"])
    for chart_type in list(middle["stale"]):
        try:
            fallback = _website_fallback(chart_type, expected)
            result["steps"].append({"source": "website_fallback", **fallback})
        except Exception as exc:
            result["steps"].append({"source": "website_fallback", "chart_type": chart_type, "ok": False, "error": str(exc)[-1500:]})

    after = _state()
    result["after"] = after
    result["ok"] = bool(after["ok"])
    result["completed_at"] = _now().isoformat()
    _write(result)
    return result


def freshness_status() -> dict:
    current = _state()
    try:
        stored = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        stored = {}
    return {"current": current, "last_run": stored}
