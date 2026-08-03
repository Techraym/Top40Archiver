#!/bin/bash
set -euo pipefail
DB=/var/lib/top40-archiver/top40.sqlite3
read -r DAY TIME < <(/opt/top40-archiver/venv/bin/python - <<'PY'
import sqlite3
c=sqlite3.connect('/var/lib/top40-archiver/top40.sqlite3')
d=dict(c.execute('select key,value from settings'))
print(d.get('weekly_day','Fri'), d.get('weekly_time','10:00'))
PY
)
cat >/etc/systemd/system/top40-archiver-check.timer <<EOT
[Unit]
Description=Wekelijkse Top 40- en Tipparadecontrole
[Timer]
OnCalendar=${DAY} *-*-* ${TIME}:00
Persistent=true
RandomizedDelaySec=30
Unit=top40-archiver-check.service
[Install]
WantedBy=timers.target
EOT
systemctl daemon-reload
systemctl enable --now top40-archiver-check.timer
systemctl restart top40-archiver-check.timer
systemctl list-timers top40-archiver-check.timer --no-pager
