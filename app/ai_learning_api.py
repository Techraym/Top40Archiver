from __future__ import annotations

import json

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from . import ai_memory
from .ai_learning import autonomy_report
from .backup_health import backup_health

router = APIRouter()


def _recent_actions(limit: int) -> list[dict]:
    with ai_memory.connect() as conn:
        rows = conn.execute(
            """
            SELECT id,cycle_id,domain,problem_key,action,subject,reason,status,
                   success,effect_score,operator_needed,reversible,backup_ref,
                   started_at,completed_at,result_json
            FROM action_execution ORDER BY id DESC LIMIT ?
            """,
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        try:
            item["result"] = json.loads(str(item.pop("result_json") or "{}"))
        except json.JSONDecodeError:
            item["result"] = {}
        items.append(item)
    return items


@router.get("/api/ai/learning")
def learning_api(limit: int = Query(100, ge=1, le=500)):
    return {
        "ok": True,
        "autonomy": autonomy_report(7),
        "backup": backup_health(),
        "recent_actions": _recent_actions(limit),
        "policy": {
            "audio_delete_allowed": False,
            "production_shell_allowed": False,
            "version_change_requires_verified_backup": True,
            "learning_from_every_ai_action": True,
        },
    }


@router.get("/ai-learning", response_class=HTMLResponse)
def learning_page() -> HTMLResponse:
    return HTMLResponse("""<!doctype html><html lang='nl'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>AI Learning Center</title><style>
:root{color-scheme:light;--bg:#f6f3ee;--card:#fff;--ink:#26211d;--muted:#756d65;--line:#e6ddd3;--good:#247a49;--warn:#a46b00;--bad:#b52d24}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 Inter,system-ui,sans-serif}.shell{max-width:1250px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.nav{display:flex;gap:8px;flex-wrap:wrap}.btn{display:inline-block;padding:9px 13px;border:1px solid var(--line);border-radius:999px;background:#fff;color:var(--ink);text-decoration:none}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.card{background:#fff;border:1px solid var(--line);border-radius:20px;padding:18px;box-shadow:0 10px 28px rgba(50,40,30,.05)}.wide{grid-column:span 2}.full{grid-column:1/-1}.metric{font-size:32px;font-weight:800}.muted{color:var(--muted)}.good{color:var(--good)}.warn{color:var(--warn)}.bad{color:var(--bad)}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:9px;border-bottom:1px solid var(--line);vertical-align:top}code{font-size:12px;overflow-wrap:anywhere}@media(max-width:850px){.grid{grid-template-columns:1fr 1fr}.wide{grid-column:span 2}}@media(max-width:540px){.grid{grid-template-columns:1fr}.wide{grid-column:auto}.top{flex-direction:column}}</style></head><body><main class='shell'><header class='top'><div><div class='muted'>Top40Archiver 1.16.3</div><h1>AI Learning Center</h1><p class='muted'>Gesloten leerlus: probleem → actie → verificatie → effect → volgende keuze.</p></div><nav class='nav'><a class='btn' href='/operations-worker'>Operations Worker</a><a class='btn' href='/ai-actions'>Downloadherstel</a><a class='btn' href='/'>Operations Center</a></nav></header><section id='view' class='grid'><article class='card full'>Laden…</article></section></main><script>
const e=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');const metric=(t,v,c='')=>`<article class='card'><div class='muted'>${e(t)}</div><div class='metric ${c}'>${e(v)}</div></article>`;async function load(){const box=document.getElementById('view');try{const r=await fetch('/api/ai/learning',{cache:'no-store'}),d=await r.json(),a=d.autonomy||{},x=a.actions||{},b=d.backup||{},top=a.top_learning||[],recent=d.recent_actions||[];box.innerHTML=metric('7-daagse autonomie',`${a.readiness_score??0}%`,a.ready_to_replace_manual_checks?'good':'warn')+metric('Acties geleerd',x.completed??0)+metric('Succesratio',`${Math.round(Number(x.success_rate||0)*100)}%`)+metric('Mens nodig',x.operator_needed??0,(x.operator_needed??0)>0?'bad':'good')+`<article class='card wide'><h2>Doel</h2><p>${e(a.goal)}</p><p><b>${e(a.days_observed)} / ${e(a.target_days)} dagen</b> waargenomen. Zelfstandig beheer gereed: <b class='${a.ready_to_replace_manual_checks?'good':'warn'}'>${a.ready_to_replace_manual_checks?'JA':'nog in leerfase'}</b>.</p></article><article class='card wide'><h2>Rollback-backup</h2><p><b class='${b.ok?'good':'bad'}'>${b.ok?'geverifieerd':'aandacht nodig'}</b></p><p>${e(b.version||'geen versie')} · ${e(b.created_at||'nog geen backup')}</p><p class='muted'>Database: ${b.database_backup?'ja':'nee'} · AI-memory: ${b.ai_memory_backup?'ja':'nee'} · Git-bundle: ${b.repository_bundle?'ja':'nee'} · audio aangeraakt: ${b.audio_library_touched?'JA':'nee'}</p></article><article class='card full'><h2>Geleerde oplossingen</h2><table><tr><th>Probleem</th><th>Actie</th><th>Bewijs</th><th>Succes</th><th>Effect</th></tr>${top.map(y=>`<tr><td><code>${e(y.problem_key)}</code></td><td>${e(y.action)}</td><td>${e(y.evidence_count)}</td><td>${Math.round(Number(y.success_rate||0)*100)}%</td><td>${Number(y.average_effect||0).toFixed(2)}</td></tr>`).join('')||'<tr><td colspan=5>Nog geen herhaalde acties geleerd.</td></tr>'}</table></article><article class='card full'><h2>Laatste AI-acties</h2><table><tr><th>Tijd</th><th>Domein</th><th>Probleem</th><th>Actie</th><th>Resultaat</th></tr>${recent.slice(0,50).map(y=>`<tr><td>${e(y.started_at)}</td><td>${e(y.domain)}</td><td><code>${e(y.problem_key)}</code></td><td>${e(y.action)}</td><td class='${y.status==='pending'?'warn':y.success?'good':'bad'}'>${y.status==='pending'?'wacht op verificatie':y.success?'geslaagd':'mislukt'}</td></tr>`).join('')}</table></article>`}catch(err){box.innerHTML=`<article class='card full bad'><h2>Learning Center niet beschikbaar</h2><p>${e(err)}</p></article>`}}load();setInterval(load,10000);</script></body></html>""")
