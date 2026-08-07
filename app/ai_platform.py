from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from . import ai_sidecar as operations
from . import ai_operations_app as recovery_ui  # noqa: F401 - registreert recovery-routes op operations.app
from .ai_worker_dashboard import router as worker_router
from .dev_assistant_api import router as development_router

VERSION = "1.16.2"
app = FastAPI(title="Top40Archiver AI Platform", version=VERSION)


@app.get("/healthz")
def healthz():
    return {
        "ok": True,
        "service": "top40-ai-platform",
        "version": VERSION,
        "port": 8041,
        "operations_center": True,
        "recovery_dashboard": True,
        "operations_worker": True,
        "cover_drain_worker": True,
        "development_assistant": True,
        "production_write": False,
    }


@app.get("/development", response_class=HTMLResponse)
def development_dashboard() -> HTMLResponse:
    return HTMLResponse("""<!doctype html><html lang='nl'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Top40 AI Development Assistant</title><style>
:root{--bg:#f5f2ed;--card:#fff;--ink:#25211e;--muted:#746c64;--line:#e3dad0;--ok:#247a49;--bad:#b52d24}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 Inter,system-ui,sans-serif}.shell{max-width:1300px;margin:auto;padding:28px}.top{display:flex;justify-content:space-between;gap:20px;align-items:flex-start}.badge{display:inline-block;border:1px solid var(--line);background:#fff;padding:7px 11px;border-radius:999px;color:var(--ink);text-decoration:none}.nav{display:flex;gap:8px;flex-wrap:wrap}.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:15px;margin-top:22px}.card{grid-column:span 4;background:var(--card);border:1px solid var(--line);border-radius:20px;padding:18px;box-shadow:0 12px 30px rgba(50,40,30,.06)}.wide{grid-column:span 8}.full{grid-column:1/-1}.muted{color:var(--muted)}.ok{color:var(--ok)}.bad{color:var(--bad)}button,input,textarea{font:inherit;border:1px solid var(--line);border-radius:12px;padding:11px;background:#fff;color:var(--ink)}button{cursor:pointer;background:var(--ink);color:#fff}textarea,input{width:100%;margin:5px 0 12px}textarea{min-height:110px}pre{background:#211e1b;color:#f7f2eb;padding:15px;border-radius:14px;max-height:420px;overflow:auto;white-space:pre-wrap}.item{padding:14px 0;border-bottom:1px solid var(--line)}@media(max-width:800px){.card,.wide{grid-column:1/-1}.top{flex-direction:column}}</style></head><body><main class='shell'><header class='top'><div><span class='badge'>Top40Archiver 1.16.2</span><h1>AI Development Assistant</h1><p class='muted'>Analyse → sandboxpatch → tests → reviewplan. Productie blijft onaangeraakt.</p></div><div class='nav'><a href='/operations-worker' class='badge'>Operations Worker</a><a href='/ai-actions' class='badge'>AI-herstelactiviteiten</a><a href='/' class='badge'>Operations Center</a></div></header><section class='grid'><article class='card wide'><h2>Nieuwe analyse</h2><label>Titel</label><input id='title' placeholder='Bijvoorbeeld: downloader herstelt 429 niet'><label>Probleem</label><textarea id='problem' placeholder='Beschrijf fout, verwacht gedrag en relevante context.'></textarea><button onclick='createWorkspace()'>Werkruimte maken</button><p id='create-result' class='muted'></p></article><article class='card'><h2>Veiligheidsstatus</h2><p class='ok'><b>Sandbox-only</b></p><p>Geen directe productiewrites.</p><p>Geen automatische merge.</p><p>PR pas na validatie en review.</p></article><article class='card full'><h2>Werkruimtes</h2><div id='items'>Laden…</div></article></section></main><script>
const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');async function api(url,opt){const r=await fetch(url,opt);if(!r.ok)throw Error(await r.text());return r.json()}async function load(){try{const d=await api('/api/development/workspaces');document.getElementById('items').innerHTML=d.items.length?d.items.map(x=>`<div class='item'><b>${esc(x.title)}</b> <span class='muted'>${esc(x.status)}</span><br><small>${esc(x.id)} · ${esc(new Date(x.created_at).toLocaleString())}</small><p>${esc(x.problem)}</p><button onclick="inspect('${x.id}')">Details</button><div id='d-${x.id}'></div></div>`).join(''):'<p>Nog geen werkruimtes.</p>'}catch(e){document.getElementById('items').innerHTML='<p class="bad">'+esc(e)+'</p>'}}async function createWorkspace(){const box=document.getElementById('create-result');try{const d=await api('/api/development/workspaces',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:document.getElementById('title').value,problem:document.getElementById('problem').value})});box.textContent='Werkruimte gemaakt: '+d.workspace.id;load()}catch(e){box.textContent=e}}async function inspect(id){const target=document.getElementById('d-'+id);try{const d=await api('/api/development/workspaces/'+id);target.innerHTML='<pre>'+esc(JSON.stringify(d,null,2))+'</pre>'}catch(e){target.textContent=e}}load();setInterval(load,30000);
</script></body></html>""")


app.include_router(worker_router)
app.include_router(development_router)
app.include_router(operations.app.router)
