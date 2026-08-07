from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .download_db import (
    cancel_job,
    jobs,
    retry_job,
    update_provider_config,
)
from .download_metrics import provider_dashboard

router = APIRouter()


def _provider_overview() -> dict[str, Any]:
    return provider_dashboard()


class ProviderConfigIn(BaseModel):
    priority: int | None = Field(default=None, ge=1, le=500)
    max_concurrent: int | None = Field(default=None, ge=1, le=4)
    requests_per_minute: int | None = Field(default=None, ge=1, le=600)
    min_delay_seconds: float | None = Field(default=None, ge=0, le=600)
    error_backoff_seconds: int | None = Field(default=None, ge=10, le=7200)

    def values(self) -> dict[str, Any]:
        return {key: value for key, value in self.model_dump().items() if value is not None}


@router.get("/api/download/status")
def download_status():
    return _provider_overview()


@router.get("/api/download/jobs")
def download_jobs(limit: int = Query(default=100, ge=1, le=500)):
    return {"ok": True, "items": jobs(limit)}


@router.get("/api/download/providers")
def download_providers():
    return _provider_overview()


@router.get("/download-providers", response_class=HTMLResponse)
def download_providers_page() -> HTMLResponse:
    return HTMLResponse(
        """<!doctype html><html lang='nl'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Top40 Download Providers</title><style>
:root{--bg:#f4f5f7;--card:#fff;--ink:#1f2933;--muted:#67727e;--line:#dfe3e8;--good:#147a48;--warn:#a26700;--bad:#b42318}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,sans-serif}.shell{max-width:1500px;margin:auto;padding:24px}header{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:18px}.nav{display:flex;gap:8px;flex-wrap:wrap}.nav a{color:var(--ink);text-decoration:none;background:#fff;border:1px solid var(--line);padding:8px 11px;border-radius:999px}.metrics,.providers{display:grid;gap:12px}.metrics{grid-template-columns:repeat(5,minmax(0,1fr));margin-bottom:16px}.metric,.provider,.jobs{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px}.metric b{font-size:28px;display:block}.metric span{color:var(--muted)}.providers{grid-template-columns:repeat(3,minmax(0,1fr))}.provider h2{margin:0 0 5px}.muted{color:var(--muted)}.good{color:var(--good)}.warn{color:var(--warn)}.bad{color:var(--bad)}button{font:inherit;border:1px solid var(--line);background:#fff;border-radius:10px;padding:7px 10px;cursor:pointer}.row{display:flex;justify-content:space-between;gap:10px;border-top:1px solid var(--line);padding:8px 0}.jobs{margin-top:16px;overflow:auto}table{width:100%;border-collapse:collapse;min-width:800px}th,td{text-align:left;padding:8px;border-bottom:1px solid var(--line);vertical-align:top}@media(max-width:1100px){.metrics{grid-template-columns:repeat(3,1fr)}}@media(max-width:900px){.metrics{grid-template-columns:repeat(2,1fr)}.providers{grid-template-columns:1fr}}@media(max-width:520px){.metrics{grid-template-columns:1fr}.shell{padding:12px}header{flex-direction:column}}</style></head><body><main class='shell'><header><div><h1>Download Providers</h1><p class='muted'>Multi Source Download Engine · YouTube Music en YouTube zijn fallbackproviders.</p></div><div class='nav'><a href='/'>AI Control Room</a><a href='/ai-session'>Qwen AI Session</a></div></header><section class='metrics' id='metrics'></section><section class='providers' id='providers'></section><section class='jobs'><h2>Recente jobs</h2><div id='jobs'>Laden…</div></section></main><script>
const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const cls=s=>s==='healthy'?'good':s==='offline'?'bad':'warn';
async function api(url,opt){const r=await fetch(url,opt);if(!r.ok)throw Error(await r.text());return r.json()}
async function toggle(name,enabled){await api('/api/download/provider/'+encodeURIComponent(name)+'/'+(enabled?'enable':'disable'),{method:'POST'});await load()}
function providerCard(p){const success=p.success_rate_24h==null?'—':p.success_rate_24h+'%';const cooldown=p.cooldown_until?new Date(p.cooldown_until).toLocaleString():'—';return `<article class='provider'><h2>${esc(p.provider)}</h2><p class='${cls(p.status)}'><b>${esc(p.status)}</b> · health ${esc(p.calculated_health_score)}/100</p><div class='row'><span>Succes 24u</span><b>${esc(success)}</b></div><div class='row'><span>Workers</span><b>${esc(p.active_workers)} / ${esc(p.max_concurrent)}</b></div><div class='row'><span>Prioriteit</span><b>${esc(p.effective_priority)}</b></div><div class='row'><span>Cooldown</span><b>${esc(cooldown)}</b></div><div class='row'><span>Laatste fout</span><span>${esc(p.last_error_category||'—')}</span></div><button onclick="toggle('${esc(p.provider)}',${p.enabled?false:true})">${p.enabled?'Uitschakelen':'Inschakelen'}</button></article>`}
async function load(){try{const d=await api('/api/download/providers');document.getElementById('metrics').innerHTML=`<div class='metric'><b>${esc(d.downloads_24h)}</b><span>Downloads 24u</span></div><div class='metric'><b>${esc(d.without_youtube_24h)}</b><span>Zonder YouTube/YouTube Music</span></div><div class='metric'><b>${esc(d.youtube_music_24h)}</b><span>Via YouTube Music</span></div><div class='metric'><b>${esc(d.youtube_24h)}</b><span>Via YouTube</span></div><div class='metric'><b class='${Number(d.youtube_dependency_percent)<10?'good':'warn'}'>${esc(d.youtube_dependency_percent)}%</b><span>YouTube dependency · doel &lt; 10%</span><small class='muted'>Family: ${esc(d.youtube_family_dependency_percent)}%</small></div>`;document.getElementById('providers').innerHTML=(d.providers||[]).map(providerCard).join('');const j=await api('/api/download/jobs?limit=40');document.getElementById('jobs').innerHTML=`<table><thead><tr><th>Track</th><th>Status</th><th>Provider</th><th>Pogingen</th><th>Volgende poging</th><th>Fout</th></tr></thead><tbody>${(j.items||[]).map(x=>`<tr><td>${esc(x.artist)} – ${esc(x.title)}</td><td>${esc(x.status)}</td><td>${esc(x.preferred_provider||'—')}</td><td>${esc(x.attempts)}</td><td>${esc(x.next_attempt_at||'—')}</td><td>${esc(x.error||'')}</td></tr>`).join('')}</tbody></table>`}catch(e){document.getElementById('providers').innerHTML='<article class="provider bad">'+esc(e)+'</article>'}}
load();setInterval(load,3000);
</script></body></html>""",
        headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/api/download/retry/{track_id}")
def retry_download(track_id: int):
    if not retry_job(track_id):
        raise HTTPException(status_code=404, detail="track niet gevonden of al gedownload")
    return {"ok": True, "track_id": track_id, "status": "queued"}


@router.post("/api/download/cancel/{track_id}")
def cancel_download(track_id: int):
    if not cancel_job(track_id):
        raise HTTPException(status_code=404, detail="actieve downloadjob niet gevonden")
    return {"ok": True, "track_id": track_id, "status": "cancelled"}


@router.post("/api/download/provider/{provider}/enable")
def enable_provider(provider: str):
    try:
        item = update_provider_config(provider, {"enabled": True})
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="onbekende provider") from exc
    return {"ok": True, "provider": item}


@router.post("/api/download/provider/{provider}/disable")
def disable_provider(provider: str):
    try:
        item = update_provider_config(provider, {"enabled": False})
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="onbekende provider") from exc
    return {"ok": True, "provider": item}


@router.post("/api/download/provider/{provider}/config")
def configure_provider(provider: str, payload: ProviderConfigIn):
    values = payload.values()
    if not values:
        raise HTTPException(status_code=400, detail="geen providerinstellingen opgegeven")
    try:
        item = update_provider_config(provider, values)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="onbekende provider") from exc
    return {"ok": True, "provider": item}
