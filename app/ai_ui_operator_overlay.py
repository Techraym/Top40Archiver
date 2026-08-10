from __future__ import annotations

from fastapi.responses import HTMLResponse


OVERLAY = r"""
<style id="operator-ui-control-style">
#operator-ui-control{position:fixed;right:14px;bottom:14px;z-index:2147483000;width:min(430px,calc(100vw - 28px));background:#fff;color:#221f1c;border:1px solid #d8d0c8;border-radius:16px;box-shadow:0 18px 50px rgba(0,0,0,.24);font:14px/1.45 system-ui,sans-serif;overflow:hidden}#operator-ui-control summary{cursor:pointer;padding:12px 14px;font-weight:700;background:#f5f1ed}#operator-ui-control .op-body{padding:12px 14px;max-height:70vh;overflow:auto}#operator-ui-control textarea{width:100%;min-height:74px;resize:vertical;padding:9px;border:1px solid #cec6bd;border-radius:9px;font:inherit}#operator-ui-control button{border:0;border-radius:9px;padding:8px 10px;margin:5px 5px 0 0;background:#27231f;color:#fff;cursor:pointer;font:inherit}#operator-ui-control button.warn{background:#8a5910}#operator-ui-control button.bad{background:#9e3029}#operator-ui-control .muted{color:#716a63}#operator-ui-control .guidance{padding:7px 0;border-top:1px solid #e6dfd7}#operator-ui-control code{font-size:12px}#operator-ui-message{white-space:pre-wrap;margin-top:8px}
</style>
<details id="operator-ui-control">
<summary>Menselijke controle over Qwen UI</summary>
<div class="op-body">
<p><b>8040:</b> vast en verboden voor Qwen/Ollama.<br><b>8041/8042:</b> AI-HTML/CSS met canary + rollback.<br><b>Maximum:</b> 3 top-level pagina's.</p>
<label for="operator-ui-guidance"><b>Correctie/richtlijn voor Qwen</b></label>
<textarea id="operator-ui-guidance" placeholder="Bijvoorbeeld: maak foutmeldingen compacter en zet actieve taken bovenaan."></textarea>
<div>
<button id="operator-ui-guide">Correctie opslaan</button>
<button id="operator-ui-hold" class="warn">Nieuwe UI-wijzigingen pauzeren</button>
</div>
<div>
<button id="operator-ui-rollback-8041" class="bad">8041 terugrollen</button>
<button id="operator-ui-rollback-8042" class="bad">8042 terugrollen</button>
</div>
<p class="muted">Een HOLD stopt alleen nieuwe AI-UI-mutaties. Monitoring en rollback blijven werken.</p>
<div id="operator-ui-guidance-list"></div>
<div id="operator-ui-message" class="muted"></div>
</div>
</details>
<script id="operator-ui-control-runtime">
(()=>{
'use strict';
const $=id=>document.getElementById(id);const msg=v=>{$('operator-ui-message').textContent=String(v??'')};
async function api(url,opt){const r=await fetch(url,opt);if(!r.ok)throw Error(await r.text());return r.json()}
async function state(){try{const d=await api('/api/ai/ui-policy');const items=d.active_ui_guidance||[];$('operator-ui-guidance-list').innerHTML=items.length?'<h4>Actieve UI-richtlijnen</h4>'+items.map(x=>`<div class="guidance"><b>#${x.id} ${x.mode==='hold'?'HOLD':'RICHTLIJN'}</b><br>${String(x.instruction??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')}<br><button data-close="${x.id}">Sluiten</button></div>`).join(''):'<p class="muted">Geen actieve UI-richtlijnen.</p>';$('operator-ui-guidance-list').querySelectorAll('[data-close]').forEach(b=>b.onclick=async()=>{try{await api('/api/ai/ui-guidance/'+b.dataset.close+'/close',{method:'POST'});msg('Richtlijn gesloten.');state()}catch(e){msg(e)}})}catch(e){msg(e)}}
async function guidance(hold){const instruction=$('operator-ui-guidance').value.trim()||(hold?'Pauzeer nieuwe Qwen UI-wijzigingen totdat ik deze HOLD sluit.':'');if(!instruction){msg('Vul eerst een correctie in.');return}try{const d=await api('/api/ai/ui-guidance',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({instruction,hold})});msg(d.qwen_acknowledgement||d.effect||'Opgeslagen.');$('operator-ui-guidance').value='';state()}catch(e){msg(e)}}
async function rollback(port){if(!confirm(`AI-pagina ${port} terugrollen naar de vorige backup?`))return;try{const d=await api('/api/ai/ui-rollback/'+port,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason:'menselijke operator rollback via 8041'})});msg(JSON.stringify(d,null,2));setTimeout(()=>location.reload(),1200)}catch(e){msg(e)}}
$('operator-ui-guide').onclick=()=>guidance(false);$('operator-ui-hold').onclick=()=>guidance(true);$('operator-ui-rollback-8041').onclick=()=>rollback(8041);$('operator-ui-rollback-8042').onclick=()=>rollback(8042);state();
})();
</script>
"""


def inject_operator_overlay(response: HTMLResponse) -> HTMLResponse:
    """Inject non-AI operator controls after the Qwen-owned page HTML is rendered."""
    try:
        html = response.body.decode("utf-8")
    except Exception:
        return response
    if "operator-ui-control-runtime" not in html:
        if "</body>" in html:
            html = html.replace("</body>", OVERLAY + "</body>", 1)
        else:
            html += OVERLAY
    headers = dict(response.headers)
    headers.pop("content-length", None)
    return HTMLResponse(html, status_code=response.status_code, headers=headers)
