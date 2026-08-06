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
CREATE INDEX IF NOT EXISTS idx_health_snapshots_captured ON health_snapshots(captured_at DESC);
"""


def init_health() -> None:
    with connect() as con:
        con.executescript(HEALTH_SCHEMA)


def _read_cpu_percent() -> float:
    global _LAST_CPU_SAMPLE
    try:
        values = [int(v) for v in Path('/proc/stat').read_text().splitlines()[0].split()[1:]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
    except (OSError, ValueError, IndexError):
        return 0.0
    previous = _LAST_CPU_SAMPLE
    _LAST_CPU_SAMPLE = (idle, total)
    if previous is None:
        time.sleep(0.05)
        return _read_cpu_percent()
    delta = total - previous[1]
    return round(max(0.0, min(100.0, 100.0 * (1.0 - (idle - previous[0]) / delta))), 1) if delta > 0 else 0.0


def _read_memory_percent() -> float:
    try:
        values: dict[str, int] = {}
        for line in Path('/proc/meminfo').read_text().splitlines():
            key, raw = line.split(':', 1)
            values[key] = int(raw.strip().split()[0])
        total = values.get('MemTotal', 0)
        available = values.get('MemAvailable', values.get('MemFree', 0))
        return round(100.0 * (total - available) / total, 1) if total else 0.0
    except (OSError, ValueError):
        return 0.0


def _internet_ok() -> bool:
    for host, port in (('www.youtube.com', 443), ('1.1.1.1', 53)):
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return True
        except OSError:
            pass
    return False


def _database_probe() -> tuple[bool, float]:
    started = time.perf_counter()
    try:
        with sqlite3.connect(DB_PATH, timeout=2.0) as con:
            row = con.execute('PRAGMA quick_check').fetchone()
        ok = bool(row and str(row[0]).casefold() == 'ok')
    except sqlite3.Error:
        ok = False
    return ok, round((time.perf_counter() - started) * 1000.0, 1)


def _score(metrics: dict[str, Any]) -> tuple[int, str, str]:
    value = 100.0
    findings: list[str] = []
    if metrics['cpu_percent'] >= 85: value -= 12; findings.append('hoge CPU-belasting')
    if metrics['memory_percent'] >= 85: value -= 12; findings.append('hoog geheugengebruik')
    if metrics['disk_percent'] >= 97: value -= 30; findings.append('opslag bijna vol')
    elif metrics['disk_percent'] >= 90: value -= 15; findings.append('weinig vrije opslag')
    if not metrics['database_ok']: value -= 35; findings.append('SQLite-controle mislukt')
    elif metrics['database_latency_ms'] >= 250: value -= 10; findings.append('SQLite reageert traag')
    if not metrics['internet_ok']: value -= 20; findings.append('internet niet bereikbaar')
    if metrics['queue_failed'] >= 10: value -= min(18, 5 + metrics['queue_failed'] / 4); findings.append('veel mislukte downloads')
    if metrics['worker_count'] > 1: value -= min(15, (metrics['worker_count'] - 1) * 5); findings.append('meer dan één downloadworker')
    score = max(0, min(100, int(round(value))))
    status = 'good' if score >= 85 else 'attention' if score >= 65 else 'critical'
    diagnosis = 'Alle gecontroleerde onderdelen functioneren normaal.' if not findings else 'Aandacht voor ' + ', '.join(findings) + '.'
    return score, status, diagnosis


def collect_health_snapshot() -> dict[str, Any]:
    init_health()
    with _HEALTH_LOCK:
        with connect() as con:
            settings = get_settings(con)
            counts = {row['download_status']: int(row['c']) for row in con.execute('SELECT download_status,COUNT(*) c FROM tracks GROUP BY download_status')}
        path = Path(settings.get('download_dir', '/')).expanduser()
        probe = path
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        try:
            usage = shutil.disk_usage(probe)
            disk_percent = round(usage.used / usage.total * 100, 1)
            disk_free_gb = round(usage.free / 1024**3, 1)
        except OSError:
            disk_percent, disk_free_gb = 100.0, 0.0
        db_ok, db_ms = _database_probe()
        metrics: dict[str, Any] = {
            'captured_at': now_iso(), 'cpu_percent': _read_cpu_percent(),
            'memory_percent': _read_memory_percent(), 'disk_percent': disk_percent,
            'disk_free_gb': disk_free_gb, 'database_ok': db_ok,
            'database_latency_ms': db_ms, 'internet_ok': _internet_ok(),
            'queue_pending': counts.get('pending', 0), 'queue_downloading': counts.get('downloading', 0),
            'queue_failed': counts.get('failed', 0),
            'worker_count': max(1, int(settings.get('download_workers', '1') or 1)),
            'downloads_paused': settings.get('operations_download_paused', '0') == '1',
        }
        score, status, diagnosis = _score(metrics)
        metrics.update(score=score, status=status, diagnosis=diagnosis)
        with connect() as con:
            cursor = con.execute('''INSERT INTO health_snapshots(captured_at,score,status,cpu_percent,memory_percent,disk_percent,disk_free_gb,database_ok,database_latency_ms,internet_ok,queue_pending,queue_downloading,queue_failed,worker_count,downloads_paused,diagnosis) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
                metrics['captured_at'], score, status, metrics['cpu_percent'], metrics['memory_percent'], disk_percent, disk_free_gb,
                int(db_ok), db_ms, int(metrics['internet_ok']), metrics['queue_pending'], metrics['queue_downloading'], metrics['queue_failed'],
                metrics['worker_count'], int(metrics['downloads_paused']), diagnosis))
            metrics['id'] = int(cursor.lastrowid)
        return metrics


def latest_health() -> dict[str, Any]:
    init_health()
    with connect() as con:
        row = con.execute('SELECT * FROM health_snapshots ORDER BY id DESC LIMIT 1').fetchone()
    return dict(row) if row else collect_health_snapshot()


def health_history(hours: int = 24, limit: int = 500) -> list[dict[str, Any]]:
    init_health()
    cutoff = (datetime.now().astimezone() - timedelta(hours=max(1, hours))).isoformat(timespec='seconds')
    with connect() as con:
        rows = con.execute('SELECT * FROM health_snapshots WHERE captured_at>=? ORDER BY id DESC LIMIT ?', (cutoff, max(1, min(2000, limit)))).fetchall()
    return [dict(row) for row in reversed(rows)]


def start_health_collector() -> None:
    global _COLLECTOR_STARTED
    if _COLLECTOR_STARTED: return
    _COLLECTOR_STARTED = True
    def loop() -> None:
        while True:
            try: collect_health_snapshot()
            except Exception as exc: print({'state':'health-error','message':str(exc)[-1000:]}, flush=True)
            time.sleep(HEALTH_INTERVAL_SECONDS)
    threading.Thread(target=loop, name='top40-health', daemon=True).start()
