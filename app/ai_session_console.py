from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import ai_memory

router = APIRouter()
MODEL = os.getenv("TOP40_AI_MODEL", "qwen3:4b")
VALID_SCOPES = {
    "global",
    "operations",
    "downloads",
    "covers",
    "charts",
    "services",
    "storage",
    "code",
    "ui",
}
VALID_MODES = {"guidance", "hold"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_value(value: object) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except Exception:
        return {}


def log_session_event(
    *,
    event_type: str,
    title: str,
    message: str,
    cycle_id: str | None = None,
    domain: str = "system",
    role: str = "assistant",
    status: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    """Auditbare werknotitie; dit is een beslissamenvatting, geen verborgen model-chain-of-thought."""
    with ai_memory.connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO ai_session_event(
              cycle_id,event_type,domain,role,title,message,status,metadata_json,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                cycle_id,
                str(event_type)[:60],
                str(domain)[:60],
                str(role)[:30],
                str(title)[:300],
                str(message)[:12000],
                str(status)[:60] if status is not None else None,
                json.dumps(metadata or {}, ensure_ascii=False),
                _now(),
            ),
        )
        return int(cursor.lastrowid)


def list_session_events(*, after_id: int = 0, limit: int = 200) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 1000))
    after_id = max(0, int(after_id))
    with ai_memory.connect() as conn:
        if after_id:
            rows = conn.execute(
                "SELECT * FROM ai_session_event WHERE id>? ORDER BY id ASC LIMIT ?",
                (after_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM ai_session_event ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            rows = list(reversed(rows))
    return [dict(row) | {"metadata": _json_value(row["metadata_json"])} for row in rows]


def create_operator_guidance(instruction: str, *, scope: str = "global", mode: str = "guidance") -> dict[str, Any]:
    scope = str(scope or "global").strip().lower()
    mode = str(mode or "guidance").strip().lower()
    instruction = str(instruction or "").strip()
    if scope not in VALID_SCOPES:
        raise ValueError(f"ongeldige scope: {scope}")
    if mode not in VALID_MODES:
        raise ValueError(f"ongeldige mode: {mode}")
    if len(instruction) < 2 or len(instruction) > 4000:
        raise ValueError("instructie moet 2-4000 tekens bevatten")
    now = _now()
    with ai_memory.connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO operator_guidance(scope,mode,instruction,status,created_at,updated_at)
            VALUES(?,?,?,'active',?,?)
            """,
            (scope, mode, instruction, now, now),
        )
        guidance_id = int(cursor.lastrowid)
    log_session_event(
        event_type="operator_guidance",
        title="Menselijke operatorrichtlijn",
        message=instruction,
        domain=scope,
        role="operator",
        status="hold" if mode == "hold" else "active",
        metadata={"guidance_id": guidance_id, "scope": scope, "mode": mode},
    )
    ai_memory.remember_event(
        "operator_guidance",
        instruction,
        service="ai-session",
        metadata={"guidance_id": guidance_id, "scope": scope, "mode": mode},
    )
    return {
        "id": guidance_id,
        "scope": scope,
        "mode": mode,
        "instruction": instruction,
        "status": "active",
        "created_at": now,
    }


def list_operator_guidance(status: str = "active", limit: int = 200) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 1000))
    with ai_memory.connect() as conn:
        if status == "all":
            rows = conn.execute(
                "SELECT * FROM operator_guidance ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM operator_guidance WHERE status=? ORDER BY id DESC LIMIT ?",
                (status, limit),
            ).fetchall()
    return [dict(row) for row in rows]


def active_guidance(scope: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
    with ai_memory.connect() as conn:
        if scope and scope != "global":
            rows = conn.execute(
                """
                SELECT * FROM operator_guidance
                WHERE status='active' AND scope IN ('global',?)
                ORDER BY CASE WHEN scope=? THEN 0 ELSE 1 END,id DESC LIMIT ?
                """,
                (scope, scope, max(1, min(int(limit), 100))),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM operator_guidance WHERE status='active' ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 100)),),
            ).fetchall()
    return [dict(row) for row in rows]


def operator_context(scope: str | None = None, limit: int = 12) -> str:
    items = active_guidance(scope, limit)
    if not items:
        return "Geen actieve menselijke operatorrichtlijnen."
    lines = [
        "ACTIEVE MENSELIJKE OPERATORRICHTLIJNEN. Deze sturen de lokale AI binnen alle bestaande harde veiligheidsregels; ze mogen veiligheidsgrenzen nooit versoepelen:"
    ]
    for item in reversed(items):
        mode = "HARD HOLD" if item.get("mode") == "hold" else "RICHTLIJN"
        lines.append(f"- #{item['id']} [{mode}] scope={item['scope']}: {item['instruction']}")
    return "\n".join(lines)


def scope_held(scope: str) -> bool:
    return any(item.get("mode") == "hold" for item in active_guidance(scope, 100))


def mark_guidance_applied(scope: str, cycle_id: str) -> list[int]:
    items = active_guidance(scope, 100)
    ids = [int(item["id"]) for item in items]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with ai_memory.connect() as conn:
        conn.execute(
            f"UPDATE operator_guidance SET last_applied_at=?,updated_at=? WHERE id IN ({placeholders})",
            (_now(), _now(), *ids),
        )
    log_session_event(
        event_type="guidance_applied",
        title="Operatorrichtlijnen geladen",
        message=f"Ik neem {len(ids)} actieve operatorrichtlijn(en) mee in deze autonome cyclus.",
        cycle_id=cycle_id,
        domain=scope,
        role="assistant",
        status="applied",
        metadata={"guidance_ids": ids},
    )
    return ids


def close_guidance(guidance_id: int) -> dict[str, Any]:
    now = _now()
    with ai_memory.connect() as conn:
        row = conn.execute("SELECT * FROM operator_guidance WHERE id=?", (int(guidance_id),)).fetchone()
        if not row:
            raise KeyError(guidance_id)
        conn.execute(
            "UPDATE operator_guidance SET status='closed',updated_at=?,closed_at=? WHERE id=?",
            (now, now, int(guidance_id)),
        )
    item = dict(row)
    log_session_event(
        event_type="operator_guidance_closed",
        title="Operatorrichtlijn beëindigd",
        message=str(item.get("instruction") or ""),
        domain=str(item.get("scope") or "global"),
        role="operator",
        status="closed",
        metadata={"guidance_id": int(guidance_id)},
    )
    return {"ok": True, "id": int(guidance_id), "status": "closed"}


def session_status() -> dict[str, Any]:
    with ai_memory.connect() as conn:
        latest = conn.execute("SELECT * FROM ai_session_event ORDER BY id DESC LIMIT 1").fetchone()
        active_cycle = conn.execute(
            "SELECT cycle_id,started_at,completed_at,ok FROM autonomy_cycle ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    latest_item = dict(latest) if latest else None
    if latest_item:
        latest_item["metadata"] = _json_value(latest_item.pop("metadata_json", "{}"))
    return {
        "ok": True,
        "model": MODEL,
        "autonomous": True,
        "human_approval_required_for_each_cycle": False,
        "operator_can_guide": True,
        "operator_can_hold_domains": True,
        "raw_chain_of_thought_exposed": False,
        "decision_summaries_exposed": True,
        "latest_event": latest_item,
        "latest_cycle": dict(active_cycle) if active_cycle else None,
        "active_guidance": list_operator_guidance("active", 100),
    }


class GuidanceIn(BaseModel):
    instruction: str = Field(min_length=2, max_length=4000)
    scope: str = Field(default="global", min_length=2, max_length=30)
    mode: str = Field(default="guidance", min_length=4, max_length=20)


@router.get("/api/ai/session/status")
def api_session_status():
    return session_status()


@router.get("/api/ai/session/events")
def api_session_events(
    after_id: int = Query(0, ge=0),
    limit: int = Query(250, ge=1, le=1000),
):
    items = list_session_events(after_id=after_id, limit=limit)
    return {"ok": True, "items": items, "last_id": items[-1]["id"] if items else after_id}


@router.get("/api/ai/session/guidance")
def api_guidance(status: str = Query("active", pattern="^(active|closed|all)$")):
    return {"ok": True, "items": list_operator_guidance(status, 500)}


@router.post("/api/ai/session/guidance")
def api_create_guidance(payload: GuidanceIn):
    try:
        item = create_operator_guidance(payload.instruction, scope=payload.scope, mode=payload.mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "guidance": item}


@router.post("/api/ai/session/guidance/{guidance_id}/close")
def api_close_guidance(guidance_id: int):
    try:
        return close_guidance(guidance_id)
    except KeyError as exc:
        raise HTTPException(404, "operatorrichtlijn niet gevonden") from exc


SESSION_HTML = r"""<!doctype html>
<html lang="nl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Top40Archiver · Qwen AI Session</title>
<style>
:root{--bg:#f4f6f8;--panel:#fff;--ink:#171a1f;--muted:#727983;--line:#dfe4e9;--ai:#fff;--op:#dceeff;--sys:#eef1f4;--good:#157a47;--warn:#9a6510;--bad:#b42318;--accent:#1268d7}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 Inter,system-ui,-apple-system,sans-serif}.shell{height:100vh;display:grid;grid-template-rows:auto 1fr auto;max-width:1180px;margin:auto;background:var(--panel);box-shadow:0 0 0 1px var(--line)}header{padding:14px 18px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:16px;align-items:center}.title{display:flex;gap:12px;align-items:center}.dot{width:10px;height:10px;border-radius:50%;background:#1ea765;box-shadow:0 0 0 4px #dff7e9}.nav{display:flex;gap:8px;flex-wrap:wrap}.nav a{color:var(--ink);text-decoration:none;border:1px solid var(--line);padding:7px 10px;border-radius:999px;background:#fff}.status{font-size:13px;color:var(--muted)}main{overflow:auto;padding:22px 18px 130px}.stream{max-width:900px;margin:auto}.msg{display:grid;grid-template-columns:42px minmax(0,1fr);gap:10px;margin:0 0 18px}.msg.operator{grid-template-columns:minmax(0,1fr) 42px}.avatar{width:34px;height:34px;border-radius:50%;display:grid;place-items:center;font-weight:700;background:#191c21;color:#fff}.operator .avatar{grid-column:2;background:#1268d7}.bubble{background:var(--ai);border:1px solid var(--line);border-radius:18px;padding:13px 15px;box-shadow:0 1px 2px #0000000b}.operator .bubble{grid-column:1;grid-row:1;background:var(--op)}.system .bubble{background:var(--sys)}.meta{font-size:12px;color:var(--muted);margin-bottom:5px;display:flex;gap:8px;flex-wrap:wrap}.message{white-space:pre-wrap;overflow-wrap:anywhere}.details{margin-top:9px}.details summary{cursor:pointer;color:var(--muted)}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;background:#101419;color:#e9eef3;padding:10px;border-radius:10px;max-height:360px;overflow:auto}.guidance{position:sticky;bottom:0;border-top:1px solid var(--line);padding:12px 16px;background:#ffffffef;backdrop-filter:blur(10px)}.composer{max-width:900px;margin:auto;border:1px solid var(--line);border-radius:18px;padding:10px;background:#fff;box-shadow:0 10px 30px #0001}.composer textarea{width:100%;resize:vertical;min-height:58px;max-height:180px;border:0;outline:0;font:inherit;color:var(--ink)}.controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.controls select,.controls button{font:inherit;border:1px solid var(--line);padding:8px 10px;border-radius:10px;background:#fff}.controls button{background:var(--accent);border-color:var(--accent);color:#fff;cursor:pointer}.controls button.hold{background:#fff;color:var(--bad);border-color:#e7a6a1}.active{max-width:900px;margin:0 auto 10px;font-size:12px;color:var(--muted)}.pill{display:inline-flex;gap:5px;align-items:center;border:1px solid var(--line);border-radius:999px;padding:4px 8px;margin:2px;background:#fff}.pill.hold{border-color:#e7a6a1;color:var(--bad)}.pill button{border:0;background:none;color:inherit;cursor:pointer;padding:0 2px}@media(max-width:700px){header{align-items:flex-start;flex-direction:column}.msg{grid-template-columns:34px minmax(0,1fr)}.msg.operator{grid-template-columns:minmax(0,1fr) 34px}main{padding:14px 10px 150px}.guidance{padding:10px}.controls select{max-width:145px}}
</style></head><body><div class="shell"><header><div class="title"><span class="dot"></span><div><b>Qwen AI Session</b><div class="status" id="status">Autonoom actief · laden…</div></div></div><nav class="nav"><a href="/" target="_blank">Control Room</a><a href="/ai-learning" target="_blank">Learning</a><a href="/ai-actions" target="_blank">Herstelacties</a></nav></header><main id="main"><div class="stream" id="stream"><p>AI-werklog laden…</p></div></main><section class="guidance"><div class="active" id="active-guidance"></div><div class="composer"><textarea id="instruction" placeholder="Alleen nodig als je Qwen wilt bijsturen. Zonder input blijft de AI autonoom werken."></textarea><div class="controls"><select id="scope"><option value="global">Alles</option><option value="operations">Operations</option><option value="downloads">Downloads</option><option value="covers">Covers</option><option value="charts">Charts</option><option value="services">Services</option><option value="storage">Opslag</option><option value="code">Code</option><option value="ui">8041 UI</option></select><button onclick="sendGuidance('guidance')">Richtlijn sturen</button><button class="hold" onclick="sendGuidance('hold')">Pauzeer domein</button><span class="status" id="send-status">Geen input nodig voor autonoom werk.</span></div></div></section></div>
<script>
'use strict';let lastId=0;const seen=new Set();const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');const fmt=t=>{try{return new Date(t).toLocaleString()}catch(_){return t}};function bubble(x){const role=x.role==='operator'?'operator':x.role==='system'?'system':'';const av=role==='operator'?'M':role==='system'?'S':'Q';const details=x.metadata&&Object.keys(x.metadata).length?`<details class="details"><summary>Technische details</summary><pre>${esc(JSON.stringify(x.metadata,null,2))}</pre></details>`:'';return `<article class="msg ${role}"><div class="avatar">${av}</div><div class="bubble"><div class="meta"><b>${esc(x.title)}</b><span>${esc(x.domain)}</span><span>${esc(x.status||'')}</span><span>${esc(fmt(x.created_at))}</span></div><div class="message">${esc(x.message)}</div>${details}</div></article>`}function append(items,initial=false){const stream=document.getElementById('stream');if(initial)stream.innerHTML='';let added=0;for(const x of items){if(seen.has(x.id))continue;seen.add(x.id);stream.insertAdjacentHTML('beforeend',bubble(x));lastId=Math.max(lastId,Number(x.id||0));added++}if(added){const main=document.getElementById('main');const near=main.scrollHeight-main.scrollTop-main.clientHeight<260;if(initial||near)main.scrollTop=main.scrollHeight}}async function api(url,opt){const r=await fetch(url,opt);if(!r.ok)throw Error(await r.text());return r.json()}async function loadInitial(){try{const d=await api('/api/ai/session/events?limit=250');append(d.items||[],true);await loadStatus()}catch(e){document.getElementById('stream').innerHTML='<p>'+esc(e)+'</p>'}}async function poll(){try{const d=await api('/api/ai/session/events?after_id='+lastId+'&limit=250');append(d.items||[]);await loadStatus()}catch(_){}}async function loadStatus(){const d=await api('/api/ai/session/status');document.getElementById('status').textContent=`Autonoom actief · ${d.model} · ${d.active_guidance.length} actieve operatorrichtlijn(en)`;const box=document.getElementById('active-guidance');box.innerHTML=d.active_guidance.length?'Actief: '+d.active_guidance.map(x=>`<span class="pill ${x.mode==='hold'?'hold':''}">#${x.id} ${esc(x.scope)} · ${esc(x.instruction.slice(0,90))}<button title="Beëindig" onclick="closeGuidance(${x.id})">×</button></span>`).join(''):'Geen actieve menselijke override; Qwen werkt volledig autonoom.'}async function sendGuidance(mode){const instruction=document.getElementById('instruction').value.trim(),scope=document.getElementById('scope').value,out=document.getElementById('send-status');if(!instruction){out.textContent='Typ eerst een correctie of richtlijn.';return}out.textContent='Opslaan…';try{await api('/api/ai/session/guidance',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({instruction,scope,mode})});document.getElementById('instruction').value='';out.textContent=mode==='hold'?'Domeinhold opgeslagen; monitoring blijft actief.':'Richtlijn opgeslagen; Qwen neemt hem mee in de volgende cyclus.';await poll()}catch(e){out.textContent=String(e)}}async function closeGuidance(id){try{await api('/api/ai/session/guidance/'+id+'/close',{method:'POST'});await loadStatus();await poll()}catch(e){alert(e)}}loadInitial();setInterval(poll,1500);
</script></body></html>"""


@router.get("/ai-session", response_class=HTMLResponse)
def ai_session_page() -> HTMLResponse:
    return HTMLResponse(
        SESSION_HTML,
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-src 'none'; base-uri 'none'",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
        },
    )