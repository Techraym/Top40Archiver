from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .ai_session_console import operator_context, scope_held
from .config import DATA_DIR
from .db import connect, get_settings
from .service_common import _parse_edition_key, _persist_chart
from .service_queue import process_queue
from .top40 import fetch_chart_from_website

TZ = ZoneInfo("Europe/Amsterdam")
STATE_FILE = DATA_DIR / "ai" / "chart-freshness.json"
RETRY_MINUTES = 20
PUBLISH_WEEKDAY = 4
PUBLISH_HOUR = 12
MAX_CATCHUP_WEEKS_PER_RUN = 12


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


def _monday(pair: tuple[int, int]) -> date:
    return date.fromisocalendar(int(pair[0]), int(pair[1]), 1)


def missing_pairs(last: tuple[int, int] | None, expected: tuple[int, int]) -> list[tuple[int, int]]:
    if last is None:
        return [expected]
    cursor = _monday(last) + timedelta(days=7)
    end = _monday(expected)
    result: list[tuple[int, int]] = []
    while cursor <= end and len(result) < MAX_CATCHUP_WEEKS_PER_RUN:
        iso = cursor.isocalendar()
        result.append((iso.year, iso.week))
        cursor += timedelta(days=7)
    return result


def _fetch_target_week(chart_type: str, pair: tuple[int, int]) -> dict:
    target = _monday(pair)
    chart = fetch_chart_from_website(target, chart_type)
    actual = (chart.year, chart.week)
    if actual != pair:
        return {
            "ok": False,
            "chart_type": chart_type,
            "requested": f"{pair[0]}-W{pair[1]:02d}",
            "actual": chart.edition_key,
            "reason": "edition_mismatch",
        }
    persisted = _persist_chart(chart, False)
    ids = list(persisted.get("new_track_ids", []) or [])
    downloads = process_queue(track_ids=ids) if ids else []
    return {
        "ok": True,
        "chart_type": chart_type,
        "requested": f"{pair[0]}-W{pair[1]:02d}",
        "actual": chart.edition_key,
        "new_track_ids": ids,
        "downloads": len(downloads),
        "persist": persisted,
    }


def _catch_up_chart(chart_type: str, before: dict, expected: tuple[int, int]) -> list[dict]:
    last_value = before.get("top40" if chart_type == "top40" else "tipparade")
    last = _edition_pair(last_value)
    steps: list[dict] = []
    for pair in missing_pairs(last, expected):
        try:
            step = _fetch_target_week(chart_type, pair)
        except Exception as exc:
            step = {
                "ok": False,
                "chart_type": chart_type,
                "requested": f"{pair[0]}-W{pair[1]:02d}",
                "error": str(exc)[-1500:],
            }
        steps.append(step)
        if not step.get("ok"):
            break
    return steps


def run_freshness_check(force: bool = False) -> dict:
    now = _now()
    before = _state()
    held = scope_held("charts")
    if before["ok"]:
        payload = {
            "ok": True,
            "action": "none",
            "before": before,
            "after": before,
            "checked_at": now.isoformat(),
            "operator_hold": held,
            "operator_guidance": operator_context("charts"),
        }
        _write(payload)
        return payload
    if held:
        payload = {
            "ok": True,
            "action": "operator_hold",
            "before": before,
            "after": before,
            "checked_at": now.isoformat(),
            "operator_hold": True,
            "operator_guidance": operator_context("charts"),
            "reason": "Menselijke operator heeft automatische chart-mutaties gepauzeerd; freshness-monitoring blijft actief.",
        }
        _write(payload)
        return payload
    if not force and _recent_attempt(now):
        return {"ok": False, "action": "cooldown", "before": before, "after": before, "checked_at": now.isoformat()}

    expected = (int(before["expected_year"]), int(before["expected_week"]))
    result: dict = {
        "ok": False,
        "action": "refresh_current_charts",
        "before": before,
        "attempted_at": now.isoformat(),
        "steps": [],
        "operator_hold": False,
        "operator_guidance": operator_context("charts"),
    }
    for chart_type in list(before["stale"]):
        result["steps"].extend(_catch_up_chart(chart_type, before, expected))

    after = _state()
    result["after"] = after
    result["ok"] = bool(after["ok"])
    result["completed_at"] = _now().isoformat()
    result["retry_in_minutes"] = 0 if result["ok"] else RETRY_MINUTES
    _write(result)
    return result


def freshness_status() -> dict:
    current = _state()
    try:
        stored = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        stored = {}
    return {"current": current, "last_run": stored}
