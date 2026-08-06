#!/usr/bin/env bash
set -euo pipefail

APP="/opt/top40-archiver"
DB="/var/lib/top40-archiver/top40.sqlite3"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="$APP/backups/history_queue_limit_$STAMP"

cd "$APP"

echo "=== Backup maken ==="
sudo install -d -o root -g root -m 750 "$APP/backups"
sudo install -d -o root -g root -m 750 "$BACKUP"
sudo cp -a app/service_history.py app/templates/index.html "$BACKUP/"

if [[ -f "$DB" ]]; then
  # De backup wordt als root gemaakt. Zo zijn schrijfrechten op de applicatie-
  # backupmap niet afhankelijk van de servicegebruiker of rechten op bovenliggende mappen.
  sudo sqlite3 "$DB" ".backup '$BACKUP/top40.sqlite3'"
  sudo chmod 640 "$BACKUP/top40.sqlite3"
fi

echo "=== Wachtrijbegrenzing toevoegen ==="
sudo python3 - <<'PY'
from pathlib import Path

path = Path('/opt/top40-archiver/app/service_history.py')
text = path.read_text(encoding='utf-8')

helper = '''\n\ndef _active_download_queue_count() -> int:\n    """Aantal persistent opgeslagen actieve downloadtaken in SQLite."""\n    with connect() as con:\n        row = con.execute(\n            """\n            SELECT COUNT(*) AS c\n            FROM tracks\n            WHERE download_status IN ('pending','downloading')\n            """\n        ).fetchone()\n    return int(row["c"] if row else 0)\n\n\ndef _history_queue_gate(settings: dict) -> dict | None:\n    """Stop alleen nieuwe historie-import wanneer de SQLite-wachtrij vol is."""\n    limit = max(1, int(settings.get("history_download_limit", "100") or 100))\n    active = _active_download_queue_count()\n    if active < limit:\n        return None\n    return {\n        "skipped": True,\n        "queue_limited": True,\n        "completed": False,\n        "active_queue": active,\n        "queue_limit": limit,\n        "message": (\n            f"Historische import wacht: {active} van maximaal {limit} nummers "\n            "staan in de persistente SQLite-wachtrij. Downloads blijven doorgaan."\n        ),\n        "downloads": 0,\n        "download_queue": "top40-archiver-download.service",\n    }\n'''

if 'def _history_queue_gate(' not in text:
    marker = '\ndef run_history_batch():\n'
    if marker not in text:
        raise SystemExit('FOUT: run_history_batch niet gevonden')
    text = text.replace(marker, helper + marker, 1)

needle = '''    if settings.get("history_enabled") != "1":\n        return {"skipped": True, "message": "Historische import staat gepauzeerd"}\n\n    batch = max(1, int(settings["history_batch_weeks"]))\n'''
replacement = '''    if settings.get("history_enabled") != "1":\n        return {"skipped": True, "message": "Historische import staat gepauzeerd"}\n\n    queue_gate = _history_queue_gate(settings)\n    if queue_gate:\n        return queue_gate\n\n    batch = max(1, int(settings["history_batch_weeks"]))\n'''
if 'queue_gate = _history_queue_gate(settings)' not in text:
    if needle not in text:
        raise SystemExit('FOUT: invoegpunt voor wachtrijcontrole niet gevonden')
    text = text.replace(needle, replacement, 1)

loop_needle = '''    for chart_type in ("top40", "tipparade"):\n        with connect() as con:\n            chart_settings = get_settings(con)\n'''
loop_replacement = '''    for chart_type in ("top40", "tipparade"):\n        with connect() as con:\n            chart_settings = get_settings(con)\n\n        queue_gate = _history_queue_gate(chart_settings)\n        if queue_gate:\n            results[chart_type] = queue_gate\n            break\n'''
if 'results[chart_type] = queue_gate' not in text:
    if loop_needle not in text:
        raise SystemExit('FOUT: lijstlus niet gevonden')
    text = text.replace(loop_needle, loop_replacement, 1)

path.write_text(text, encoding='utf-8')
PY

echo "=== Beheerinstelling verduidelijken ==="
sudo python3 - <<'PY'
from pathlib import Path

path = Path('/opt/top40-archiver/app/templates/index.html')
text = path.read_text(encoding='utf-8')

old = '''<label>Downloads per historische run<input type="number" min="0" max="100" name="history_download_limit" value="{{ settings.history_download_limit }}"></label>'''
new = '''<label>Maximale actieve wachtrij<input type="number" min="1" max="1000" name="history_download_limit" value="{{ settings.history_download_limit }}"><small>Nieuwe historische weken wachten zodra dit aantal pending/bezig is bereikt. De wachtrij blijft in SQLite bewaard.</small></label>'''

if old in text:
    text = text.replace(old, new, 1)
elif 'Maximale actieve wachtrij' not in text:
    raise SystemExit('FOUT: instelling history_download_limit niet gevonden')

for version in ('22','23','24','25','26','27','28'):
    text = text.replace(f'/static/style.css?v={version}', '/static/style.css?v=29')
    text = text.replace(f'/static/live.js?v={version}', '/static/live.js?v=29')

path.write_text(text, encoding='utf-8')
PY

echo "=== Veilige instellingen toepassen ==="
sudo -u top40archiver sqlite3 "$DB" <<'SQL'
INSERT INTO settings(key,value) VALUES('history_batch_weeks','1')
ON CONFLICT(key) DO UPDATE SET value='1';
INSERT INTO settings(key,value) VALUES('history_download_limit','100')
ON CONFLICT(key) DO UPDATE SET value='100';
SQL

echo "=== Syntaxcontrole ==="
sudo -u top40archiver "$APP/venv/bin/python" -m py_compile app/service_history.py

echo "=== Services herstarten ==="
sudo systemctl restart top40-archiver-history.timer
sudo systemctl restart top40-archiver-download.service
sudo systemctl restart top40-archiver-web.service
sleep 3

echo "=== HTTP-test ==="
HTTP_CODE="$(curl -sS -o /tmp/top40-queue-limit-test.html -w '%{http_code}' http://127.0.0.1:8040/ || true)"
echo "HTTP-status: $HTTP_CODE"

if [[ "$HTTP_CODE" != "200" ]]; then
  echo "FOUT: dashboard geeft geen HTTP 200."
  sudo journalctl -u top40-archiver-web.service -n 80 --no-pager
  echo "Backup: $BACKUP"
  exit 1
fi

echo "=== Huidige persistente wachtrij ==="
sudo -u top40archiver sqlite3 -header -column "$DB" <<'SQL'
SELECT download_status, COUNT(*) AS aantal
FROM tracks
WHERE download_status IN ('pending','downloading')
GROUP BY download_status
ORDER BY download_status;
SQL

echo
echo "KLAAR."
echo "Historische import blijft actief, maar voegt pas nieuwe weken toe zodra de actieve wachtrij onder 100 komt."
echo "Bestaande wachtrij-items blijven veilig opgeslagen in SQLite."
echo "Backup: $BACKUP"
