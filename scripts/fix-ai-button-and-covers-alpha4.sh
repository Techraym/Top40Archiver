#!/usr/bin/env bash
set -euo pipefail

APP="/opt/top40-archiver"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="/var/lib/top40-archiver/backups/alpha4_ui_cover_fix_${STAMP}"

cd "$APP"

if [ "$(id -u)" -ne 0 ]; then
  echo "FOUT: voer dit script uit met sudo."
  exit 1
fi

install -d -o root -g root -m 750 "$BACKUP"
cp -a app/templates/index.html app/static/live.js app/static/style.css "$BACKUP/"

echo "Backup: $BACKUP"

python3 - <<'PY'
from pathlib import Path

index = Path('/opt/top40-archiver/app/templates/index.html')
text = index.read_text(encoding='utf-8')

# Discrete AI-link, zonder bestaande vormgeving of layout te vervangen.
if 'id="ai-sidecar-link"' not in text:
    needle = '<div class="actions header-actions">'
    replacement = '''<div class="actions header-actions">
      <a id="ai-sidecar-link" class="secondary ai-sidecar-link" href="http://127.0.0.1:8041/" target="_blank" rel="noopener">AI</a>'''
    if needle not in text:
        raise SystemExit('FOUT: header-actions invoegpunt niet gevonden')
    text = text.replace(needle, replacement, 1)

# Covers in server-rendered Top 40 en Tipparade.
old = '<td><b>{{ x.artist }}</b></td><td>{{ x.title }}'
new = '''<td><div class="artist-cell">{% if x.cover_url %}<img class="track-cover" src="{{ x.cover_url }}" alt="" loading="lazy" referrerpolicy="no-referrer">{% else %}<span class="cover-placeholder">&#9835;</span>{% endif %}<b>{{ x.artist }}</b></div></td><td>{{ x.title }}'''
text = text.replace(old, new)

# Cacheversies verhogen.
import re
text = re.sub(r'/static/style\.css\?v=\d+', '/static/style.css?v=31', text)
text = re.sub(r'/static/live\.js\?v=\d+', '/static/live.js?v=31', text)
index.write_text(text, encoding='utf-8')

live = Path('/opt/top40-archiver/app/static/live.js')
js = live.read_text(encoding='utf-8')

# Maak de AI-link host-onafhankelijk: dezelfde host, poort 8041.
if 'ai-sidecar-link' not in js:
    js = '''document.addEventListener("DOMContentLoaded", () => {\n  const ai = document.getElementById("ai-sidecar-link");\n  if (ai) ai.href = `${location.protocol}//${location.hostname}:8041/`;\n});\n\n''' + js

# Live tabelregels ook met covers renderen.
start = js.find('  function chartRows(rows, statusLabels) {')
end = js.find('\n\n  function updateChart(', start)
if start != -1 and end != -1:
    replacement = '''  function chartRows(rows, statusLabels) {
    return rows.length
      ? rows.map((row) => {
          const cover = row.cover_url
            ? `<img class="track-cover" src="${escapeHtml(row.cover_url)}" alt="" loading="lazy" referrerpolicy="no-referrer">`
            : '<span class="cover-placeholder">&#9835;</span>';
          return `
          <tr class="${row.is_new ? "new" : ""}">
            <td><span class="position">${escapeHtml(row.position)}</span></td>
            <td><div class="artist-cell">${cover}<b>${escapeHtml(row.artist)}</b></div></td>
            <td>${escapeHtml(row.title)} ${row.is_new ? '<span class="new-label">NIEUW</span>' : ""}</td>
            <td><span class="status-badge status-${escapeHtml(row.download_status)}">${escapeHtml(statusLabels[row.download_status] || row.download_status)}</span></td>
          </tr>`;
        }).join("")
      : '<tr><td colspan="4" class="empty">Nog geen editie verwerkt.</td></tr>';
  }'''
    js = js[:start] + replacement + js[end:]

live.write_text(js, encoding='utf-8')

style = Path('/opt/top40-archiver/app/static/style.css')
css = style.read_text(encoding='utf-8')
block = '''

/* alpha.4 hotfix: discrete AI-link en albumhoezen */
.ai-sidecar-link{display:inline-flex;align-items:center;justify-content:center;text-decoration:none;min-height:46px;padding:0 18px;border-radius:12px;font-weight:700}
.artist-cell{min-width:190px;display:flex;align-items:center;gap:12px}
.track-cover,.cover-placeholder{width:42px;height:42px;flex:0 0 42px;border-radius:8px;border:1px solid #e7e4de;box-shadow:0 3px 10px rgba(30,28,24,.08)}
.track-cover{display:block;object-fit:cover;background:#f2f1ed}
.cover-placeholder{display:grid;place-items:center;color:#ef5846;background:linear-gradient(145deg,#fff3ef,#f7eee9);font-size:18px;font-weight:700}
td{vertical-align:middle}
'''
if 'alpha.4 hotfix: discrete AI-link en albumhoezen' not in css:
    css += block
style.write_text(css, encoding='utf-8')
PY

sudo -u top40archiver "$APP/venv/bin/python" -m py_compile app/main.py app/db.py app/cover_art.py

systemctl kill --kill-who=all --signal=SIGKILL top40-archiver-web.service 2>/dev/null || true
systemctl reset-failed top40-archiver-web.service || true
systemctl start top40-archiver-web.service
sleep 4

curl -fsS http://127.0.0.1:8040/ >/dev/null

echo "=== Coverstatus ==="
sudo -u top40archiver sqlite3 -header -column /var/lib/top40-archiver/top40.sqlite3 "
SELECT COUNT(*) AS totaal,
       SUM(CASE WHEN cover_url IS NOT NULL THEN 1 ELSE 0 END) AS met_cover,
       SUM(CASE WHEN cover_checked_at IS NOT NULL THEN 1 ELSE 0 END) AS gecontroleerd
FROM tracks;
"

echo "=== Coverworker nu starten ==="
systemctl start top40-archiver-cover-art.service || true

echo "KLAAR. Ververs de browser met Ctrl+F5."
echo "AI: http://$(hostname -I | awk '{print $1}'):8041/"
echo "Backup: $BACKUP"
