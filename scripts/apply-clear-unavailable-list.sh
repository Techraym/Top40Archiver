#!/usr/bin/env bash
set -euo pipefail

APP="/opt/top40-archiver"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="$APP/backups/clear_unavailable_$STAMP"

cd "$APP"

echo "=== Backup maken ==="
sudo mkdir -p "$BACKUP"
sudo cp -a app/main.py app/templates/index.html app/static/style.css "$BACKUP/"

echo "=== Backendroute toevoegen ==="
sudo python3 - <<'PY'
from pathlib import Path

path = Path('/opt/top40-archiver/app/main.py')
text = path.read_text(encoding='utf-8')

route = '''\n\n@app.post("/unavailable/clear")\ndef clear_unavailable():\n    with connect() as con:\n        con.execute(\n            """\n            UPDATE tracks\n            SET download_status='pending',\n                download_attempts=0,\n                youtube_url=NULL,\n                custom_search_query=NULL,\n                error_message=NULL,\n                updated_at=?\n            WHERE download_status='unavailable'\n            """,\n            (now_iso(),),\n        )\n    return RedirectResponse("/", 303)\n'''

if '@app.post("/unavailable/clear")' not in text:
    marker = '\n\n@app.post("/track/{track_id}/restore")\n'
    if marker not in text:
        raise SystemExit('FOUT: invoegpunt voor backendroute niet gevonden')
    text = text.replace(marker, route + marker, 1)

path.write_text(text, encoding='utf-8')
PY

echo "=== Knop aan lijst toevoegen ==="
sudo python3 - <<'PY'
from pathlib import Path

path = Path('/opt/top40-archiver/app/templates/index.html')
text = path.read_text(encoding='utf-8')

old = '''<div class="section-heading compact"><div><span class="eyebrow">Bewust overgeslagen</span><h2>Niet online beschikbaar</h2></div><span id="unavailable-count" class="count-chip">{{ status_counts.unavailable }}</span></div>'''
new = '''<div class="section-heading compact unavailable-heading">\n      <div><span class="eyebrow">Bewust overgeslagen</span><h2>Niet online beschikbaar</h2></div>\n      <div class="unavailable-actions">\n        <span id="unavailable-count" class="count-chip">{{ status_counts.unavailable }}</span>\n        <form method="post" action="/unavailable/clear" onsubmit="return confirm('Alle nummers uit deze lijst terugzetten naar de wachtrij?');">\n          <button type="submit" class="secondary clear-unavailable">Lijst legen</button>\n        </form>\n      </div>\n    </div>'''

if 'class="clear-unavailable"' not in text:
    if old not in text:
        raise SystemExit('FOUT: kop van niet-beschikbare lijst niet gevonden')
    text = text.replace(old, new, 1)

for version in ('22','23','24','25','26'):
    text = text.replace(f'/static/style.css?v={version}', '/static/style.css?v=27')

path.write_text(text, encoding='utf-8')
PY

echo "=== Stijl toevoegen ==="
sudo tee -a app/static/style.css >/dev/null <<'CSS'

/* Niet-online-beschikbaar lijst legen */
.unavailable-heading {
  align-items: center;
}

.unavailable-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.unavailable-actions form {
  margin: 0;
}

.clear-unavailable {
  min-height: 38px;
  padding: 7px 13px;
  border-color: #e3b7b1 !important;
  color: #b63f35 !important;
  background: #fff7f5 !important;
}

.clear-unavailable:hover {
  border-color: #d78e85 !important;
  background: #fff0ed !important;
}

@media (max-width: 640px) {
  .unavailable-heading {
    align-items: flex-start;
  }

  .unavailable-actions {
    width: 100%;
    justify-content: space-between;
  }
}
CSS

echo "=== Syntaxcontrole ==="
sudo -u top40archiver "$APP/venv/bin/python" -m py_compile app/main.py

echo "=== Webservice herstarten ==="
sudo systemctl restart top40-archiver-web.service
sleep 3

HTTP_CODE="$(curl -sS -o /tmp/top40-clear-unavailable-test.html -w '%{http_code}' http://127.0.0.1:8040/ || true)"
echo "HTTP-status: $HTTP_CODE"

if [[ "$HTTP_CODE" != "200" ]]; then
  echo "FOUT: dashboard geeft geen HTTP 200."
  sudo journalctl -u top40-archiver-web.service -n 80 --no-pager
  echo "Backup: $BACKUP"
  exit 1
fi

echo

echo "KLAAR. De knop 'Lijst legen' is toegevoegd."
echo "De actie verwijdert geen hitlijsthistorie: alle items worden veilig teruggezet naar de wachtrij."
echo "Backup: $BACKUP"
