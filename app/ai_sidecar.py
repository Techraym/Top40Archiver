from __future__ import annotations

import asyncio
import os
import socket

import requests
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

from .ai_memory import best_learning, remember_event, timeline
from .incident_engine import incident_summary, list_incidents, scan_journal
from .operations_center import cover_dashboard, database_dashboard, download_dashboard, health_score, service_monitor

VERSION = "1.15.5"
LOG_READER = os.getenv("TOP40_LOG_READER_URL", "http://127.0.0.1:8042")
app = FastAPI(title="Top40Archiver AI Operations Center", version=VERSION)


def _reader(path: str, params: dict | None = None) -> dict:
    try:
        response = requests.get(LOG_READER + path, params=params, timeout=12)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise HTTPException(503, f"Logreader niet beschikbaar: {exc}") from exc


def _ollama() -> dict[str, object]:
    host = os.getenv("OLLAMA_HOST", "127.0.0.1"); port = int(os.getenv("OLLAMA_PORT", "11434"))
    try:
        with socket.create_connection((host, port), timeout=1.5): return {"reachable": True, "model": os.getenv("TOP40_AI_MODEL", "qwen3:4b")}
    except OSError: return {"reachable": False, "model": os.getenv("TOP40_AI_MODEL", "qwen3:4b")}


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse("""<!doctype html><html lang='nl'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Top40 AI Operations Center</title><style>
:root{color-scheme:light;--bg:#f6f3ee;--card:#fff;--ink:#26211d;--muted:#756d65;--line:#e6ddd3;--good:#247a49;--warn:#ae7000;--bad:#b52d24}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 Inter,system-ui,sans-serif}.shell{max-width:1450px;margin:auto;padding:26px}.top{display:flex;justify-content:space-between;gap:20px;align-items:center}.eyebrow{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}h1{margin:.2rem 0;font-size:clamp(30px,5vw,54px)}.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:22px 0}.tab,.btn{border:1px solid var(--line);background:#fff;border-radius:999px;padding:10px 15px;cursor:pointer}.tab.active,.btn.primary{background:var(--ink);color:#fff}.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:14px}.card{grid-column:span 3;background:var(--card);border:1px solid var(--line);border-radius:20px;padding:18px;box-shadow:0 12px 32px rgba(60,45,30,.06)}.wide{grid-column:span 6}.full{grid-column:1/-1}.metric{font-size:34px;font-weight:800;margin-top:6px}.muted{color:var(--muted)}.good{color:var(--good)}.warn{color:var(--warn)}.bad{color:var(--bad)}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px;border-bottom:1px solid var(--line);vertical-align:top}.timeline{border-left:2px solid var(--line);margin-left:8px}.event{padding:0 0 18px 20px;position:relative}.event:before{content:'';position:absolute;left:-6px;top:5px;width:10px;height:10px;border-radius:50%;background:var(--ink)}pre{white-space:pre-wrap;background:#211e1b;color:#f7f2eb;padding:16px;border-radius:14px;max-height:560px;overflow:auto}.toolbar{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}input,select{padding:10px;border:1px solid var(--line);border-radius:10px;background:#fff}@media(max-width:900px){.card{grid-column:span 6}}@media(max-width:560px){.card,.wide{grid-column:1/-1}.top{align-items:flex-start;flex-direction:column}}</style></head><body><main class='shell'><header class='top'><div><div class='eyebrow'>Top40Archiver · AI beheerlaag · poort 8041</div><h1>Operations Center</h1><div class='muted'>Live inzicht, incidentanalyse en veilige systeemdiagnostiek.</div></div><button class='btn primary' onclick='scan()'>Systeem scannen</button></header><nav class='tabs' id='tabs'></nav><section class='grid' id='view'></section></main><script>
const tabs=['overzicht','services','downloads','covers','database','incidenten','tijdlijn','logs','zoeken'];let active='overzicht';const e=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');document.getElementById('tabs').innerHTML=tabs.map(x=>`<button class='tab ${x===active?'active':''}' onclick="go('${x}',this)">${x[0].toUpperCase()+x.slice(1)}</button>`).join('');function go(x,b){active=x;document.querySelectorAll('.tab').forEach(y=>y.classList.remove('active'));b.classList.add('active');load()}async function j(u,o){const r=await fetch(u,o);if(!r.ok)throw Error(await r.text());return r.json()}async function scan(){await j('/api/incidents/scan',{method:'POST'});active='incidenten';load()}function card(t,v,c=''){return `<article class='card ${c}'><div class='muted'>${e(t)}</div><div class='metric'>${e(v)}</div></article>`}async function load(){const v=document.getElementById('view');v.innerHTML=`<article class='card full'>Laden…</article>`;try{if(active==='overzicht'){const d=await j('/api/overview');v.innerHTML=card('Health score',d.health.score+'%',d.health.score>=90?'good':d.health.score>=70?'warn':'bad')+card('Status',d.health.label)+card('Open incidenten',d.incidents.counts?.total||0)+card('Ollama',d.ollama.reachable?'Online':'Offline',d.ollama.reachable?'good':'bad')+`<article class='card wide'><h2>Diagnose</h2><p>${e((d.health.reasons||[]).join(' · ')||'Geen kritieke afwijkingen gevonden.')}</p></article><article class='card wide'><h2>Platform</h2><p>${d.services.filter(x=>x.status==='active').length} van ${d.services.length} services actief.</p><p>${e(d.downloads.queue)} downloads in wachtrij · ${e(d.database.tracks)} tracks.</p></article>`}else if(active==='services'){const d=await j('/api/operations/services');v.innerHTML=`<article class='card full'><h2>Service Monitor</h2><table><tr><th>Service</th><th>Status</th><th>PID</th><th>CPU</th><th>RAM</th><th>Threads</th><th>Restarts</th><th>Laatste start</th></tr>${d.items.map(x=>`<tr><td>${e(x.unit)}</td><td class='${x.status==='active'?'good':'bad'}'>${e(x.status)}</td><td>${x.pid}</td><td>${x.cpu_seconds}s</td><td>${x.ram_mb} MB</td><td>${x.threads}</td><td>${x.restarts}</td><td>${e(x.last_restart||'-')}</td></tr>`).join('')}</table></article>`}else if(active==='downloads'||active==='covers'||active==='database'){const d=await j('/api/operations/'+active);v.innerHTML=Object.entries(d).filter(([k])=>k!=='ok').map(([k,x])=>card(k.replaceAll('_',' '),typeof x==='boolean'?(x?'Ja':'Nee'):x)).join('')}else if(active==='incidenten'){const d=await j('/api/incidents?status=open');v.innerHTML=`<article class='card full'><h2>Incidentanalyse</h2>${d.incidents.length?d.incidents.map(x=>`<div style='padding:15px 0;border-bottom:1px solid var(--line)'><b>${e(x.title)}</b> <span class='muted'>${Math.round(x.confidence*100)}%</span><p>${e(x.recommendation)}</p></div>`).join(''):'<p>Geen open incidenten.</p>'}</article>`}else if(active==='tijdlijn'){const d=await j('/api/timeline');v.innerHTML=`<article class='card full'><h2>Incident Timeline</h2><div class='timeline'>${d.items.map(x=>`<div class='event'><b>${e(new Date(x.created_at).toLocaleString())}</b><br>${e(x.message)}<div class='muted'>${e(x.service||x.event_type)}</div></div>`).join('')||'<p>De tijdlijn is nog leeg.</p>'}</div></article>`}else if(active==='zoeken'){v.innerHTML=`<article class='card full'><h2>Zoekmachine</h2><div class='toolbar'><input id='q' placeholder='Zoek logs en incidenten'><button class='btn primary' onclick='searchAll()'>Zoeken</button></div><div id='results'></div></article>`}else{v.innerHTML=`<article class='card full'><h2>Live logging</h2><div class='toolbar'><select id='svc'>${['all','web','download','cover','ai','ollama','database','updater','system'].map(x=>`<option>${x}</option>`).join('')}</select><button class='btn' onclick='connectLogs()'>Verbinden</button></div><pre id='log'>Klik op Verbinden.</pre></article>`}}catch(err){v.innerHTML=`<article class='card full bad'><h2>Niet beschikbaar</h2><p>${e(err)}</p></article>`}}async function searchAll(){const q=document.getElementById('q').value,d=await j('/api/search?q='+encodeURIComponent(q));document.getElementById('results').innerHTML=`<h3>Logs</h3>${d.logs.map(x=>`<p><b>${e(x.service)}</b> ${e(x.message)}</p>`).join('')||'<p>Geen resultaten.</p>'}<h3>Incidenten</h3>${d.incidents.map(x=>`<p><b>${e(x.title)}</b> ${e(x.recommendation)}</p>`).join('')||'<p>Geen resultaten.</p>'}`}let ws;function connectLogs(){if(ws)ws.close();const out=document.getElementById('log');out.textContent='';ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/logs?service=${document.getElementById('svc').value}`);ws.onmessage=x=>{const d=JSON.parse(x.data);out.textContent+=`[${d.time}] ${d.service} ${d.level}: ${d.message}\n`;out.scrollTop=out.scrollHeight}}load();setInterval(()=>{if(['overzicht','services','downloads','covers','database','incidenten','tijdlijn'].includes(active))load()},30000);
</script></body></html>""")


@app.get('/api/overview')
def overview():
    return {"ok": True, "health": health_score(), "services": service_monitor(), "downloads": download_dashboard(), "covers": cover_dashboard(), "database": database_dashboard(), "incidents": incident_summary(), "ollama": _ollama()}

@app.get('/api/operations/services')
def services(): return {"ok": True, "items": service_monitor()}
@app.get('/api/operations/downloads')
def downloads(): return {"ok": True, **download_dashboard()}
@app.get('/api/operations/covers')
def covers(): return {"ok": True, **cover_dashboard()}
@app.get('/api/operations/database')
def database(): return {"ok": True, **database_dashboard()}
@app.get('/api/timeline')
def history(limit: int = Query(100,ge=1,le=500)): return {"ok": True, "items": timeline(limit)}
@app.get('/api/incidents')
def incidents(status: str=Query('open',pattern='^(open|all)$'),limit:int=Query(100,ge=1,le=500)): return {"ok":True,"summary":incident_summary(),"incidents":list_incidents(limit,status)}
@app.post('/api/incidents/scan')
def scan(minutes:int=Query(20,ge=1,le=240)):
    result=scan_journal(minutes); remember_event('scan','Handmatige incidentscan uitgevoerd',metadata=result); return {"ok":True,"result":result}
@app.get('/api/logs/service/{service}')
def logs(service:str,minutes:int=60,lines:int=1000): return _reader(f'/api/logs/service/{service}',{"minutes":minutes,"lines":lines})
@app.get('/api/logs/errors')
def errors(minutes:int=1440,lines:int=500): return _reader('/api/logs/errors',{"minutes":minutes,"lines":lines})
@app.get('/api/search')
def search(q:str=Query(...,min_length=2,max_length=200)):
    logs=_reader('/api/logs/search',{"q":q,"lines":500}).get('items',[])
    found=[x for x in list_incidents(500,'all') if q.casefold() in (str(x.get('title',''))+' '+str(x.get('recommendation',''))).casefold()]
    return {"ok":True,"logs":logs,"incidents":found,"learning":best_learning(q)}

@app.websocket('/ws/logs')
async def ws_logs(ws:WebSocket):
    await ws.accept(); service=ws.query_params.get('service','all'); seen=set()
    try:
        while True:
            data=_reader('/api/logs/live',{"service":service,"minutes":2,"lines":250})
            for item in data.get('items',[]):
                key=(item.get('time'),item.get('service'),item.get('message'))
                if key not in seen: seen.add(key); await ws.send_json(item)
            await asyncio.sleep(1)
    except (WebSocketDisconnect,RuntimeError): return

@app.get('/healthz')
def healthz(): return {"ok":True,"service":"top40-ai-sidecar","version":VERSION,"port":8041,"log_reader":LOG_READER}
