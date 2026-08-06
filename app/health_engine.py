from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import shutil
import socket
import sqlite3
import threading
import time
from typing import Any

from .config import DB_PATH
from .db import connect, get_settings, now_iso

HEALTH_INTERVAL_SECONDS = 60.0
_HEALTH_LOCK = threading.Lock()
_COLLECTOR_STARTED = False
_LAST_CPU_SAMPLE: tuple[int, int] | None = None

HEALTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS health_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  captured_at TEXT NOT NULL,
  score INTEGER NOT NULL,
  status TEXT NOT NULL,
  cpu_percent REAL NOT NULL,
  memory_percent REAL NOT NULL,
  disk_percent REAL NOT NULL,
  disk_free_gb REAL NOT NULL,
  database_ok INTEGER NOT NULL,
  database_latency_ms REAL NOT NULL,
  internet_ok INTEGER NOT NULL,
  queue_pending INTEGER NOT NULL,
  queue_downloading INTEGER NOT NULL,
  queue_failed INTEGER NOT NULL,
  worker_count INTEGER NOT NULL,
  downloads_paused INTEGER NOT NULL,
  diagnosis TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_health_snapshots_captured
ON health_snapshots(captured_at DESC);

CREATE TABLE IF NOT EXISTS health_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  component TEXT NOT NULL,
  severity TEXT NOT NULL,
  event_key TEXT NOT NULL,
  message TEXT NOT NULL,
  snapshot_id INTEGER REFERENCES health_snapshots(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_health_events_created
ON health_events(created_at DESC);

CREATE TABLE IF NOT EXISTS health_thresholds (
  key TEXT PRIMARY KEY,
  value REAL NOT NULL,
  updated_at TEXT NOT NULL
);
"""

DEFAULT_THRESHOLDS = {
    "cpu_warning": 85.0,
    "memory_warning": 85.0,
    "disk_warning": 90.0,
    "disk_critical": 97.0,
    "database_latency_warning_ms": 250.0,
    "failed_downloads_warning": 10.0,
    "queue_warning": 500.0,
}


def init_health() -> None:
    with connect() as con:
        con.executescript(HEALTH_SCHEMA)
        stamp = now_iso()
        for key, value in DEFAULT_THRESHOLDS.items():
            con.execute(
                "INSERT OR IGNORE INTO health_thresholds(key,value,updated_at) VALUES(?,?,?)",
                (key, value, stamp),
            )


def _read_cpu_percent() -> float:
    global _LAST_CPU_SAMPLE
    try:
        fields = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()[1:]
        values = [int(value) for value in fields]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
    except (OSError, ValueError, IndexError):
        return 0.0

    previous = _LAST_CPU_SAMPLE
    _LAST_CPU_SAMPLE = (idle, total)
    if previous is None:
        time.sleep(0.08)
        return _read_cpu_percent()

    idle_delta = idle - previous[0]
    total_delta = total - previous[1]
    if total_delta <= 0:
        return 0.0
    return round(max(0.0, min(100.0, 100.0 * (1.0 - idle_delta / total_delta))), 1)


def _read_memory_percent() -> float:
    try:
        values: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            name, raw = line.split(":", 1)
            values[name] = int(raw.strip().split()[0])
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", values.get("MemFree", 0))
        return round(100.0 * (total - available) / total, 1) if total else 0.0
    except (OSError, ValueError):
        return 0.0


def _internet_ok() -> bool:
    for host, port in (("www.youtube.com", 443), ("1.1.1.1", 53)):
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return True
        except OSError:
            continue
    return False


def _database_probe() -> tuple[bool, float]:
    started = time.perf_counter()
    try:
        with sqlite3.connect(DB_PATH, timeout=2.0) as con:
            result = con.execute("PRAGMA quick_check").fetchone()
        ok = bool(result and str(result[0]).casefold() == "ok")
    except sqlite3.Error:
        ok = False
    return ok, round((time.perf_counter() - started) * 1000.0, 1)


def _thresholds(con) -> dict[str, float]:
    values = dict(DEFAULT_THRESHOLDS)
    for row in con.execute("SELECT key,value FROM health_thresholds"):
        values[str(row["key"])] = float(row["value"])
    return values


def _score_and_diagnosis(metrics: dict[str, Any], thresholds: dict[str, float]) -> tuple[int, str, str]:
    score = 100.0
    findings: list[str] = []

    cpu = float(metrics["cpu_percent"])
    memory = float(metrics["memory_percent"])
    disk = float(metrics["disk_percent"])
    if cpu >= thresholds["cpu_warning"]:
        score -= min(18.0, (cpu - thresholds["cpu_warning"]) * 1.2 + 6.0)
        findings.append("hoge CPU-belasting")
    if memory >= thresholds["memory_warning"]:
        score -= min(18.0, (memory - thresholds["memory_warning"]) + 6.0)
        findings.append("hoog geheugengebruik")
    if disk >= thresholds["disk_critical"]:
        score -= 30.0
        findings.append("opslag bijna vol")
    elif disk >= thresholds["disk_warning"]:
        score -= 15.0
        findings.append("weinig vrije opslag")
    if not metrics["database_ok"]:
        score -= 35.0
        findings.append("SQLite-controle mislukt")
    elif metrics["database_latency_ms"] >= thresholds["database_latency_warning_ms"]:
        score -= 10.0
        findings.append("SQLite reageert traag")
    if not metrics["internet_ok"]:
        score -= 20.0
        findings.append("internetverbinding niet bereikbaar")
    if metrics["queue_failed"] >= thresholds["failed_downloads_warning"]:
        score -= min(18.0, 5.0 + metrics["queue_failed"] / 4.0)
        findings.append("veel mislukte downloads")
    if metrics["queue_pending"] >= thresholds["queue_warning"]:
        score -= 8.0
        findings.append("grote downloadwachtrij")
    if metrics["worker_count"] > 2:
        score -= 8.0
        findings.append("hoge workerparalleliteit")
    if metrics["downloads_paused"]:
        score -= 5.0
        findings.append("downloads door AI Operations gepauzeerd")

    score_int = max(0, min(100, int(round(score))))
    status = "good" if score_int >= 85 else "attention" if score_int >= 65 else "critical"
    if findings:
        diagnosis = "De gezondheid wordt beïnvloed door " + ", ".join(findings) + "."
    else:
        diagnosis = "Alle gecontroleerde onderdelen functioneren binnen de ingestelde grenzen."
    return score_int, status, diagnosis


def collect_health_snapshot() -> dict[str, Any]:
    init_health()
    with _HEALTH_LOCK:
        with connect() as con:
            settings = get_settings(con)
            thresholds = _thresholds(con)
            counts = {row["download_status"]: int(row["c"]) for row in con.execute(
                "SELECT download_status,COUNT(*) AS c FROM tracks GROUP BY download_status"
            )}

        download_dir = Path(settings.get("download_dir", "/")).expanduser()
        probe = download_dir
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        try:
            usage = shutil.disk_usage(probe)
            disk_percent = round(usage.used / usage.total * 100.0, 1) if usage.total else 0.0
            disk_free_gb = round(usage.free / (1024 ** 3), 1)
        except OSError:
            disk_percent = 100.0
            disk_free_gb = 0.0

        database_ok, database_latency_ms = _database_probe()
        metrics: dict[str, Any] = {
            "captured_at": now_iso(),
            "cpu_percent": _read_cpu_percent(),
            "memory_percent": _read_memory_percent(),
            "disk_percent": disk_percent,
            "disk_free_gb": disk_free_gb,
            "database_ok": database_ok,
            "database_latency_ms": database_latency_ms,
            "internet_ok": _internet_ok(),
            "queue_pending": counts.get("pending", 0),
            "queue_downloading": counts.get("downloading", 0),
            "queue_failed": counts.get("failed", 0),
            "worker_count": max(1, int(settings.get("download_workers", "1") or 1)),
            "downloads_paused": settings.get("operations_download_paused", "0") == "1",
        }
        score, status, diagnosis = _score_and_diagnosis(metrics, thresholds)
        metrics.update({"score": score, "status": status, "diagnosis": diagnosis})

        with connect() as con:
            cursor = con.execute(
                """
                INSERT INTO health_snapshots(
                  captured_at,score,status,cpu_percent,memory_percent,disk_percent,
                  disk_free_gb,database_ok,database_latency_ms,internet_ok,
                  queue_pending,queue_downloading,queue_failed,worker_count,
                  downloads_paused,diagnosis
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    metrics["captured_at"], score, status, metrics["cpu_percent"],
                    metrics["memory_percent"], disk_percent, disk_free_gb,
                    int(database_ok), database_latency_ms, int(metrics["internet_ok"]),
                    metrics["queue_pending"], metrics["queue_downloading"],
                    metrics["queue_failed"], metrics["worker_count"],
                    int(metrics["downloads_paused"]), diagnosis,
                ),
            )
            metrics["id"] = int(cursor.lastrowid)
            _record_events(con, metrics, thresholds)
        return metrics


def _record_events(con, metrics: dict[str, Any], thresholds: dict[str, float]) -> None:
    events: list[tuple[str, str, str, str]] = []
    if metrics["disk_percent"] >= thresholds["disk_critical"]:
        events.append(("storage", "critical", "disk-critical", "De opslag is vrijwel volledig gevuld."))
    elif metrics["disk_percent"] >= thresholds["disk_warning"]:
        events.append(("storage", "warning", "disk-warning", "De vrije opslagruimte neemt sterk af."))
    if not metrics["database_ok"]:
        events.append(("database", "critical", "database-check", "SQLite quick_check is mislukt."))
    if not metrics["internet_ok"]:
        events.append(("network", "warning", "internet-unreachable", "De externe netwerkcontrole is mislukt."))
    if metrics["worker_count"] > 2:
        events.append(("downloads", "warning", "workers-high", f"Er zijn {metrics['worker_count']} downloadworkers ingesteld."))
    if metrics["queue_failed"] >= thresholds["failed_downloads_warning"]:
        events.append(("downloads", "warning", "failed-high", f"Er staan {metrics['queue_failed']} mislukte downloads geregistreerd."))

    cutoff = (datetime.now().astimezone() - timedelta(minutes=30)).isoformat(timespec="seconds")
    for component, severity, event_key, message in events:
        exists = con.execute(
            "SELECT 1 FROM health_events WHERE event_key=? AND created_at>=? LIMIT 1",
            (event_key, cutoff),
        ).fetchone()
        if not exists:
            con.execute(
                "INSERT INTO health_events(created_at,component,severity,event_key,message,snapshot_id) VALUES(?,?,?,?,?,?)",
                (metrics["captured_at"], component, severity, event_key, message, metrics["id"]),
            )


def latest_health() -> dict[str, Any]:
    init_health()
    with connect() as con:
        row = con.execute("SELECT * FROM health_snapshots ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else collect_health_snapshot()


def health_history(hours: int = 24, limit: int = 500) -> list[dict[str, Any]]:
    init_health()
    cutoff = (datetime.now().astimezone() - timedelta(hours=max(1, hours))).isoformat(timespec="seconds")
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM health_snapshots WHERE captured_at>=? ORDER BY id DESC LIMIT ?",
            (cutoff, max(1, min(2000, limit))),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def health_events(limit: int = 100) -> list[dict[str, Any]]:
    init_health()
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM health_events ORDER BY id DESC LIMIT ?",
            (max(1, min(500, limit)),),
        ).fetchall()
    return [dict(row) for row in rows]


def start_health_collector() -> None:
    global _COLLECTOR_STARTED
    if _COLLECTOR_STARTED:
        return
    _COLLECTOR_STARTED = True

    def loop() -> None:
        while True:
            try:
                snapshot = collect_health_snapshot()
                print(
                    {
                        "state": "health",
                        "score": snapshot["score"],
                        "cpu": snapshot["cpu_percent"],
                        "memory": snapshot["memory_percent"],
                        "queue": snapshot["queue_pending"],
                    },
                    flush=True,
                )
            except Exception as exc:
                print({"state": "health-error", "message": str(exc)[-1000:]}, flush=True)
            time.sleep(HEALTH_INTERVAL_SECONDS)

    threading.Thread(target=loop, name="top40-health", daemon=True).start()
