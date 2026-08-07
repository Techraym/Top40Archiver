from __future__ import annotations

import json
from pathlib import Path

from fastapi import Query
from fastapi.responses import HTMLResponse

from .ai_sidecar import app
from .config import DATA_DIR

REPORT_FILE = DATA_DIR / "ai" / "last-recovery-report.json"
HISTORY_FILE = DATA_DIR / "ai" / "recovery-history.jsonl"
STATE_FILE = DATA_DIR / "ai" / "recovery-state.json"


def _json_file(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _history(limit: int = 50) -> list[dict]:
    try:
        lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    items: list[dict] = []
    for line in reversed(lines[-max(1, limit):]):
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return items


@app.get("/api/recovery/actions")
@app.get("/api/ai/recovery")
def recovery_actions(limit: int = Query(25, ge=1, le=200)):
    report = _json_file(REPORT_FILE, {})
    state = _json_file(STATE_FILE, {})
    return {
        "ok": True,
        "available": bool(report),
        "report": report,
        "state": state,
        "history": _history(limit),
        "report_path": str(REPORT_FILE),
    }


@app.get("/ai-actions", response_class=HTMLResponse)
def ai_actions_page() -> HTMLResponse:
    return HTMLResponse("""<!doctype html><html lang='nl'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>AI-herstelactiviteiten</title><style>
:root{color-scheme:light;--bg:#f6f3ee;--card:#fff;--ink:#26211d;--muted:#756d65;--line:#e6ddd3;--good:#247a49;--warn:#ae7000;--bad:#b52d24;--accent:#ef5846}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 Inter,system-ui,sans-serif}.shell{max-width:1250px;margin:auto;padding:26px}.top{display:flex;justify-content:space-between;gap:20px;align-items:center}.nav{display:flex;gap:8px;flex-wrap:wrap}.btn{display:inline-block;border:1px solid var(--line);background:#fff;color:var(--ink);text-decoration:none;border-radius:999px;padding:10px 15px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.card{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:18px;box-shadow:0 12px 32px rgba(60,45,30,.06)}.wide{grid-column:span 2}.full{grid-column:1/-1}.metric{font-size:32px;font-weight:800}.muted{color:var(--muted)}.good{color:var(--good)}.warn{color:var(--warn)}.bad{color:var(--bad)}.decision{border-left:5px solid var(--accent)}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px;border-bottom:1px solid var(--line);vertical-align:top}pre{white-space:pre-wrap;overflow:auto;background:#211e1b;color:#f7f2eb;padding:14px;border-radius:14px}.repair{padding:10px 0;border-bottom:1px solid var(--line)}.repair:last-child{border-bottom:0}.strategy{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:3px 7px;margin-left:6px;font-size:12px}.query{margin-top:4px;color:var(--muted);font-family:ui-monospace,monospace;font-size:12px;overflow-wrap:anywhere}@media(max-width:800px){.grid{grid-template-columns:1fr 1fr}.wide{grid-column:span 2}}@media(max-width:520px){.grid{grid-template-columns:1fr}.wide{grid-column:auto}.top{align-items:flex-start;flex-direction:column}}</style></head><body><main class='shell'><header class='top'><div><div class='muted'>Top40Archiver 1.16.3</div><h1>AI-herstelactiviteiten</h1><p class='muted'>Wat de AI ziet, besluit, uitvoert en daarna controleert.</p></div><div class='nav'><a class='btn' href='/development'>Development Assistant</a><a class='btn' href='/'>Operations Center</a></div></header><section id='view' class='grid'><article class='card full'>Laden…</article></section></main><script>
const e=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');function card(t,v,c=''){return `<article class='card ${c}'><div class='muted'>${e(t)}</div><div class='metric'>${e(v)}</div></article>`}function actionResult(y){if(y.result)return y.result;if(y.restart?.ok===true)return 'Gelukt';if(y.restart?.ok===false)return 'Mislukt';return 'Uitgevoerd'}async function load(){const box=document.getElementById('view');try{const r=await fetch('/api/ai/recovery',{cache:'no-store'}),d=await r.json(),x=d.report||{},a=x.actions||[],cats=x.categories||{},decision=x.decision||{},verify=x.verification||{},repairs=a.flatMap(y=>y.repairs||[]);box.innerHTML=card('Laatste cyclus',x.generated_at?new Date(x.generated_at).toLocaleString():'Nog niet uitgevoerd')+card('Mislukte downloads',x.failure_count??0)+card('Herstelbaar',x.retryable_count??0)+card('Uitgevoerde acties',a.length,a.length?'good':'warn')+`<article class='card wide decision'><h2>AI-besluit</h2><p><b>${e(decision.status||'Geen besluit beschikbaar')}</b> · ${Math.round(Number(decision.confidence||0)*100)}%</p><p>${e(decision.reason||'De eerste herstelcyclus heeft nog geen rapport geschreven.')}</p></article><article class='card wide'><h2>Controle na actie</h2><p><b>${e(verify.pending_after??0)}</b> in wachtrij · <b>${e(verify.downloading_after??0)}</b> bezig · <b>${e(verify.failed_after??0)}</b> mislukt</p><p>Downloader-herstart: <b class='${verify.download_service_restart_ok===false?'bad':'good'}'>${verify.download_service_restart_ok===false?'niet bevestigd':'OK'}</b></p></article><article class='card wide'><h2>Aanbevelingen</h2>${(x.recommendations||[]).map(y=>`<p>${e(y)}</p>`).join('')||'<p>Geen nieuwe aanbevelingen.</p>'}</article><article class='card wide'><h2>Foutcategorieën</h2><table><tr><th>Categorie</th><th>Aantal</th></tr>${Object.entries(cats).map(([k,v])=>`<tr><td>${e(k)}</td><td>${e(v)}</td></tr>`).join('')||'<tr><td colspan=2>Geen fouten gevonden.</td></tr>'}</table></article><article class='card full'><h2>Uitgevoerde acties</h2><table><tr><th>Actie</th><th>Vrijgegeven</th><th>Resultaat</th></tr>${a.map(y=>`<tr><td>${e(y.action)}</td><td>${e(y.released??'-')}</td><td>${e(actionResult(y))}</td></tr>`).join('')||'<tr><td colspan=3>Deze cyclus hoefde niets uit te voeren.</td></tr>'}</table></article><article class='card full'><h2>Herstelstrategieën per track</h2>${repairs.length?repairs.map(y=>`<div class='repair'><b>#${e(y.id)} ${e(y.artist)} — ${e(y.title)}</b><span class='strategy'>${e(y.strategy)}</span><div class='muted'>${e(y.category)} · herstelpoging ${e(y.recovery_number)}</div><div class='query'>${e(y.query||'standaard brede zoekstrategie')}</div></div>`).join(''):'<p>Deze cyclus zijn geen individuele tracks aangepast.</p>'}</article><article class='card full'><h2>Volledig rapport</h2><pre>${e(JSON.stringify(x,null,2))}</pre></article>`}catch(err){box.innerHTML=`<article class='card full bad'><h2>Rapport niet beschikbaar</h2><p>${e(err)}</p></article>`}}load();setInterval(load,10000);
</script></body></html>""")
