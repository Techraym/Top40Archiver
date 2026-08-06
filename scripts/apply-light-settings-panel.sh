#!/usr/bin/env bash
set -euo pipefail

APP="/opt/top40-archiver"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="$APP/backups/settings_panel_$STAMP"

cd "$APP"

echo "=== Backup maken ==="
sudo mkdir -p "$BACKUP"
sudo cp -a app/static/style.css app/templates/index.html "$BACKUP/"

echo "=== Beheerinstellingen licht maken ==="
sudo tee -a app/static/style.css >/dev/null <<'CSS'

/* ===== Beheerinstellingen: definitieve lichte kleurcorrectie ===== */
.settings-panel,
.settings-panel[open],
.settings-panel summary,
.settings-panel .settings-grid,
.settings-panel .organize-box {
  background: #ffffff !important;
  color: #181817 !important;
}

.settings-panel {
  border: 1px solid #e6e3dd !important;
  box-shadow: 0 1px 2px rgba(24,24,20,.03), 0 8px 22px rgba(24,24,20,.04) !important;
}

.settings-panel summary {
  border-radius: 14px !important;
}

.settings-panel summary b,
.settings-panel summary span,
.settings-panel label,
.settings-panel .note,
.settings-panel .organize-box b,
.settings-panel .organize-box small {
  color: #181817 !important;
}

.settings-panel label > small,
.settings-panel .note,
.settings-panel .organize-box small {
  color: #6f6c66 !important;
}

.settings-panel input,
.settings-panel select,
.settings-panel textarea {
  background: #ffffff !important;
  color: #181817 !important;
  border: 1px solid #d8d4cc !important;
  box-shadow: inset 0 1px 1px rgba(20,20,18,.02) !important;
  -webkit-text-fill-color: #181817 !important;
}

.settings-panel input::placeholder,
.settings-panel textarea::placeholder {
  color: #96928a !important;
  opacity: 1 !important;
}

.settings-panel input:focus,
.settings-panel select:focus,
.settings-panel textarea:focus {
  background: #ffffff !important;
  color: #181817 !important;
  border-color: #ef5846 !important;
  outline: 3px solid rgba(239,88,70,.14) !important;
}

.settings-panel select {
  background-image: none !important;
}

.settings-panel .check-label {
  background: #faf9f6 !important;
  border: 1px solid #e7e4de !important;
  border-radius: 10px !important;
  color: #181817 !important;
}

.settings-panel .check-label input[type="checkbox"] {
  accent-color: #ef5846 !important;
  width: 18px !important;
  height: 18px !important;
  min-height: 18px !important;
  box-shadow: none !important;
}

.settings-panel button {
  background: #ef5846 !important;
  color: #ffffff !important;
  border-color: #ef5846 !important;
}

.settings-panel button:hover {
  background: #db4938 !important;
  border-color: #db4938 !important;
}

.settings-panel button.secondary {
  background: #ffffff !important;
  color: #181817 !important;
  border-color: #d8d4cc !important;
  box-shadow: none !important;
}

.settings-panel button.secondary:hover {
  background: #f7f6f2 !important;
}

.settings-panel code,
.settings-panel pre {
  background: #f4f2ed !important;
  color: #4e4b46 !important;
  border: 1px solid #e6e2da !important;
}

.settings-panel .organize-box {
  border: 1px solid #e6e3dd !important;
  border-radius: 12px !important;
}
CSS

sudo python3 - <<'PY'
from pathlib import Path
path = Path('/opt/top40-archiver/app/templates/index.html')
text = path.read_text(encoding='utf-8')
for version in ('22','23','24','25'):
    text = text.replace(f'/static/style.css?v={version}', '/static/style.css?v=26')
path.write_text(text, encoding='utf-8')
PY

echo "=== Webservice herstarten ==="
sudo systemctl restart top40-archiver-web.service
sleep 3
curl -fsS http://127.0.0.1:8040/ >/dev/null

echo "KLAAR. Vernieuw de browser met Ctrl+F5."
echo "Backup: $BACKUP"
