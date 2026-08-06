from __future__ import annotations

import os
import socket

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse

from .health_engine import start_health_collector
from .prediction_engine import build_predictions

app = FastAPI(title='Top40Archiver AI Sidecar', version='1.15.0-alpha.4')
start_health_collector()


def _ollama_status() -> dict[str, object]:
    host = os.getenv('OLLAMA_HOST', '127.0.0.1')
    port = int(os.getenv('OLLAMA_PORT', '11434'))
    model = os.getenv('TOP40_AI_MODEL', 'qwen3:4b')
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return {'reachable': True, 'model': model}
    except OSError:
        return {'reachable': False, 'model': model}


@app.get('/', response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse("""<!doctype html><html lang='nl'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Top40 AI Operations</title><style>
:root{color-scheme:light}body{margin:0;background:#f6f3ee;color:#27211c;font-family:Inter,system-ui,sans-serif}.shell{max-width:1180px;margin:auto;padding:30px}.top{display:flex;justify-content:space-between;gap:20px;align-items:center}.badge{display:inline-block;padding:7px 11px;border-radius:999px;background:#e9e0d4;font-size:13px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-top:24px}.card{background:#fff;border:1px solid #e3d9cd;border-radius:20px;padding:20px;box-shadow:0 14px 35px rgba(50,40,30,.07)}.card strong{display:block;font-size:30px;margin-top:8px}.wide{grid-column:span 2}.risk{height:9px;background:#eee7de;border-radius:999px;overflow:hidden;margin-top:12px}.risk span{display:block;height:100%;background:#29231e}.links{display:flex;gap:10px;flex-wrap:wrap}.button{padding:11px 15px;border-radius:12px;background:#29231e;color:#fff;text-decoration:none;border:0;cursor:pointer}.secondary{background:#fff;color:#29231e;border:1px solid #d8cdc0}@media(max-width:800px){.grid{grid-template-columns:1fr 1fr}.wide{grid-column:span 2}}@media(max-width:520px){.grid{grid-template-columns:1fr}.wide{grid-column:auto}.top{align-items:flex-start;flex-direction:column}}</style></head><body><main class='shell'><div class='top'><div><span class='badge'>AI-sidecar · poort 8041</span><h1>Top40 AI Operations</h1><p>Voorspellingen en diagnose staan volledig los van de hoofdinterface op poort 8040.</p></div><div class='links'><a class='button secondary' id='main-link'>Hoofdpagina</a><button class='button' onclick='loadData()'>Vernieuwen</button></div></div><section id='content' class='grid'><article class='card wide'><h2>Analyse wordt geladen…</h2></article></section></main><script>
document.getElementById('main-link').href=location.protocol+'//'+location.hostname+':8040/';const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');async function loadData(){try{const r=await fetch('/api/predictions?range=24h',{cache:'no-store'});const d=await r.json();const p=d.predictions;document.getElementById('content').innerHTML=`<article class='card wide'><span>AI-advies</span><h2>${esc(p.headline)}</h2><p>${esc(p.advice)}</p><small>Zekerheid ${Math.round((p.confidence||0)*100)}%</small></article><article class='card'><span>Health</span><strong>${esc(p.health.score)}%</strong></article><article class='card'><span>Wachtrij klaar in</span><strong>${esc(p.queue_hours)} u</strong></article>${(p.risks||[]).map(x=>`<article class='card'><span>${esc(x.label)}</span><strong>${esc(x.risk)}%</strong><div class='risk'><span style='width:${Number(x.risk)}%'></span></div></article>`).join('')}<article class='card wide'><span>Lokale AI</span><h2>${d.ollama.reachable?'Ollama bereikbaar':'Ollama niet bereikbaar'}</h2><p>Model: ${esc(d.ollama.model)}. De sidecar blijft functioneren als Ollama tijdelijk uitstaat.</p></article>`}catch(e){document.getElementById('content').innerHTML='<article class="card wide"><h2>AI-data tijdelijk niet beschikbaar</h2><p>'+esc(e)+'</p></article>'}}loadData();setInterval(loadData,30000);
</script></body></html>""")


@app.get('/api/predictions')
def predictions(range: str = Query('24h', pattern='^(1h|24h|7d)$')) -> JSONResponse:
    return JSONResponse({'ok': True, 'predictions': build_predictions(range), 'ollama': _ollama_status()})


@app.get('/healthz')
def healthz() -> dict[str, object]:
    return {'ok': True, 'service': 'top40-ai-sidecar', 'version': '1.15.0-alpha.4', 'port': 8041}
