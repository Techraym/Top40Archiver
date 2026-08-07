from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from .config import DATA_DIR

router = APIRouter()
REPORT_FILE = DATA_DIR / "ai" / "last-operations-worker-report.json"


def _report() -> dict:
    try:
        payload = json.loads(REPORT_FILE.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


@router.get("/api/ai/operations-worker")
def operations_worker_report():
    report = _report()
    return {
        "ok": True,
        "available": bool(report),
        "report": report,
        "report_path": str(REPORT_FILE),
    }


@router.get("/operations-worker", response_class=HTMLResponse)
def operations_worker_page() -> HTMLResponse:
    return HTMLResponse("""<!doctype html><html lang='nl'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>AI Operations Worker</title><style>
:root{color-scheme:light;--bg:#f6f3ee;--card:#fff;--ink:#26211d;--muted:#756d65;--line:#e6ddd3;--ok:#247a49;--warn:#ae7000;--bad:#b52d24;--accent:#ef5846}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 Inter,system-ui,sans-serif}.shell{max-width:1250px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.nav{display:flex;gap:8px;flex-wrap:wrap}.btn{border:1px solid var(--line);background:#fff;color:var(--ink);text-decoration:none;border-radius:999px;padding:9px 13px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:20px}.card{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:18px;box-shadow:0 12px 32px rgba(60,45,30,.06)}.wide{grid-column:span 2}.full{grid-column:1/-1}.metric{font-size:30px;font-weight:800}.muted{color:var(--muted)}.good{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:9px;border-bottom:1px solid var(--line);vertical-align:top}pre{white-space:pre-wrap;overflow:auto;background:#211e1b;color:#f7f2eb;padding:14px;border-radius:14px;max-height:520px}@media(max-width:800px){.grid{grid-template-columns:1fr 1fr}.wide{grid-column:span 2}.top{flex-direction:column}}@media(max-width:520px){.grid{grid-template-columns:1fr}.wide{grid-column:auto}}</style></head><body><main class='shell'><header class='top'><div><div class='muted'>Top40Archiver 1.16.2 · iedere 5 minuten</div><h1>AI Operations Worker</h1><p class='muted'>Policy-first herstel. Qwen analyseert en verklaart, maar kan geen vrije systeemcommando's uitvoeren.</p></div><nav class='nav'><a class='btn' href='/ai-actions'>Downloadherstel</a><a class='btn' href='/'>Operations Center</a></nav></header><section id='view' class='grid'><article class='card full'>Laden…</article></section></main><script>
const e=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');const card=(t,v,c='')=>`<article class='card ${c}'><div class='muted'>${e(t)}</div><div class='metric'>${e(v)}</div></article>`;async function load(){const box=document.getElementById('view');try{const r=await fetch('/api/ai/operations-worker',{cache:'no-store'}),d=await r.json(),x=d.report||{},a=x.after||{},c=a.covers||{},db=a.database||{},disk=a.disk||{},oll=a.ollama||{},m=x.model_assessment||{},acts=x.actions||[];box.innerHTML=card('Coverwachtrij',c.eligible_queue??'-',Number(c.eligible_queue||0)>0?'warn':'good')+card('Coverworker',c.running?'Bezig':(c.phase||'Stand-by'),c.running?'good':'')+card('Database',db.health||'-',db.health==='ok'?'good':'bad')+card('Vrije schijf',disk.free_percent!=null?disk.free_percent+'%':'-',Number(disk.free_percent||0)<10?'warn':'good')+`<article class='card wide'><h2>Coververwerking</h2><p><b>${e(c.processed_total??0)}</b> verwerkt in deze drain-run · <b>${e(c.found_total??0)}</b> gevonden · <b>${e(c.missing_total??0)}</b> zonder match.</p><p>Nu: ${e(c.current_artist||'-')} ${c.current_title?'— '+e(c.current_title):''}</p><p class='muted'>${e(c.per_minute??0)} per minuut · laatste update ${e(c.updated_at||'-')}</p></article><article class='card wide'><h2>Qwen analyse</h2><p><b>Risico: ${e(m.risk||'onbekend')}</b></p><p>${e(m.summary||'Nog geen modelanalyse beschikbaar.')}</p>${(m.attention||[]).map(y=>`<p class='warn'>${e(y)}</p>`).join('')}</article><article class='card full'><h2>Automatische acties</h2><table><tr><th>Actie</th><th>Reden</th><th>Resultaat</th></tr>${acts.map(y=>`<tr><td>${e(y.action)}</td><td>${e(y.reason||'-')}</td><td class='${y.ok?'good':'bad'}'>${y.ok?'Gelukt':'Mislukt'}</td></tr>`).join('')||'<tr><td colspan=3>Geen actie nodig in de laatste cyclus.</td></tr>'}</table></article><article class='card wide'><h2>Systeemstatus</h2><p>Ollama: <b class='${oll.reachable?'good':'bad'}'>${oll.reachable?'bereikbaar':'niet bereikbaar'}</b></p><p>DB-fragmentatie: ${e(db.fragmentation_percent??'-')}%</p><p>Covers zonder match/uitgestelde retry: ${e(c.processed_without_match??0)}</p></article><article class='card wide'><h2>Aanbevelingen</h2>${(x.recommendations||[]).map(y=>`<p>${e(y)}</p>`).join('')||'<p>Geen aanvullende aanbevelingen.</p>'}</article><article class='card full'><h2>Volledig worker-rapport</h2><pre>${e(JSON.stringify(x,null,2))}</pre></article>`}catch(err){box.innerHTML=`<article class='card full bad'><h2>Niet beschikbaar</h2><p>${e(err)}</p></article>`}}load();setInterval(load,10000);
</script></body></html>""")
