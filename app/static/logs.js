(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const state = { paused: false, timer: null, signature: "" };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function render(data) {
    const rows = data.rows || [];
    const signature = JSON.stringify(rows.map((row) => row.id));
    if (signature !== state.signature) {
      $("log-list").innerHTML = rows.length
        ? rows.map((row) => `<div class="log-row ${escapeHtml(row.level)}"><span class="source">${escapeHtml(row.source)}</span><span>${escapeHtml(row.message)}</span></div>`).join("")
        : '<div class="empty">Geen logregels gevonden met deze filters.</div>';
      state.signature = signature;
      if ($("auto-scroll").checked) $("log-list").scrollTop = $("log-list").scrollHeight;
    }

    const counts = data.counts || {};
    $("count-total").textContent = rows.length;
    $("count-error").textContent = counts.error || 0;
    $("count-warning").textContent = counts.warning || 0;
    $("count-info").textContent = counts.info || 0;
    $("updated-at").textContent = data.generated_at || "—";
    $("live-state").textContent = state.paused ? "Liveweergave gepauzeerd" : "Live · elke 2 seconden";

    const notice = $("journal-notice");
    notice.hidden = !data.journal_error;
    notice.textContent = data.journal_error || "";
  }

  async function refresh() {
    if (state.paused) return;
    const params = new URLSearchParams({
      limit: $("log-limit").value,
      level: $("log-level").value,
      q: $("log-search").value.trim(),
    });
    try {
      const response = await fetch(`/api/logs?${params}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      render(await response.json());
    } catch (error) {
      $("live-state").textContent = `Verbinding mislukt: ${error.message}`;
    }
  }

  function schedule() {
    window.clearInterval(state.timer);
    state.timer = window.setInterval(refresh, 2000);
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("refresh-now").addEventListener("click", () => {
      state.paused = false;
      $("pause-live").textContent = "Live pauzeren";
      $("pause-live").classList.remove("active");
      refresh();
    });
    $("pause-live").addEventListener("click", () => {
      state.paused = !state.paused;
      $("pause-live").textContent = state.paused ? "Live hervatten" : "Live pauzeren";
      $("pause-live").classList.toggle("active", state.paused);
      $("live-state").textContent = state.paused ? "Liveweergave gepauzeerd" : "Live · elke 2 seconden";
      if (!state.paused) refresh();
    });
    ["log-level", "log-limit"].forEach((id) => $(id).addEventListener("change", refresh));
    let debounce;
    $("log-search").addEventListener("input", () => {
      window.clearTimeout(debounce);
      debounce = window.setTimeout(refresh, 300);
    });
    refresh();
    schedule();
  });

  window.addEventListener("beforeunload", () => window.clearInterval(state.timer));
})();
