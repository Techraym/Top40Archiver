from __future__ import annotations

from datetime import datetime, timedelta
from statistics import mean
from typing import Any

from .db import connect
from .health_engine import init_health

RANGES = {
    "1h": (1, 60),
    "24h": (24, 120),
    "7d": (24 * 7, 168),
}

METRIC_KEYS = (
    "score",
    "cpu_percent",
    "memory_percent",
    "disk_percent",
    "database_latency_ms",
    "queue_pending",
    "queue_downloading",
    "queue_failed",
)


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(str(value))


def _bucket_rows(rows: list[dict[str, Any]], maximum_points: int) -> list[dict[str, Any]]:
    if len(rows) <= maximum_points:
        return rows

    bucket_size = max(1, (len(rows) + maximum_points - 1) // maximum_points)
    result: list[dict[str, Any]] = []
    for offset in range(0, len(rows), bucket_size):
        bucket = rows[offset : offset + bucket_size]
        item: dict[str, Any] = {
            "captured_at": bucket[-1]["captured_at"],
            "database_ok": int(all(bool(row["database_ok"]) for row in bucket)),
            "internet_ok": int(all(bool(row["internet_ok"]) for row in bucket)),
            "downloads_paused": int(any(bool(row["downloads_paused"]) for row in bucket)),
            "worker_count": max(int(row["worker_count"]) for row in bucket),
            "status": bucket[-1]["status"],
        }
        for key in METRIC_KEYS:
            values = [float(row[key]) for row in bucket]
            averaged = mean(values)
            item[key] = round(averaged, 1) if key not in {"score", "queue_pending", "queue_downloading", "queue_failed"} else int(round(averaged))
        result.append(item)
    return result


def _direction(first: float, last: float, tolerance: float) -> str:
    difference = last - first
    if abs(difference) <= tolerance:
        return "stable"
    return "up" if difference > 0 else "down"


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "sample_count": 0,
            "score_average": 0,
            "score_minimum": 0,
            "score_maximum": 0,
            "score_direction": "stable",
            "cpu_average": 0.0,
            "memory_average": 0.0,
            "queue_average": 0.0,
            "failed_change": 0,
            "availability_percent": 0.0,
            "diagnosis": "Er zijn nog onvoldoende historische metingen voor trendanalyse.",
        }

    scores = [float(row["score"]) for row in rows]
    cpu = [float(row["cpu_percent"]) for row in rows]
    memory = [float(row["memory_percent"]) for row in rows]
    queue = [float(row["queue_pending"]) for row in rows]
    available = [bool(row["database_ok"]) and bool(row["internet_ok"]) for row in rows]
    failed_change = int(rows[-1]["queue_failed"]) - int(rows[0]["queue_failed"])
    direction = _direction(scores[0], scores[-1], 2.0)

    findings: list[str] = []
    if direction == "down":
        findings.append("de gezondheidsscore daalt")
    elif direction == "up":
        findings.append("de gezondheidsscore verbetert")
    else:
        findings.append("de gezondheidsscore is stabiel")
    if mean(cpu) >= 70:
        findings.append("de gemiddelde CPU-belasting is verhoogd")
    if mean(memory) >= 75:
        findings.append("het gemiddelde geheugengebruik is verhoogd")
    if failed_change > 0:
        findings.append(f"het aantal mislukte downloads nam met {failed_change} toe")
    elif failed_change < 0:
        findings.append(f"het aantal mislukte downloads nam met {abs(failed_change)} af")

    return {
        "sample_count": len(rows),
        "score_average": round(mean(scores), 1),
        "score_minimum": int(min(scores)),
        "score_maximum": int(max(scores)),
        "score_direction": direction,
        "cpu_average": round(mean(cpu), 1),
        "memory_average": round(mean(memory), 1),
        "queue_average": round(mean(queue), 1),
        "failed_change": failed_change,
        "availability_percent": round(sum(1 for value in available if value) / len(available) * 100.0, 1),
        "diagnosis": "In deze periode is " + ", ".join(findings) + ".",
    }


def health_trends(range_key: str = "24h") -> dict[str, Any]:
    init_health()
    hours, maximum_points = RANGES.get(range_key, RANGES["24h"])
    cutoff = (datetime.now().astimezone() - timedelta(hours=hours)).isoformat(timespec="seconds")
    with connect() as con:
        raw_rows = [
            dict(row)
            for row in con.execute(
                """
                SELECT captured_at,score,status,cpu_percent,memory_percent,disk_percent,
                       database_latency_ms,database_ok,internet_ok,queue_pending,
                       queue_downloading,queue_failed,worker_count,downloads_paused
                FROM health_snapshots
                WHERE captured_at>=?
                ORDER BY id
                """,
                (cutoff,),
            ).fetchall()
        ]

    rows = _bucket_rows(raw_rows, maximum_points)
    return {
        "range": range_key if range_key in RANGES else "24h",
        "hours": hours,
        "raw_sample_count": len(raw_rows),
        "rows": rows,
        "summary": _summary(raw_rows),
    }
