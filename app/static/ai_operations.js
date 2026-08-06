(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  const actionLabels = {
    pause_downloads: "Downloads veilig pauzeren",
    clear_source_and_retry: "Bron wissen en opnieuw zoeken",
    retry_track: "Gecontroleerd opnieuw proberen",
    retry_later: "Retry voorbereiden",
    manual_update_required: "Handmatig controleren",
    manual_review: "Handmatig beoordelen",
  };
  function render(data) {
    $("open-count").textContent = data.open_count ?? 0;
    $("pause-state").textContent = data.paused ? "Gepauzeerd" : "Actief";
    $("scan-state").textContent = `${data.scan?.scanned ?? 0} fouten`;
    $("paused-banner").hidden = !data.paused;
    const rows = data.incidents || [];
    $("incident-list").innerHTML = rows.length ? rows.map((item) => {
      const evidence = (item.evidence || []).map((entry) => `${entry.seen_at || ""} · ${entry.artist || ""} — ${entry.title || ""}\n${entry.message || ""}`).join("\n\n");
      const resolved = item.status === "resolved";
      return `<article class="incident severity-${esc(item.severity)} ${resolved ? "resolved" : ""}">
        <div class="incident-head"><div><span class="eyebrow">${esc(item.category)}</span><h2>${esc(item.title)}</h2></div><span class="status-badge">${resolved ? "Opgelost" : esc(item.severity)}</span></div>
        <p>${esc(item.diagnosis)}</p>
        <p class="confidence">Betrouwbaarheid diagnose: ${Math.round(Number(item.confidence || 0) * 100)}% · ${esc(item.occurrences)} waarneming(en)</p>
        <details><summary>Technisch bewijs tonen</summary><pre class="evidence">${esc(evidence || "Geen bewijsregels beschikbaar")}</pre></details>
        ${resolved ? "" : `<div class="ops-actions"><form method="post" action="/ai-operations/incident/${encodeURIComponent(item.id)}/repair"><input type="hidden" name="action_name" value="${esc(item.recommended_action || "")}"><button>${esc(actionLabels[item.recommended_action] || "Voorgestelde oplossing uitvoeren")}</button></form></div>`}
      </article>`;
    }).join("") : '<p class="empty success-text">Geen incidenten gevonden.</p>';
  }
  async function load() {
    try {
      const response = await fetch("/api/ai-operations", {cache: "no-store"});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      render(await response.json());
    } catch (error) {
      $("incident-list").innerHTML = `<div class="error-box">AI Operations kon niet worden geladen: ${esc(error.message)}</div>`;
    }
  }
  document.addEventListener("DOMContentLoaded", () => { load(); window.setInterval(load, 5000); });
})();