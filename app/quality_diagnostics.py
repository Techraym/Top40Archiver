from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from .config import DB_PATH

AI_DIR = Path('/var/lib/top40-archiver/ai')
DIAGNOSTICS_FILE = AI_DIR / 'diagnostics.json'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _run(*cmd: str, timeout: int = 12) -> dict[str, object]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return {'ok': p.returncode == 0, 'returncode': p.returncode, 'stdout': p.stdout[-8000:], 'stderr': p.stderr[-4000:]}
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}


def quality_check() -> dict[str, object]:
    result: dict[str, object] = {'checked_at': _now(), 'database': str(DB_PATH), 'ok': True, 'checks': {}}
    try:
        uri = f"file:{DB_PATH}?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=5)
        con.row_factory = sqlite3.Row
        checks = {
            'tracks': "SELECT COUNT(*) FROM tracks",
            'empty_artist': "SELECT COUNT(*) FROM tracks WHERE trim(coalesce(artist,''))=''",
            'empty_title': "SELECT COUNT(*) FROM tracks WHERE trim(coalesce(title,''))=''",
            'failed_downloads': "SELECT COUNT(*) FROM tracks WHERE download_status='failed'",
            'active_downloads': "SELECT COUNT(*) FROM tracks WHERE download_status='downloading'",
            'duplicates': "SELECT COUNT(*) FROM (SELECT normalized_artist,normalized_title,COUNT(*) n FROM tracks GROUP BY 1,2 HAVING n>1)",
            'duplicate_chart_positions': "SELECT COUNT(*) FROM (SELECT edition_id,position,COUNT(*) n FROM chart_entries GROUP BY 1,2 HAVING n>1)",
            'missing_covers': "SELECT COUNT(*) FROM tracks WHERE download_status='downloaded' AND coalesce(cover_url,'')=''",
        }
        for key, sql in checks.items():
            try:
                result['checks'][key] = int(con.execute(sql).fetchone()[0])
            except sqlite3.Error as exc:
                result['checks'][key] = {'error': str(exc)}
                result['ok'] = False
        integrity = con.execute('PRAGMA quick_check').fetchone()[0]
        result['checks']['quick_check'] = integrity
        result['ok'] = bool(result['ok'] and integrity == 'ok')
        con.close()
    except Exception as exc:
        result['ok'] = False
        result['error'] = str(exc)
    return result


def ollama_status() -> dict[str, object]:
    started = time.monotonic()
    try:
        req = Request('http://127.0.0.1:11434/api/version', headers={'User-Agent': 'Top40Archiver/1.15.4'})
        with urlopen(req, timeout=4) as response:
            data = json.loads(response.read().decode('utf-8'))
        return {'reachable': True, 'version': data.get('version'), 'latency_ms': round((time.monotonic()-started)*1000)}
    except Exception as exc:
        return {'reachable': False, 'error': str(exc), 'latency_ms': round((time.monotonic()-started)*1000)}


def collect_diagnostics(write_file: bool = True) -> dict[str, object]:
    disk = shutil.disk_usage('/opt/top40-archiver')
    services = {}
    for unit in ('top40-archiver-web.service','top40-archiver-download.service','top40-archiver-ai.service','ollama.service'):
        services[unit] = {
            'active': _run('systemctl','is-active',unit),
            'restarts': _run('systemctl','show',unit,'-p','NRestarts','--value'),
        }
    report = {
        'generated_at': _now(),
        'version': Path('/opt/top40-archiver/VERSION').read_text(encoding='utf-8').strip() if Path('/opt/top40-archiver/VERSION').exists() else 'unknown',
        'services': services,
        'disk': {'total_gb': round(disk.total/2**30,1), 'free_gb': round(disk.free/2**30,1), 'used_percent': round((disk.used/disk.total)*100,1)},
        'memory': _run('free','-m'),
        'load': os.getloadavg(),
        'database_size_mb': round(Path(DB_PATH).stat().st_size/2**20,2) if Path(DB_PATH).exists() else None,
        'quality': quality_check(),
        'ollama': ollama_status(),
        'warnings': _run('journalctl','-p','warning','--since','-30 minutes','--no-pager','-n','100'),
    }
    if write_file:
        AI_DIR.mkdir(parents=True, exist_ok=True)
        tmp = DIAGNOSTICS_FILE.with_suffix('.tmp')
        tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(DIAGNOSTICS_FILE)
    return report
