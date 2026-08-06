from __future__ import annotations

import os
import socket

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from .health_engine import start_health_collector
from .incident_engine import incident_summary, list_incidents, read_journal, scan_journal
from .prediction_engine import build_predictions

VERSION = "1.15.2"
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
    return HTMLResponse("""<!doctype html><html lang='nl'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Top40 AI Incident Center</title><style>
:root{color-scheme:light}body{margin:0;background:#f6f3ee;color:#27211c;font-family:Inter,system-ui,sans-serif}.shell{max-width:1220px;margin:auto;padding:28px}.top{display:flex;justify-content:space-between;gap:18px;align-items:center}.badge{display:inline-block;padding:7px 11px;border-radius:999px;background:#e9e0d4;font-size:13px}.links{display:flex;gap:10px;flex-wrap:wrap}.button{padding:11px 15px;border-radius:12px;background:#29231e;color:#fff;text-decoration:none;border:0;cursor:pointer}.secondary{background:#fff;color:#29231e;border:1px solid #d8cdc0}.tabs{display:flex;gap:8px;margin:22px 0}.tab{padding:10px 14px;border-radius:12px;border:1px solid #d8cdc0;background:#fff;cursor:pointer}.tab.active{background:#29231e;color:#fff}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.card{background:#fff;border:1px solid #e3d9cd;border-radius:20px;padding:20px;box-shadow:0 14px 35px rgba(50,40,30,.07)}.wide{grid-column:span 2}.full{grid-column:1/-1}.critical{border-left:6px solid #b42318}.warning{border-left:6px solid #b77700}.ok{border-left:6px solid #27864a}.metric{font-size:30px;font-weight:800}.incident{display:grid;grid-template-columns:1fr auto;gap:12px;margin-top:12px;padding:15px;border:1px solid #e6ded4;border-radius:14px}.incident pre{white-space:pre-wrap;max-height:120px;overflow:auto;background:#f7f4ef;padding:10px;border-radius:10px}.log{background:#201d1a;color:#f5f0e8;padding:16px;border-radius:16px;white-space:pre-wrap;max-height:560px;overflow:auto;font:12px/1.5 ui-monospace,monospace}@media(max-width:800px){.grid{grid-template-columns:1fr 1fr}.wide{grid-column:span 2}}@media(max-width:520px){.grid{grid-template-columns:1fr}.wide{grid-column:auto}.top{align-items:flex-start;flex-direction:column}}</style></head><body><main class='shell'><div class='top'><div><span class='badge'>AI-sidecar · 8041 · v1.15.2</span><h1>AI Incident Center</h1><p>Voorspellingen, incidenten en live logs staan los van de hoofdinterface.</p></div><div class='links'><a class='button secondary' id='main-link'>Hoofdpagina</a><button class='button' onclick='scanNow()'>Nu scannen</button></div></div><div class='tabs'><button class='tab active' onclick="showTab('incidents',this)">Incidenten</button><button class='tab' onclick="showTab('health',this)">Voorspellingen</button><button class='tab' onclick="showTab('logs',this)">Live logs</button></div><section id='content' class='grid'><article class='card full'><h2>Gegevens worden geladen…</h2></article></section></main><script>
document.getElementById('main-link').href=location.protocol+'//'+location.hostname+':8040/';let current='incidents';const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');function showTab(name,b){current=name;document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));b.classList.add('active');loadData()}async function scanNow(){await fetch('/api/incidents/scan',{method:'POST'});current='incidents';loadData()}async function loadData(){const box=document.getElementById('content');try{if(current==='incidents'){const r=await fetch('/api/incidents?status=open',{cache:'no-store'}),d=await r.json(),s=d.summary,c=s.counts||{},items=d.incidents||[];box.innerHTML=`<article class='card ${s.circuit_breaker.active?'critical':'ok'}'><span>Circuit breaker</span><div class='metric'>${s.circuit_breaker.active?'ACTIEF':'VRIJ'}</div></article><article class='card critical'><span>Kritiek</span><div class='metric'>${c.critical||0}</div></article><article class='card warning'><span>Waarschuwingen</span><div class='metric'>${c.warning||0}</div></article><article class='card'><span>Open incidenten</span><div class='metric'>${items.length}</div></article><article class='card full'><h2>Incidenten</h2>${items.length?items.map(x=>`<div class='incident ${esc(x.severity)}'><div><b>${esc(x.title)}</b><p>${esc(x.recommendation)}</p><details><summary>Bewijs</summary><pre>${esc(x.evidence)}</pre></details></div><div><b>${Math.round(Number(x.confidence)*100)}%</b><br><small>${x.occurrences}×</small></div></div>`).join(''):'<p>Geen open incidenten.</p>'}</article>`}else if(current==='health'){const r=await fetch('/api/predictions?range=24h',{cache:'no-store'}),d=await r.json(),p=d.predictions;box.innerHTML=`<article class='card wide'><h2>${esc(p.headline)}</h2><p>${esc(p.advice)}</p></article><article class='card'><span>Health</span><div class='metric'>${esc(p.health.score)}%</div></article><article class='card'><span>Wachtrij</span><div class='metric'>${esc(p.queue_hours)} u</div></article>${(p.risks||[]).map(x=>`<article class='card'><b>${esc(x.label)}</b><div class='metric'>${esc(x.risk)}%</div></article>`).join('')}`}else{const r=await fetch('/api/logs?minutes=30&lines=500',{cache:'no-store'}),d=await r.text();box.innerHTML=`<article class='card full'><h2>Laatste logregels</h2><pre class='log'>${esc(d)}</pre></article>`}}catch(e){box.innerHTML=`<article class='card full critical'><h2>Data niet beschikbaar</h2><p>${esc(e)}</p></article>`}}loadData();setInterval(loadData,30000);
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


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {"ok": True, "service": "top40-ai-sidecar", "version": VERSION, "port": 8041}
