from __future__ import annotations

import os
import socket

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from .health_engine import start_health_collector
from .incident_engine import incident_summary, list_incidents, read_journal, scan_journal
from .log_console import ALLOWED_UNITS, read_logs, service_states
from .prediction_engine import build_predictions
from .recovery_engine import ALLOWED_ACTIONS, execute_action, list_actions

VERSION = "1.15.3"
app = FastAPI(title="Top40Archiver AI Sidecar", version=VERSION)
start_health_collector()


def _ollama_status() -> dict[str, object]:
    host = os.getenv("OLLAMA_HOST", "127.0.0.1")
    port = int(os.getenv("OLLAMA_PORT", "11434"))
    model = os.getenv("TOP40_AI_MODEL", "qwen3:4b")
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return {"reachable": True, "model": model}
    except OSError:
        return {"reachable": False, "model": model}


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse("""<!doctype html><html lang='nl'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Top40 AI Operations</title><style>
:root{color-scheme:light}body{margin:0;background:#f6f3ee;color:#27211c;font-family:Inter,system-ui,sans-serif}.shell{max-width:1220px;margin:auto;padding:28px}.top{display:flex;justify-content:space-between;gap:18px;align-items:center}.badge{display:inline-block;padding:7px 11px;border-radius:999px;background:#e9e0d4;font-size:13px}.links,.tabs,.toolbar{display:flex;gap:10px;flex-wrap:wrap}.button,.tab{padding:11px 15px;border-radius:12px;border:1px solid #d8cdc0;background:#fff;color:#29231e;cursor:pointer;text-decoration:none;font-weight:700}.button.primary,.tab.active{background:#29231e;color:#fff}.danger{background:#b42318!important;color:#fff!important}.tabs{margin:22px 0}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.card{background:#fff;border:1px solid #e3d9cd;border-radius:20px;padding:20px;box-shadow:0 14px 35px rgba(50,40,30,.07)}.wide{grid-column:span 2}.full{grid-column:1/-1}.critical{border-left:6px solid #b42318}.warning{border-left:6px solid #b77700}.ok{border-left:6px solid #27864a}.metric{font-size:30px;font-weight:800}.incident{display:grid;grid-template-columns:1fr auto;gap:12px;margin-top:12px;padding:15px;border:1px solid #e6ded4;border-radius:14px}.log{background:#201d1a;color:#f5f0e8;padding:16px;border-radius:16px;white-space:pre-wrap;max-height:620px;overflow:auto;font:12px/1.5 ui-monospace,monospace}.service-table{width:100%;border-collapse:collapse}.service-table th,.service-table td{text-align:left;padding:10px;border-bottom:1px solid #eee6dc}.state-ok{color:#27864a;font-weight:700}.state-bad{color:#b42318;font-weight:700}.action-card{display:flex;justify-content:space-between;gap:16px;align-items:center;padding:14px;border:1px solid #e6ded4;border-radius:14px;margin-top:10px}.toolbar select,.toolbar input{padding:10px 12px;border:1px solid #d8cdc0;border-radius:10px;background:#fff}@media(max-width:800px){.grid{grid-template-columns:1fr 1fr}.wide{grid-column:span 2}}@media(max-width:520px){.grid{grid-template-columns:1fr}.wide{grid-column:auto}.top{align-items:flex-start;flex-direction:column}.action-card{align-items:flex-start;flex-direction:column}}</style></head><body><main class='shell'><div class='top'><div><span class='badge'>AI-sidecar · 8041 · v1.15.3</span><h1>AI Operations Center</h1><p>Incidenten, logging en gecontroleerd zelfherstel.</p></div><div class='links'><a class='button' id='main-link'>Hoofdpagina</a><button class='button primary' onclick='scanNow()'>Nu scannen</button></div></div><div class='tabs'><button class='tab active' onclick="showTab('incidents',this)">Incidenten</button><button class='tab' onclick="showTab('recovery',this)">Herstelacties</button><button class='tab' onclick="showTab('health',this)">Voorspellingen</button><button class='tab' onclick="showTab('services',this)">Services</button><button class='tab' onclick="showTab('logs',this)">Complete logging</button></div><section id='content' class='grid'><article class='card full'><h2>Gegevens worden geladen…</h2></article></section></main><script>
document.getElementById('main-link').href=location.protocol+'//'+location.hostname+':8040/';let current='incidents';const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');function showTab(name,b){current=name;document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));b.classList.add('active');loadData()}async function scanNow(){await fetch('/api/incidents/scan',{method:'POST'});current='incidents';loadData()}async function action(name){if(!confirm('Actie uitvoeren: '+name+'?'))return;const r=await fetch('/api/recovery/'+name,{method:'POST'}),d=await r.json();alert(d.status==='success'?'Actie geslaagd':'Actie mislukt');loadData()}async function loadLogs(){const g=document.getElementById('log-group')?.value||'all',m=document.getElementById('log-minutes')?.value||60;const r=await fetch(`/api/log-console?group=${encodeURIComponent(g)}&minutes=${encodeURIComponent(m)}&lines=2000`,{cache:'no-store'}),d=await r.text();document.getElementById('log-output').textContent=d}async function loadData(){const box=document.getElementById('content');try{if(current==='incidents'){const r=await fetch('/api/incidents?status=open',{cache:'no-store'}),d=await r.json(),s=d.summary,c=s.counts||{},items=d.incidents||[];box.innerHTML=`<article class='card ${s.circuit_breaker.active?'critical':'ok'}'><span>Circuit breaker</span><div class='metric'>${s.circuit_breaker.active?'ACTIEF':'VRIJ'}</div></article><article class='card critical'><span>Kritiek</span><div class='metric'>${c.critical||0}</div></article><article class='card warning'><span>Waarschuwingen</span><div class='metric'>${c.warning||0}</div></article><article class='card'><span>Open incidenten</span><div class='metric'>${items.length}</div></article><article class='card full'><h2>Incidenten</h2>${items.length?items.map(x=>`<div class='incident ${esc(x.severity)}'><div><b>${esc(x.title)}</b><p>${esc(x.recommendation)}</p><details><summary>Bewijs</summary><pre>${esc(x.evidence)}</pre></details></div><div><b>${Math.round(Number(x.confidence)*100)}%</b><br><small>${x.occurrences}×</small></div></div>`).join(''):'<p>Geen open incidenten.</p>'}</article>`}else if(current==='recovery'){const r=await fetch('/api/recovery/actions',{cache:'no-store'}),d=await r.json(),h=d.history||[];const actions=[['set_workers_one','Workers naar 1','Zet alleen de downloadparalleliteit veilig terug naar één.'],['pause_downloads','Downloads pauzeren','Stopt downloadtimer en actieve downloadservice.'],['run_test_download','Testdownload starten','Start één normale downloadservice-run als gecontroleerde test.'],['resume_downloads','Downloads hervatten','Start de downloadtimer opnieuw.'],['clear_circuit_breaker','Circuit breaker vrijgeven','Geeft de blokkadestatus handmatig vrij na controle.']];box.innerHTML=`<article class='card full'><h2>Gecontroleerde herstelacties</h2><p>Alle acties zijn vooraf gedefinieerd, omkeerbaar en worden in SQLite gelogd.</p>${actions.map(x=>`<div class='action-card'><div><b>${x[1]}</b><p>${x[2]}</p></div><button class='button ${x[0]==='pause_downloads'?'danger':'primary'}' onclick="action('${x[0]}')">Uitvoeren</button></div>`).join('')}</article><article class='card full'><h2>Auditlog</h2><table class='service-table'><thead><tr><th>Tijd</th><th>Actie</th><th>Status</th><th>Aanvrager</th></tr></thead><tbody>${h.map(x=>`<tr><td>${esc(x.started_at)}</td><td>${esc(x.action)}</td><td>${esc(x.status)}</td><td>${esc(x.requested_by)}</td></tr>`).join('')}</tbody></table></article>`}else if(current==='health'){const r=await fetch('/api/predictions?range=24h',{cache:'no-store'}),d=await r.json(),p=d.predictions;box.innerHTML=`<article class='card wide'><h2>${esc(p.headline)}</h2><p>${esc(p.advice)}</p></article><article class='card'><span>Health</span><div class='metric'>${esc(p.health.score)}%</div></article><article class='card'><span>Wachtrij</span><div class='metric'>${esc(p.queue_hours)} u</div></article>${(p.risks||[]).map(x=>`<article class='card'><b>${esc(x.label)}</b><div class='metric'>${esc(x.risk)}%</div></article>`).join('')}`}else if(current==='services'){const r=await fetch('/api/services',{cache:'no-store'}),d=await r.json();box.innerHTML=`<article class='card full'><h2>Servicestatus</h2><table class='service-table'><thead><tr><th>Service</th><th>Actief</th><th>Substatus</th><th>Resultaat</th></tr></thead><tbody>${d.services.map(x=>`<tr><td>${esc(x.unit)}</td><td class='${x.active==='active'?'state-ok':'state-bad'}'>${esc(x.active)}</td><td>${esc(x.sub)}</td><td>${esc(x.result)}</td></tr>`).join('')}</tbody></table></article>`}else{const r=await fetch('/api/log-groups',{cache:'no-store'}),d=await r.json();box.innerHTML=`<article class='card full'><h2>Complete logging</h2><div class='toolbar'><select id='log-group'>${d.groups.map(x=>`<option value='${esc(x)}'>${esc(x)}</option>`).join('')}</select><input id='log-minutes' type='number' min='1' max='1440' value='60'><button class='button primary' onclick='loadLogs()'>Log ophalen</button></div><pre id='log-output' class='log'>Log wordt geladen…</pre></article>`;await loadLogs()}}catch(e){box.innerHTML=`<article class='card full critical'><h2>Data niet beschikbaar</h2><p>${esc(e)}</p></article>`}}loadData();setInterval(()=>{if(current!=='logs')loadData()},30000);
</script></body></html>""")


@app.get("/api/predictions")
def predictions(range: str = Query("24h", pattern="^(1h|24h|7d)$")) -> JSONResponse:
    return JSONResponse({"ok": True, "predictions": build_predictions(range), "ollama": _ollama_status()})


@app.get("/api/incidents")
def incidents(status: str = Query("open", pattern="^(open|all)$"), limit: int = Query(100, ge=1, le=500)) -> JSONResponse:
    return JSONResponse({"ok": True, "summary": incident_summary(), "incidents": list_incidents(limit, status)})


@app.post("/api/incidents/scan")
def scan(minutes: int = Query(20, ge=1, le=240)) -> JSONResponse:
    return JSONResponse({"ok": True, "result": scan_journal(minutes)})


@app.get("/api/logs", response_class=PlainTextResponse)
def logs(minutes: int = Query(30, ge=1, le=1440), lines: int = Query(500, ge=20, le=3000)) -> PlainTextResponse:
    return PlainTextResponse("\n".join(read_journal(minutes, lines)))


@app.get("/api/log-groups")
def log_groups() -> JSONResponse:
    return JSONResponse({"ok": True, "groups": list(ALLOWED_UNITS)})


@app.get("/api/log-console", response_class=PlainTextResponse)
def log_console(group: str = Query("all"), minutes: int = Query(60, ge=1, le=1440), lines: int = Query(1000, ge=20, le=5000)) -> PlainTextResponse:
    result = read_logs(group, minutes, lines)
    return PlainTextResponse("\n".join(result.lines))


@app.get("/api/services")
def services() -> JSONResponse:
    return JSONResponse({"ok": True, "services": service_states()})


@app.get("/api/recovery/actions")
def recovery_actions(limit: int = Query(100, ge=1, le=500)) -> JSONResponse:
    return JSONResponse({"ok": True, "allowed": sorted(ALLOWED_ACTIONS), "history": list_actions(limit)})


@app.post("/api/recovery/{action}")
def recovery_action(action: str) -> JSONResponse:
    if action not in ALLOWED_ACTIONS:
        return JSONResponse({"ok": False, "error": "Actie niet toegestaan"}, status_code=400)
    result = execute_action(action, "ai-sidecar-operator")
    return JSONResponse({"ok": result["status"] == "success", **result})


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {"ok": True, "service": "top40-ai-sidecar", "version": VERSION, "port": 8041}
