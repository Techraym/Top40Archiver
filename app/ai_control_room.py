from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import ai_memory
from .ai_learning import autonomy_report
from .backup_health import backup_health
from .chart_freshness import freshness_status
from .config import DATA_DIR
from .incident_engine import incident_summary, list_incidents
from .operations_center import (
    cover_dashboard,
    database_dashboard,
    download_dashboard,
    health_score,
    service_monitor,
)

router = APIRouter()
CONTROL_ROOM_DIR = DATA_DIR / "ai" / "control-room"
LIVE_HTML = CONTROL_ROOM_DIR / "current.html"
STATE_FILE = CONTROL_ROOM_DIR / "state.json"
CODE_REPAIR_STATE = DATA_DIR / "ai" / "code-repair-state.json"
CODE_IMPROVEMENT_STATE = DATA_DIR / "ai" / "code-improvement-state.json"
RECOVERY_REPORT = DATA_DIR / "ai" / "last-recovery-report.json"
OPERATIONS_REPORT = DATA_DIR / "ai" / "last-operations-worker-report.json"
LOG_READER = os.getenv("TOP40_LOG_READER_URL", "http://127.0.0.1:8042")
VERSION_FILE = Path(__file__).resolve().parents[1] / "VERSION"

REQUIRED_SECTION_IDS = (
    "cr-summary",
    "cr-tasks",
    "cr-actions",
    "cr-services",
    "cr-downloads",
    "cr-covers",
    "cr-database",
    "cr-charts",
    "cr-incidents",
    "cr-code",
    "cr-learning",
    "cr-ui",
    "cr-logs",
    "cr-raw",
)

FORBIDDEN_HTML_MARKERS = (
    "<script",
    "javascript:",
    "onerror=",
    "onclick=",
    "onload=",
    "<iframe",
    "<object",
    "<embed",
    "http://",
    "https://",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _release_version() -> str:
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


def _load_json(path: Path, default: Any = None) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value
    except Exception:
        return {} if default is None else default


def _json_value(value: object) -> Any:
    try:
        return json.loads(str(value or "{}"))
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def validate_control_room_html(html: str) -> dict[str, Any]:
    text = str(html or "")
    lowered = text.casefold()
    missing = [section for section in REQUIRED_SECTION_IDS if f'id="{section}"' not in lowered and f"id='{section}'" not in lowered]
    forbidden = [marker for marker in FORBIDDEN_HTML_MARKERS if marker in lowered]
    score = 100
    score -= len(missing) * 8
    score -= len(forbidden) * 20
    if "<!doctype html" not in lowered:
        score -= 10
    if "viewport" not in lowered:
        score -= 8
    if "@media" not in lowered:
        score -= 5
    if len(text) < 3000:
        score -= 15
    if len(text) > 180_000:
        score -= 15
    return {
        "ok": not missing and not forbidden and "<!doctype html" in lowered and len(text) <= 180_000,
        "missing_sections": missing,
        "forbidden_markers": forbidden,
        "bytes": len(text.encode("utf-8", "ignore")),
        "structural_score": max(0, min(100, score)),
        "sha256": hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest(),
    }


def _fallback_html() -> str:
    sections = [
        ("cr-summary", "Systeemoverzicht"),
        ("cr-tasks", "Actieve taken"),
        ("cr-actions", "Alle AI-acties"),
        ("cr-services", "Services & timers"),
        ("cr-downloads", "Downloads"),
        ("cr-covers", "Covers"),
        ("cr-database", "Database"),
        ("cr-charts", "Top 40 & Tipparade"),
        ("cr-incidents", "Incidenten"),
        ("cr-code", "Codeherstel & verbeteringen"),
        ("cr-learning", "AI-learning"),
        ("cr-ui", "AI-paginaontwikkeling"),
        ("cr-logs", "Recente fouten"),
        ("cr-raw", "Volledige live snapshot"),
    ]
    cards = "".join(f"<section class='panel' id='{sid}'><h2>{title}</h2><p class='muted'>Laden…</p></section>" for sid, title in sections)
    return f"""<!doctype html><html lang='nl'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Top40Archiver AI Control Room</title><style>
:root{{--bg:#071018;--panel:#0d1924;--panel2:#101f2d;--line:#223547;--text:#eef6fb;--muted:#91a7b8;--good:#54d69b;--warn:#ffc866;--bad:#ff7777;--accent:#73b8ff}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 Inter,system-ui,sans-serif}}.shell{{max-width:1680px;margin:auto;padding:22px}}header{{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;margin-bottom:18px}}h1{{font-size:clamp(30px,5vw,58px);margin:.15em 0}}.muted{{color:var(--muted)}}.badge{{border:1px solid var(--line);border-radius:999px;padding:7px 11px;display:inline-block}}.grid{{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:14px}}.panel{{grid-column:span 6;background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:18px;padding:17px;min-width:0;overflow:auto}}#cr-summary,#cr-tasks,#cr-actions,#cr-services,#cr-raw{{grid-column:1/-1}}table{{width:100%;border-collapse:collapse;min-width:700px}}th,td{{padding:8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#050a0f;border:1px solid var(--line);padding:12px;border-radius:12px;max-height:560px;overflow:auto}}details{{border-top:1px solid var(--line);padding:8px 0}}.good{{color:var(--good)}}.warn{{color:var(--warn)}}.bad{{color:var(--bad)}}@media(max-width:900px){{.panel{{grid-column:1/-1}}header{{flex-direction:column}}}}@media(max-width:560px){{.shell{{padding:12px}}table{{min-width:620px}}}}
</style></head><body><main class='shell'><header><div><span class='badge'>Top40Archiver · AI Control Room · :8041</span><h1>Lokale AI cockpit</h1><p class='muted'>Deze veilige fallback blijft beschikbaar totdat Qwen zijn eigen gevalideerde cockpit heeft geschreven.</p></div><div><b id='cr-updated'>Laden…</b><br><span class='muted' id='cr-revision'>fallback</span></div></header><div class='grid'>{cards}</div></main></body></html>"""


def _recent_actions(limit: int = 200) -> list[dict[str, Any]]:
    with ai_memory.connect() as conn:
        rows = conn.execute(
            """
            SELECT id,cycle_id,domain,problem_key,action,subject,reason,status,
                   success,effect_score,operator_needed,reversible,backup_ref,
                   started_at,completed_at,before_json,after_json,result_json
            FROM action_execution ORDER BY id DESC LIMIT ?
            """,
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["before"] = _json_value(item.pop("before_json", "{}"))
        item["after"] = _json_value(item.pop("after_json", "{}"))
        item["result"] = _json_value(item.pop("result_json", "{}"))
        items.append(item)
    return items


def _recent_cycles(limit: int = 40) -> list[dict[str, Any]]:
    with ai_memory.connect() as conn:
        rows = conn.execute(
            """
            SELECT cycle_id,started_at,completed_at,ok,incidents_detected,
                   actions_executed,actions_successful,unresolved_after,
                   operator_needed,report_json
            FROM autonomy_cycle ORDER BY started_at DESC LIMIT ?
            """,
            (max(1, min(int(limit), 100)),),
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["report"] = _json_value(item.pop("report_json", "{}"))
        items.append(item)
    return items


def _ui_telemetry_summary(revision: int | None = None, limit: int = 500) -> dict[str, Any]:
    with ai_memory.connect() as conn:
        if revision is None:
            rows = conn.execute(
                "SELECT * FROM ui_telemetry ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 2000)),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM ui_telemetry WHERE revision=? ORDER BY id DESC LIMIT ?",
                (int(revision), max(1, min(limit, 2000))),
            ).fetchall()
    events = [dict(row) | {"detail": _json_value(row["detail_json"])} for row in rows]
    page_health = [x for x in events if x.get("event_type") == "page_health"]
    errors = [x for x in events if x.get("event_type") in {"js_error", "api_error", "render_error"}]
    durations = [float(x["duration_ms"]) for x in page_health if x.get("duration_ms") is not None]
    overflows = sum(1 for x in page_health if bool((x.get("detail") or {}).get("horizontal_overflow")))
    return {
        "revision": revision,
        "events": len(events),
        "page_health_events": len(page_health),
        "errors": len(errors),
        "error_rate": round(len(errors) / max(1, len(page_health)), 4),
        "horizontal_overflow_events": overflows,
        "average_load_ms": round(sum(durations) / len(durations), 1) if durations else None,
        "latest": events[:25],
    }


def _reader_errors() -> list[dict[str, Any]]:
    try:
        response = requests.get(LOG_READER + "/api/logs/errors", params={"minutes": 120, "lines": 120}, timeout=8)
        response.raise_for_status()
        data = response.json()
        return list(data.get("items") or [])[-120:]
    except Exception as exc:
        return [{"time": _now(), "service": "log-reader", "level": "ERROR", "message": f"Logreader niet beschikbaar: {exc}"}]


def _ollama() -> dict[str, Any]:
    url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
    base = url.rsplit("/api/", 1)[0]
    try:
        response = requests.get(base + "/api/tags", timeout=3)
        response.raise_for_status()
        names = [str(x.get("name") or "") for x in response.json().get("models", [])]
        return {"reachable": True, "model": os.getenv("TOP40_AI_MODEL", "qwen3:4b"), "models": names}
    except Exception as exc:
        return {"reachable": False, "model": os.getenv("TOP40_AI_MODEL", "qwen3:4b"), "error": str(exc)[-500:]}


def _build_tasks(
    services: list[dict[str, Any]],
    downloads: dict[str, Any],
    covers: dict[str, Any],
    charts: dict[str, Any],
    actions: list[dict[str, Any]],
    code_repair: dict[str, Any],
    code_improvement: dict[str, Any],
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for item in services:
        if item.get("health") in {"critical", "attention"}:
            tasks.append({
                "priority": "critical" if item.get("health") == "critical" else "attention",
                "domain": "service",
                "task": f"Herstel/bewaak {item.get('unit')}",
                "status": item.get("status"),
                "detail": item,
            })
    if int(downloads.get("queue") or 0) > 0 or int(downloads.get("retry") or 0) > 0:
        tasks.append({"priority": "active", "domain": "download", "task": "Downloadwachtrij verwerken", "status": f"queue={downloads.get('queue', 0)} retry={downloads.get('retry', 0)}", "detail": downloads})
    if int(covers.get("eligible_queue") or 0) > 0:
        tasks.append({"priority": "active", "domain": "cover", "task": "Ontbrekende covers verwerken", "status": f"{covers.get('eligible_queue', 0)} in wachtrij", "detail": covers})
    current = charts.get("current") or {}
    if current and not current.get("ok"):
        tasks.append({"priority": "critical", "domain": "charts", "task": "Top 40 en Tipparade actualiseren", "status": current.get("expected_edition"), "detail": charts})
    if code_repair.get("active"):
        tasks.append({"priority": "canary", "domain": "code", "task": "Runtime-codepatch canary bewaken", "status": "actief", "detail": code_repair.get("active")})
    if code_improvement.get("active"):
        tasks.append({"priority": "canary", "domain": "code_improvement", "task": "Codeverbetering meten", "status": "actief", "detail": code_improvement.get("active")})
    for item in actions:
        if item.get("status") == "pending":
            tasks.append({"priority": "verification", "domain": item.get("domain"), "task": f"Verifieer AI-actie #{item.get('id')}: {item.get('action')}", "status": "pending", "detail": item})
    return tasks[:250]


def control_room_snapshot(action_limit: int = 200) -> dict[str, Any]:
    services = service_monitor()
    downloads = download_dashboard()
    covers = cover_dashboard()
    database = database_dashboard()
    charts = freshness_status()
    actions = _recent_actions(action_limit)
    code_repair = _load_json(CODE_REPAIR_STATE)
    code_improvement = _load_json(CODE_IMPROVEMENT_STATE)
    ui_state = _load_json(STATE_FILE)
    revision = int(ui_state.get("revision") or 0)
    incidents = list_incidents(150, "open")
    tasks = _build_tasks(services, downloads, covers, charts, actions, code_repair, code_improvement)
    changes = [x for x in actions if x.get("domain") in {"code", "code_improvement", "ui"}][:100]
    return {
        "ok": True,
        "generated_at": _now(),
        "version": _release_version(),
        "health": health_score(),
        "ollama": _ollama(),
        "autonomy": autonomy_report(7),
        "tasks": tasks,
        "actions": actions,
        "cycles": _recent_cycles(),
        "services": services,
        "downloads": downloads,
        "covers": covers,
        "database": database,
        "charts": charts,
        "incidents": {"summary": incident_summary(), "items": incidents},
        "code": {"repair": code_repair, "improvement": code_improvement, "changes": changes},
        "ui": {"state": ui_state, "telemetry": _ui_telemetry_summary(revision if revision else None)},
        "backup": backup_health(),
        "recovery": _load_json(RECOVERY_REPORT),
        "operations_worker": _load_json(OPERATIONS_REPORT),
        "logs": _reader_errors(),
        "policy": {
            "page_html_css_owned_by_local_ai": True,
            "runtime_javascript_owned_by_policy": True,
            "ui_can_execute_system_actions": False,
            "ui_external_network_allowed": False,
            "audio_delete_allowed": False,
            "all_ai_actions_visible": True,
        },
    }


class TelemetryIn(BaseModel):
    event_type: str = Field(min_length=2, max_length=40)
    revision: int = Field(default=0, ge=0, le=1_000_000)
    duration_ms: float | None = Field(default=None, ge=0, le=600_000)
    detail: dict[str, Any] = Field(default_factory=dict)


@router.get("/api/ai/control-room")
def control_room_api(limit: int = Query(200, ge=10, le=500)):
    return control_room_snapshot(limit)


@router.get("/api/ai/control-room/actions")
def control_room_actions(limit: int = Query(250, ge=1, le=500)):
    return {"ok": True, "items": _recent_actions(limit)}


@router.get("/api/ai/control-room/tasks")
def control_room_tasks():
    snapshot = control_room_snapshot(250)
    return {"ok": True, "generated_at": snapshot["generated_at"], "items": snapshot["tasks"]}


@router.get("/api/ai/control-room/changes")
def control_room_changes():
    snapshot = control_room_snapshot(300)
    return {"ok": True, "generated_at": snapshot["generated_at"], "items": snapshot["code"]["changes"], "ui": snapshot["ui"]}


@router.post("/api/ai/control-room/telemetry")
def control_room_telemetry(payload: TelemetryIn):
    detail = dict(payload.detail or {})
    raw = json.dumps(detail, ensure_ascii=False)
    if len(raw) > 20_000:
        detail = {"truncated": True, "summary": raw[:19_000]}
    with ai_memory.connect() as conn:
        conn.execute(
            "INSERT INTO ui_telemetry(revision,event_type,duration_ms,detail_json,created_at) VALUES(?,?,?,?,?)",
            (payload.revision, payload.event_type, payload.duration_ms, json.dumps(detail, ensure_ascii=False), _now()),
        )
    return {"ok": True}


TRUSTED_RUNTIME = r"""
<script>
(()=>{
'use strict';
const ids=['cr-summary','cr-tasks','cr-actions','cr-services','cr-downloads','cr-covers','cr-database','cr-charts','cr-incidents','cr-code','cr-learning','cr-ui','cr-logs','cr-raw'];
const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const cls=v=>v===true||v==='active'||v==='ok'||v==='Gezond'?'good':v===false||v==='failed'||v==='critical'||v==='error'?'bad':'warn';
const pretty=v=>`<pre>${esc(JSON.stringify(v,null,2))}</pre>`;
const table=(heads,rows)=>`<div style="overflow:auto"><table><thead><tr>${heads.map(x=>`<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.join('')||`<tr><td colspan="${heads.length}">Geen gegevens.</td></tr>`}</tbody></table></div>`;
const obj=o=>table(['Eigenschap','Waarde'],Object.entries(o||{}).map(([k,v])=>`<tr><td>${esc(k)}</td><td>${typeof v==='object'?`<details><summary>details</summary>${pretty(v)}</details>`:esc(v)}</td></tr>`));
const revision=()=>Number(document.querySelector('meta[name="ai-ui-revision"]')?.content||0);
async function telemetry(event_type,detail={},duration_ms=null){try{await fetch('/api/ai/control-room/telemetry',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({event_type,revision:revision(),duration_ms,detail}),keepalive:true})}catch(_){}}
function put(id,html){const el=document.getElementById(id);if(el)el.innerHTML=html}
function render(d){
 const a=d.autonomy||{},ax=a.actions||{},h=d.health||{},ui=d.ui||{},uis=ui.state||{},inc=d.incidents||{};
 put('cr-summary',`<h2>Systeemoverzicht</h2><div class="cr-metrics"><div><b>${esc(h.score)}%</b><span>Health</span></div><div><b>${esc(a.readiness_score)}%</b><span>Autonomie</span></div><div><b>${esc(ax.completed||0)}</b><span>AI-acties geleerd</span></div><div><b>${esc(ax.pending||0)}</b><span>Wacht op verificatie</span></div><div><b class="${cls(d.ollama?.reachable)}">${d.ollama?.reachable?'Online':'Offline'}</b><span>${esc(d.ollama?.model||'Ollama')}</span></div></div><p>${esc((h.reasons||[]).join(' · ')||'Geen kritieke afwijkingen.')}</p>`);
 put('cr-tasks',`<h2>Actieve taken</h2>${table(['Prioriteit','Domein','Taak','Status','Details'],(d.tasks||[]).map(x=>`<tr><td class="${x.priority==='critical'?'bad':'warn'}">${esc(x.priority)}</td><td>${esc(x.domain)}</td><td>${esc(x.task)}</td><td>${esc(x.status)}</td><td><details><summary>bekijk</summary>${pretty(x.detail)}</details></td></tr>`))}`);
 put('cr-actions',`<h2>Alle AI-acties</h2><p>${esc((d.actions||[]).length)} meest recente acties; vóór/na/resultaat zijn volledig zichtbaar.</p>${table(['#','Tijd','Domein','Probleem','Actie','Reden','Status','Effect','Bewijs'],(d.actions||[]).map(x=>`<tr><td>${esc(x.id)}</td><td>${esc(x.started_at)}</td><td>${esc(x.domain)}</td><td><code>${esc(x.problem_key)}</code></td><td>${esc(x.action)}</td><td>${esc(x.reason)}</td><td class="${x.status==='pending'?'warn':x.success?'good':'bad'}">${esc(x.status==='pending'?'pending':x.success?'geslaagd':'mislukt')}</td><td>${esc(x.effect_score)}</td><td><details><summary>voor/na/resultaat</summary><h4>Voor</h4>${pretty(x.before)}<h4>Na</h4>${pretty(x.after)}<h4>Resultaat</h4>${pretty(x.result)}${x.backup_ref?`<p>Backup: ${esc(x.backup_ref)}</p>`:''}</details></td></tr>`))}`);
 put('cr-services',`<h2>Services & timers</h2>${table(['Unit','Health','Status','PID','CPU','RAM','Threads','Restarts','Laatste start'],(d.services||[]).map(x=>`<tr><td>${esc(x.unit)}</td><td class="${cls(x.health)}">${esc(x.health)}</td><td>${esc(x.status)}</td><td>${esc(x.pid)}</td><td>${esc(x.cpu_seconds)}</td><td>${esc(x.ram_mb)} MB</td><td>${esc(x.threads)}</td><td>${esc(x.restarts)}</td><td>${esc(x.last_restart)}</td></tr>`))}`);
 put('cr-downloads',`<h2>Downloads</h2>${obj(d.downloads)}`);
 put('cr-covers',`<h2>Covers</h2>${obj(d.covers)}`);
 put('cr-database',`<h2>Database</h2>${obj(d.database)}`);
 put('cr-charts',`<h2>Top 40 & Tipparade</h2>${obj(d.charts)}`);
 put('cr-incidents',`<h2>Incidenten</h2><p>Open: ${esc((inc.items||[]).length)} · circuit breaker: <b class="${cls(!(inc.summary?.circuit_breaker?.active))}">${inc.summary?.circuit_breaker?.active?'ACTIEF':'vrij'}</b></p>${table(['Ernst','Titel','Confidence','Aantal','Laatste','Advies'],(inc.items||[]).map(x=>`<tr><td class="${x.severity==='critical'?'bad':'warn'}">${esc(x.severity)}</td><td>${esc(x.title)}</td><td>${Math.round(Number(x.confidence||0)*100)}%</td><td>${esc(x.occurrences)}</td><td>${esc(x.last_seen)}</td><td>${esc(x.recommendation)}</td></tr>`))}`);
 put('cr-code',`<h2>Codeherstel & verbeteringen</h2><h3>Runtime repair</h3>${pretty(d.code?.repair||{})}<h3>Gemeten verbetering</h3>${pretty(d.code?.improvement||{})}<h3>Laatste code/UI-wijzigingen</h3>${table(['Tijd','Domein','Actie','Probleem','Status'],(d.code?.changes||[]).map(x=>`<tr><td>${esc(x.started_at)}</td><td>${esc(x.domain)}</td><td>${esc(x.action)}</td><td>${esc(x.problem_key)}</td><td class="${x.success?'good':x.status==='pending'?'warn':'bad'}">${esc(x.status)}</td></tr>`))}`);
 put('cr-learning',`<h2>AI-learning</h2><p>Modus: <b>${esc(a.learning_mode)}</b> · readiness ${esc(a.readiness_score)}% · menselijke interactie nodig: ${esc(ax.operator_needed||0)}</p>${table(['Probleem','Actie','Bewijs','Succes','Effect','Confidence'],(a.top_learning||[]).map(x=>`<tr><td><code>${esc(x.problem_key)}</code></td><td>${esc(x.action)}</td><td>${esc(x.evidence_count)}</td><td>${Math.round(Number(x.success_rate||0)*100)}%</td><td>${Number(x.average_effect||0).toFixed(2)}</td><td>${Number(x.confidence||0).toFixed(2)}</td></tr>`))}<h3>Laatste cycli</h3>${table(['Start','OK','Incidenten','Acties','Succes','Onopgelost','Mens nodig'],(d.cycles||[]).map(x=>`<tr><td>${esc(x.started_at)}</td><td class="${cls(Boolean(x.ok))}">${x.ok?'ja':'nee'}</td><td>${esc(x.incidents_detected)}</td><td>${esc(x.actions_executed)}</td><td>${esc(x.actions_successful)}</td><td>${esc(x.unresolved_after)}</td><td>${esc(x.operator_needed)}</td></tr>`))}`);
 put('cr-ui',`<h2>AI-paginaontwikkeling</h2><p>De HTML/CSS van deze pagina wordt lokaal door ${esc(d.ollama?.model||'Qwen')} geschreven en op fouten/overflow/API-latency teruggekoppeld. Runtime-JavaScript blijft vast veiligheidsbeleid.</p>${obj(uis)}<h3>Browsertelemetrie huidige revisie</h3>${obj(ui.telemetry||{})}`);
 put('cr-logs',`<h2>Recente fouten</h2>${table(['Tijd','Service','Level','Melding'],(d.logs||[]).map(x=>`<tr><td>${esc(x.time||x.timestamp)}</td><td>${esc(x.service)}</td><td class="${String(x.level||'').toUpperCase()==='ERROR'?'bad':'warn'}">${esc(x.level)}</td><td>${esc(x.message)}</td></tr>`))}`);
 put('cr-raw',`<h2>Volledige live snapshot</h2><details><summary>Toon alle ruwe AI-data</summary>${pretty(d)}</details>`);
 const u=document.getElementById('cr-updated');if(u)u.textContent=new Date(d.generated_at).toLocaleString();
 const r=document.getElementById('cr-revision');if(r)r.textContent=`AI UI revisie ${esc(uis.revision||0)} · ${esc(uis.status||'fallback')}`;
}
async function load(){const start=performance.now();try{const r=await fetch('/api/ai/control-room?limit=250',{cache:'no-store'});if(!r.ok)throw Error(await r.text());const d=await r.json();render(d);requestAnimationFrame(()=>{const missing=ids.filter(id=>!document.getElementById(id));const overflow=document.documentElement.scrollWidth>window.innerWidth+2;telemetry('page_health',{missing_sections:missing,horizontal_overflow:overflow,viewport:{w:innerWidth,h:innerHeight}},performance.now()-start)})}catch(err){put('cr-summary',`<h2 class="bad">Control Room datafout</h2><pre>${esc(err)}</pre>`);telemetry('api_error',{error:String(err)},performance.now()-start)}}
window.addEventListener('error',e=>telemetry('js_error',{message:e.message,source:e.filename,line:e.lineno,col:e.colno}));
window.addEventListener('unhandledrejection',e=>telemetry('js_error',{message:String(e.reason)}));
load();setInterval(load,5000);
})();
</script>
"""


def control_room_response() -> HTMLResponse:
    html = ""
    if LIVE_HTML.is_file():
        try:
            candidate = LIVE_HTML.read_text(encoding="utf-8")
            if validate_control_room_html(candidate).get("ok"):
                html = candidate
        except OSError:
            html = ""
    if not html:
        html = _fallback_html()
    state = _load_json(STATE_FILE)
    revision = int(state.get("revision") or 0)
    meta = f'<meta name="ai-ui-revision" content="{revision}">'
    if "</head>" in html:
        html = html.replace("</head>", meta + "</head>", 1)
    if "</body>" in html:
        html = html.replace("</body>", TRUSTED_RUNTIME + "</body>", 1)
    else:
        html += TRUSTED_RUNTIME
    headers = {
        "Cache-Control": "no-store, max-age=0",
        "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self' ws: wss:; img-src 'self' data:; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
    }
    return HTMLResponse(html, headers=headers)
