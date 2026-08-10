from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi.responses import HTMLResponse

from .config import DATA_DIR

LOG_CONTROL_DIR = DATA_DIR / "ai" / "log-control"
LIVE_HTML = LOG_CONTROL_DIR / "current.html"
STATE_FILE = LOG_CONTROL_DIR / "state.json"
BACKUP_DIR = LOG_CONTROL_DIR / "backups"

REQUIRED_SECTION_IDS = (
    "lc-status",
    "lc-errors",
    "lc-live",
    "lc-policy",
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


def _load_state() -> dict[str, Any]:
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def validate_log_control_html(html: str) -> dict[str, Any]:
    text = str(html or "")
    lowered = text.casefold()
    missing = [
        section
        for section in REQUIRED_SECTION_IDS
        if f'id="{section}"' not in lowered and f"id='{section}'" not in lowered
    ]
    forbidden = [marker for marker in FORBIDDEN_HTML_MARKERS if marker in lowered]
    return {
        "ok": bool(
            "<!doctype html" in lowered
            and not missing
            and not forbidden
            and len(text) <= 120_000
        ),
        "missing_sections": missing,
        "forbidden_markers": forbidden,
        "bytes": len(text.encode("utf-8", "ignore")),
        "sha256": hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest(),
    }


def _fallback_html() -> str:
    return """<!doctype html><html lang='nl'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Top40Archiver Log Control</title><style>
:root{--bg:#081018;--panel:#101c27;--line:#263949;--text:#edf5fa;--muted:#9db0bd;--bad:#ff7a7a;--warn:#ffd178;--good:#5cdda3}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 system-ui,sans-serif}.shell{max-width:1500px;margin:auto;padding:22px}header{margin-bottom:18px}h1{font-size:clamp(28px,5vw,50px);margin:.2em 0}.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:14px}.panel{grid-column:span 6;background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:16px;overflow:auto}.wide{grid-column:1/-1}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#05090d;padding:12px;border-radius:12px;max-height:550px;overflow:auto}.bad{color:var(--bad)}.warn{color:var(--warn)}.good{color:var(--good)}@media(max-width:850px){.panel{grid-column:1/-1}}
</style></head><body><main class='shell'><header><p class='muted'>Top40Archiver · veilige lokale logreader · :8042</p><h1>Log & AI controle</h1><p class='muted'>Qwen mag alleen de HTML/CSS van deze beheerpagina verbeteren. De vaste runtime en log-API blijven policy-code.</p></header><div class='grid'><section class='panel' id='lc-status'><h2>Status</h2><p>Laden…</p></section><section class='panel' id='lc-policy'><h2>UI-policy</h2><p>Laden…</p></section><section class='panel wide' id='lc-errors'><h2>Recente fouten</h2><p>Laden…</p></section><section class='panel wide' id='lc-live'><h2>Live logs</h2><p>Laden…</p></section></div></main></body></html>"""


TRUSTED_RUNTIME = r"""
<script>
(()=>{
'use strict';
const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const put=(id,html)=>{const el=document.getElementById(id);if(el)el.innerHTML=html};
const lines=items=>`<pre>${(items||[]).map(x=>esc(`${x.time||''} ${x.service||''} [${x.level||''}] ${x.message||''}`)).join('\n')||'Geen regels.'}</pre>`;
async function load(){
 try{
  const [health,errors,live]=await Promise.all([
   fetch('/healthz',{cache:'no-store'}).then(r=>r.json()),
   fetch('/api/logs/errors?minutes=120&lines=160',{cache:'no-store'}).then(r=>r.json()),
   fetch('/api/logs/live?service=all&minutes=2&lines=180',{cache:'no-store'}).then(r=>r.json())
  ]);
  put('lc-status',`<h2>Status</h2><p class='good'><b>Logreader actief</b></p><pre>${esc(JSON.stringify(health,null,2))}</pre>`);
  put('lc-policy',`<h2>UI-policy</h2><p><b>:8040</b> is menselijk en immutable voor Qwen/Ollama.</p><p><b>:8041 en :8042</b> mogen alleen binnen canary/rollback-policy visueel evolueren.</p><p>Maximaal 3 top-level pagina's: 8040, 8041, 8042.</p>`);
  put('lc-errors',`<h2>Recente fouten</h2>${lines(errors.items)}`);
  put('lc-live',`<h2>Live logs</h2>${lines(live.items)}`);
 }catch(e){put('lc-status',`<h2>Status</h2><p class='bad'>${esc(e)}</p>`)}
}
load();setInterval(load,5000);
})();
</script>
"""


def log_control_response() -> HTMLResponse:
    html = ""
    if LIVE_HTML.is_file():
        try:
            candidate = LIVE_HTML.read_text(encoding="utf-8")
            if validate_log_control_html(candidate).get("ok"):
                html = candidate
        except OSError:
            pass
    if not html:
        html = _fallback_html()
    state = _load_state()
    revision = int(state.get("revision") or 0)
    meta = f'<meta name="ai-ui-port" content="8042"><meta name="ai-ui-revision" content="{revision}">'
    if "</head>" in html:
        html = html.replace("</head>", meta + "</head>", 1)
    if "</body>" in html:
        html = html.replace("</body>", TRUSTED_RUNTIME + "</body>", 1)
    else:
        html += TRUSTED_RUNTIME
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
        },
    )
