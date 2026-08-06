from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from .health_engine import start_health_collector
from .incident_engine import incident_summary, list_incidents, read_journal, scan_journal
from .log_console import ALLOWED_UNITS, read_logs, service_states
from .prediction_engine import build_predictions
from .quality_diagnostics import collect_diagnostics, ollama_status, quality_check
from .recovery_engine import ALLOWED_ACTIONS, execute_action, list_actions

VERSION = '1.15.4'
app = FastAPI(title='Top40Archiver AI Operations', version=VERSION)
start_health_collector()


@app.get('/', response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse("""<!doctype html><html lang='nl'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Top40 AI Operations</title><style>:root{color-scheme:light}body{margin:0;background:#f7f7f5;color:#191714;font-family:Inter,system-ui,sans-serif}.shell{max-width:1240px;margin:auto;padding:28px}.top,.tabs,.toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center}.top{justify-content:space-between}.badge{padding:6px 10px;border-radius:999px;background:#fff0ed;color:#d84b3f;font-weight:700}.tabs{margin:22px 0}.button,.tab{border:1px solid #d8d2ca;border-radius:11px;padding:10px 14px;background:#fff;color:#222;cursor:pointer;font-weight:700;text-decoration:none}.button.primary,.tab.active{background:#f35b4d;border-color:#f35b4d;color:#fff}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.card{background:#fff;border:1px solid #e6e1da;border-radius:18px;padding:20px;box-shadow:0 10px 30px rgba(40,30,20,.06)}.full{grid-column:1/-1}.wide{grid-column:span 2}.metric{font-size:30px;font-weight:800}.critical{border-left:6px solid #df3d35}.warning{border-left:6px solid #d88b00}.ok{border-left:6px solid #24a35a}.log{background:#201d1a;color:#f5f0e8;padding:16px;border-radius:14px;white-space:pre-wrap;max-height:620px;overflow:auto;font:12px/1.5 monospace}table{width:100%;border-collapse:collapse}th,td{padding:10px;border-bottom:1px solid #eee;text-align:left}select,input{min-height:42px;border:1px solid #d8d2ca;border-radius:10px;background:#fff;color:#222;padding:9px 12px}.action{display:flex;justify-content:space-between;gap:15px;align-items:center;border:1px solid #eee;border-radius:13px;padding:13px;margin-top:10px}@media(max-width:800px){.grid{grid-template-columns:1fr 1fr}}@media(max-width:520px){.grid{grid-template-columns:1fr}.wide{grid-column:auto}}</style></head><body><main class='shell'><div class='top'><div><span class='badge'>AI-sidecar · 8041 · v1.15.4</span><h1>AI Operations Center</h1><p>Diagnostiek, kwaliteit, incidenten, logging en gecontroleerd herstel.</p></div><a class='button' id='main-link'>Hoofdpagina</a></div><div class='tabs' id='tabs'></div><section class='grid' id='content'><article class='card full'>Laden…</article></section></main><script>document.getElementById('main-link').href=location.protocol+'//'+location.hostname+':8040/';const tabs=['status','quality','diagnostics','incidents','recovery','services','logs'];let current='status';const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');document.getElementById('tabs').innerHTML=tabs.map((x,i)=>`<button class="tab ${i?'':'active'}" onclick="openTab('${x}',this)">${x}</button>`).join('');function openTab(n,b){current=n;document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));b.classList.add('active');load()}async function act(a){if(confirm('Actie uitvoeren: '+a+'?')){await fetch('/api/recovery/'+a,{method:'POST'});load()}}async function load(){const c=document.getElementById('content');try{if(current==='status'){const d=await (await fetch('/api/status')).json();c.innerHTML=`<article class='card'><b>Versie</b><div class='metric'>${esc(d.version)}</div></article><article class='card ${d.ollama.reachable?'ok':'warning'}'><b>Ollama</b><div class='metric'>${d.ollama.reachable?'Online':'Offline'}</div><small>${esc(d.ollama.latency_ms)} ms</small></article><article class='card'><b>Health</b><div class='metric'>${esc(d.predictions.health.score)}%</div></article><article class='card'><b>Open incidenten</b><div class='metric'>${esc(d.incidents.open)}</div></article>`}else if(current==='quality'){const d=await (await fetch('/api/quality-check')).json();c.innerHTML=`<article class='card full ${d.ok?'ok':'critical'}'><h2>Kwaliteitscontrole</h2><pre>${esc(JSON.stringify(d,null,2))}</pre></article>`}else if(current==='diagnostics'){const d=await (await fetch('/api/diagnostics')).json();c.innerHTML=`<article class='card full'><h2>Systeemdiagnostiek</h2><pre>${esc(JSON.stringify(d,null,2))}</pre></article>`}else if(current==='incidents'){const d=await (await fetch('/api/incidents?status=open')).json();c.innerHTML=`<article class='card full'><h2>Incidenten</h2><pre>${esc(JSON.stringify(d,null,2))}</pre></article>`}else if(current==='recovery'){const d=await (await fetch('/api/recovery/actions')).json();c.innerHTML=`<article class='card full'><h2>Herstelacties</h2>${d.allowed.map(a=>`<div class='action'><b>${esc(a)}</b><button class='button primary' onclick="act('${a}')">Uitvoeren</button></div>`).join('')}</article><article class='card full'><h2>Auditlog</h2><pre>${esc(JSON.stringify(d.history,null,2))}</pre></article>`}else if(current==='services'){const d=await (await fetch('/api/services')).json();c.innerHTML=`<article class='card full'><h2>Services</h2><pre>${esc(JSON.stringify(d.services,null,2))}</pre></article>`}else{const t=await (await fetch('/api/log-console?group=all&minutes=60&lines=2000')).text();c.innerHTML=`<article class='card full'><h2>Complete logging</h2><pre class='log'>${esc(t)}</pre></article>`}}catch(e){c.innerHTML=`<article class='card full critical'><h2>Fout</h2><p>${esc(e)}</p></article>`}}load();setInterval(()=>{if(current!=='logs')load()},30000)</script></body></html>""")


@app.get('/api/status')
def status() -> JSONResponse:
    p = build_predictions('24h')
    s = incident_summary()
    return JSONResponse({'ok': True, 'version': VERSION, 'ollama': ollama_status(), 'predictions': p, 'incidents': {'open': sum((s.get('counts') or {}).values()), **s}})


@app.get('/api/quality-check')
def quality() -> JSONResponse:
    return JSONResponse(quality_check())


@app.get('/api/diagnostics')
def diagnostics() -> JSONResponse:
    return JSONResponse(collect_diagnostics(write_file=True))


@app.get('/api/predictions')
def predictions(range: str = Query('24h', pattern='^(1h|24h|7d)$')) -> JSONResponse:
    return JSONResponse({'ok': True, 'predictions': build_predictions(range), 'ollama': ollama_status()})


@app.get('/api/incidents')
def incidents(status: str = Query('open', pattern='^(open|all)$'), limit: int = Query(100, ge=1, le=500)) -> JSONResponse:
    return JSONResponse({'ok': True, 'summary': incident_summary(), 'incidents': list_incidents(limit, status)})


@app.post('/api/incidents/scan')
def scan(minutes: int = Query(20, ge=1, le=240)) -> JSONResponse:
    return JSONResponse({'ok': True, 'result': scan_journal(minutes)})


@app.get('/api/logs', response_class=PlainTextResponse)
def logs(minutes: int = Query(30, ge=1, le=1440), lines: int = Query(500, ge=20, le=3000)) -> PlainTextResponse:
    return PlainTextResponse('\n'.join(read_journal(minutes, lines)))


@app.get('/api/log-groups')
def log_groups() -> JSONResponse:
    return JSONResponse({'ok': True, 'groups': list(ALLOWED_UNITS)})


@app.get('/api/log-console', response_class=PlainTextResponse)
def log_console(group: str = Query('all'), minutes: int = Query(60, ge=1, le=1440), lines: int = Query(1000, ge=20, le=5000)) -> PlainTextResponse:
    return PlainTextResponse('\n'.join(read_logs(group, minutes, lines).lines))


@app.get('/api/services')
def services() -> JSONResponse:
    return JSONResponse({'ok': True, 'services': service_states()})


@app.get('/api/recovery/actions')
def recovery_actions(limit: int = Query(100, ge=1, le=500)) -> JSONResponse:
    return JSONResponse({'ok': True, 'allowed': sorted(ALLOWED_ACTIONS), 'history': list_actions(limit)})


@app.post('/api/recovery/{action}')
def recovery_action(action: str) -> JSONResponse:
    if action not in ALLOWED_ACTIONS:
        return JSONResponse({'ok': False, 'error': 'Actie niet toegestaan'}, status_code=400)
    result = execute_action(action, 'ai-sidecar-operator')
    return JSONResponse({'ok': result['status'] == 'success', **result})


@app.get('/health')
@app.get('/healthz')
def healthz() -> dict[str, object]:
    return {'ok': True, 'service': 'top40-ai-sidecar', 'version': VERSION, 'port': 8041}
