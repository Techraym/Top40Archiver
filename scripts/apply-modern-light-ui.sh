#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/top40-archiver"
INDEX="$APP_DIR/app/templates/index.html"
CSS="$APP_DIR/app/static/style.css"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="$APP_DIR/backups/ui_$STAMP"

echo "=== Top 40 Archiver: moderne lichte UI installeren ==="

if [[ ! -f "$INDEX" || ! -f "$CSS" ]]; then
  echo "FOUT: index.html of style.css ontbreekt."
  exit 1
fi

sudo mkdir -p "$BACKUP"
sudo cp -a "$INDEX" "$CSS" "$BACKUP/"
echo "Backup: $BACKUP"

sudo python3 - "$INDEX" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")

text = text.replace(
    '<meta name="theme-color" content="#171513">',
    '<meta name="theme-color" content="#f7f7f5">'
)
text = text.replace('/static/style.css?v=22', '/static/style.css?v=23')
text = text.replace('/static/live.js?v=22', '/static/live.js?v=23')

sidebar = """
<aside class="app-sidebar" aria-label="Hoofdnavigatie">
  <a class="side-logo active" href="/" aria-label="Dashboard">
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 11.5 12 4l9 7.5v8a1.5 1.5 0 0 1-1.5 1.5H15v-6H9v6H4.5A1.5 1.5 0 0 1 3 19.5z"/></svg>
  </a>
  <nav>
    <a href="#latest-chart-title" aria-label="Laatste lijsten">
      <svg viewBox="0 0 24 24"><path d="M6 5h12M6 12h12M6 19h12M3 5h.01M3 12h.01M3 19h.01"/></svg>
    </a>
    <a href="#archive-card" aria-label="Archiefopbouw">
      <svg viewBox="0 0 24 24"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7"/></svg>
    </a>
    <a href="#queue-list" aria-label="Downloads">
      <svg viewBox="0 0 24 24"><path d="M5 20V10M12 20V4M19 20v-7"/></svg>
    </a>
    <a href=".settings-panel" aria-label="Instellingen">
      <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.6v-.2h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1z"/></svg>
    </a>
  </nav>
  <div class="side-bottom">
    <button type="button" class="theme-toggle" aria-label="Thema wisselen" title="Thema wisselen">
      <svg viewBox="0 0 24 24"><path d="M20 15.2A8.5 8.5 0 0 1 8.8 4 8.5 8.5 0 1 0 20 15.2z"/></svg>
    </button>
  </div>
</aside>
"""

if 'class="app-sidebar"' not in text:
    text = text.replace("<body>", "<body>\n" + sidebar, 1)

text = text.replace(">Opslag en koppelingen<", ">Opslag &amp; koppelingen<")
path.write_text(text, encoding="utf-8")
PY

sudo tee -a "$CSS" >/dev/null <<'CSS'

/* =========================================================
   Top 40 Archiver — Modern Light UI v23
   ========================================================= */

:root {
  color-scheme: light;
  --page: #f5f5f2;
  --surface: #ffffff;
  --surface-raised: #ffffff;
  --surface-soft: #f9f9f7;
  --line: #e8e6e1;
  --line-strong: #d9d6cf;
  --text: #181817;
  --muted: #686761;
  --muted-2: #929089;
  --accent: #ef5846;
  --accent-hover: #db4938;
  --accent-soft: #fff0ec;
  --green: #31a663;
  --green-soft: #edf9f1;
  --amber: #dc9416;
  --amber-soft: #fff7e8;
  --blue: #3978b8;
  --blue-soft: #edf5fc;
  --red: #df4a41;
  --red-soft: #fff0ef;
  --purple: #7a62a6;
  --purple-soft: #f4effb;
  --radius: 16px;
  --radius-small: 10px;
  --shadow-sm: 0 1px 2px rgba(24,24,20,.03), 0 8px 22px rgba(24,24,20,.04);
  --shadow-md: 0 2px 5px rgba(24,24,20,.04), 0 18px 45px rgba(24,24,20,.06);
}

html,
body {
  background:
    radial-gradient(circle at 22% 0%, rgba(255,255,255,.95), transparent 34rem),
    var(--page);
  color: var(--text);
}

body {
  min-height: 100vh;
  font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

body::before {
  content: "";
  position: fixed;
  inset: 0 auto 0 0;
  width: 78px;
  background: rgba(255,255,255,.78);
  border-right: 1px solid var(--line);
  backdrop-filter: blur(18px);
  z-index: 20;
}

.app-sidebar {
  position: fixed;
  inset: 20px auto 20px 12px;
  width: 54px;
  z-index: 30;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 22px;
}

.app-sidebar a,
.app-sidebar button {
  width: 42px;
  height: 42px;
  min-height: 42px;
  padding: 0;
  border: 0;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: transparent;
  color: #55534f;
  box-shadow: none;
}

.app-sidebar a:hover,
.app-sidebar button:hover {
  background: var(--surface-soft);
  color: var(--accent);
}

.app-sidebar .active {
  background: var(--accent-soft);
  color: var(--accent);
  border: 1px solid #ffd3ca;
}

.app-sidebar nav {
  display: grid;
  gap: 10px;
}

.app-sidebar svg {
  width: 20px;
  height: 20px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.app-sidebar .side-logo svg {
  fill: currentColor;
  stroke: none;
}

.side-bottom {
  margin-top: auto;
}

.shell {
  width: min(1320px, calc(100% - 124px));
  margin: 0 auto 0 92px;
  padding: 42px 0 64px;
}

.page-header {
  align-items: center;
  border-bottom: 0;
  padding: 0 0 28px;
}

.brand-block {
  align-items: center;
  gap: 22px;
}

.logo {
  width: 68px;
  height: 78px;
  border-radius: 8px;
  box-shadow: 0 10px 28px rgba(239,88,70,.22);
  background: linear-gradient(145deg, #f66652, #df4738);
}

.logo span {
  font: 700 13px/1 Georgia, "Times New Roman", serif;
  letter-spacing: .08em;
}

.logo b {
  font-size: 36px;
}

.title-line h1 {
  font: 650 clamp(34px, 4vw, 54px)/1 Georgia, "Iowan Old Style", "Palatino Linotype", serif;
  letter-spacing: -.04em;
}

.brand-block p {
  margin-top: 10px;
  color: var(--muted);
}

.brand-block small {
  color: var(--muted-2);
}

.live-pill {
  border-radius: 999px;
  padding: 5px 10px;
  background: var(--green-soft);
  border-color: #bfe6cd;
}

.header-actions button {
  min-height: 46px;
  border-radius: 10px;
  padding-inline: 18px;
  box-shadow: 0 7px 18px rgba(239,88,70,.12);
}

.header-actions .secondary {
  background: #fff;
  border-color: var(--line-strong);
  box-shadow: var(--shadow-sm);
}

.metric-grid {
  overflow: hidden;
  margin: 18px 0 26px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: rgba(255,255,255,.88);
  box-shadow: var(--shadow-sm);
}

.metric-card {
  padding: 23px 20px 22px;
  border-right-color: var(--line);
}

.metric-card span {
  color: #67655f;
  font-size: 10px;
  letter-spacing: .06em;
}

.metric-card strong {
  margin-top: 10px;
  color: var(--text);
  font-size: 29px;
}

.metric-card small {
  color: var(--muted);
  line-height: 1.35;
}

.success-card strong { color: var(--green); }
.warning-card strong { color: var(--amber); }
.danger-card strong { color: var(--red); }

.archive-card {
  display: grid;
  grid-template-columns: minmax(0, 1.8fr) minmax(310px, .9fr);
  gap: 18px;
  background: transparent;
  border: 0;
  box-shadow: none;
}

.archive-main,
.storage-card,
.panel {
  background: rgba(255,255,255,.92);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
}

.archive-main {
  padding: 30px;
}

.storage-card {
  padding: 28px;
}

.panel {
  margin-top: 22px;
  padding: 26px 28px;
}

.section-heading h2 {
  color: var(--text);
  font: 650 30px/1.12 Georgia, "Iowan Old Style", serif;
  letter-spacing: -.025em;
}

.section-heading.compact h2 {
  font-size: 27px;
}

.eyebrow {
  color: var(--accent);
  font-size: 11px;
  letter-spacing: .13em;
}

.status-badge {
  border-radius: 999px;
  padding: 5px 10px;
  font-weight: 700;
  box-shadow: none;
}

.progress {
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: #ebeae6;
}

.progress span {
  border-radius: inherit;
  background: linear-gradient(90deg, #f56450, #ea5544);
}

.archive-numbers {
  margin-top: 26px;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}

.archive-numbers > div {
  padding: 22px 18px 20px;
  border-right-color: var(--line);
}

.archive-numbers strong {
  color: var(--text);
  font-size: 24px;
}

.archive-numbers span,
.note {
  color: var(--muted);
}

.storage-state {
  border-bottom-color: var(--line);
}

.storage-state > span {
  background: #fff;
}

.storage-numbers {
  color: var(--muted);
}

button,
.button {
  min-height: 44px;
  border-radius: 10px;
  box-shadow: 0 6px 16px rgba(239,88,70,.12);
}

button.secondary,
button.quiet {
  background: #fff;
  color: var(--text);
  box-shadow: none;
}

button.secondary:hover,
button.quiet:hover {
  background: #f7f7f4;
  border-color: var(--line-strong);
}

.table-wrap {
  overflow: auto;
  border-top: 1px solid var(--line);
}

table {
  border-collapse: separate;
  border-spacing: 0;
}

th {
  color: #77746e;
  font-size: 10px;
  letter-spacing: .08em;
  background: transparent;
}

td {
  border-top: 1px solid #efeee9;
  padding-top: 14px;
  padding-bottom: 14px;
}

tbody tr {
  transition: background .15s ease;
}

tbody tr:hover {
  background: #fafaf7;
}

tbody tr.new {
  background: #fffdfb;
}

.position {
  color: #292824;
  font-weight: 800;
}

.new-label {
  color: var(--accent);
  background: var(--accent-soft);
  border: 1px solid #ffd0c7;
  border-radius: 6px;
}

.compact-list article,
.success-list article,
.failed-list article {
  border-color: var(--line);
  background: #fff;
}

.failed-list article {
  border-radius: 12px;
}

.count-chip {
  border-radius: 999px;
}

input,
select {
  border: 1px solid var(--line-strong);
  border-radius: 10px;
  background: #fff;
  color: var(--text);
}

input:focus,
select:focus {
  outline: 3px solid rgba(239,88,70,.13);
  border-color: var(--accent);
}

.settings-panel summary {
  color: var(--text);
}

footer {
  color: var(--muted-2);
  border-top-color: var(--line);
}

code,
pre {
  color: #5b5954;
  background: #f5f4f0;
}

@media (max-width: 1180px) {
  .metric-grid {
    grid-template-columns: repeat(3, 1fr);
  }

  .metric-card:nth-child(3) {
    border-right: 0;
  }

  .metric-card:nth-child(-n+3) {
    border-bottom: 1px solid var(--line);
  }

  .archive-card {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 850px) {
  body::before,
  .app-sidebar {
    display: none;
  }

  .shell {
    width: min(100% - 28px, 760px);
    margin: 0 auto;
    padding-top: 24px;
  }

  .page-header {
    align-items: flex-start;
  }

  .page-header,
  .brand-block {
    flex-direction: column;
  }

  .brand-block {
    align-items: flex-start;
  }

  .header-actions {
    width: 100%;
    justify-content: flex-start;
  }

  .metric-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .metric-card,
  .metric-card:nth-child(3) {
    border-right: 1px solid var(--line);
  }

  .metric-card:nth-child(even) {
    border-right: 0;
  }

  .metric-card:nth-child(-n+4) {
    border-bottom: 1px solid var(--line);
  }

  .archive-main,
  .storage-card,
  .panel {
    padding: 22px;
  }
}

@media (max-width: 560px) {
  .metric-grid {
    grid-template-columns: 1fr;
  }

  .metric-card,
  .metric-card:nth-child(even),
  .metric-card:nth-child(3) {
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }

  .metric-card:last-child {
    border-bottom: 0;
  }

  .archive-numbers {
    grid-template-columns: repeat(2, 1fr);
  }

  .title-line h1 {
    font-size: 38px;
  }

  .logo {
    width: 60px;
    height: 68px;
  }
}
CSS

echo
echo "=== HTML en CSS controleren ==="
sudo -u top40archiver test -r "$INDEX"
sudo -u top40archiver test -r "$CSS"

echo
echo "=== Webservice herstarten ==="
sudo systemctl restart top40-archiver-web.service
sleep 3

echo
echo "=== Servicecontrole ==="
sudo systemctl --no-pager --full status top40-archiver-web.service | sed -n '1,18p'

echo
echo "=== HTTP-test ==="
HTTP_CODE="$(curl -sS -o /tmp/top40-ui-test.html -w '%{http_code}' http://127.0.0.1:8040/ || true)"
echo "HTTP-status: $HTTP_CODE"

if [[ "$HTTP_CODE" != "200" ]]; then
  echo
  echo "FOUT: dashboard geeft geen HTTP 200. Backup wordt niet automatisch teruggezet."
  echo "Logboek:"
  sudo journalctl -u top40-archiver-web.service -n 60 --no-pager
  echo
  echo "Handmatig terugzetten:"
  echo "sudo cp -a '$BACKUP/index.html' '$INDEX'"
  echo "sudo cp -a '$BACKUP/style.css' '$CSS'"
  echo "sudo systemctl restart top40-archiver-web.service"
  exit 1
fi

echo
echo "KLAAR."
echo "Open of vernieuw: http://192.168.2.68:8040/"
echo "Gebruik Ctrl+F5 om de browsercache te omzeilen."
