(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  function percent(value) {
    return `${Number(value || 0).toFixed(1)}%`;
  }

  function setBar(id, value) {
    const el = $(id);
    if (el) el.style.width = `${Math.max(0, Math.min(100, Number(value || 0)))}%`;
  }

  function renderHealth(row) {
    const scoreCard = $("score-card");
    scoreCard.className = `health-card health-score score-${row.status || "attention"}`;
    $("health-score").textContent = `${row.score ?? 0}%`;
    $("health-diagnosis").textContent = row.diagnosis || "Geen diagnose beschikbaar.";
    $("health-time").textContent = `Gemeten ${row.captured_at || "—"} · ${row.worker_count || 1} worker(s)`;
    $("cpu-value").textContent = percent(row.cpu_percent);
    $("memory-value").textContent = percent(row.memory_percent);
    $("disk-value").textContent = percent(row.disk_percent);
    $("disk-free").textContent = `${row.disk_free_gb ?? 0} GB vrij`;
    $("database-value").textContent = row.database_ok ? "Gezond" : "Fout";
    $("database-value").className = row.database_ok ? "status-good" : "status-critical";
    $("database-latency").textContent = `${row.database_latency_ms ?? 0} ms reactietijd`;
    $("internet-value").textContent = row.internet_ok ? "Bereikbaar" : "Offline";
    $("internet-value").className = row.internet_ok ? "status-good" : "status-critical";
    $("queue-value").textContent = row.queue_pending ?? 0;
    $("queue-detail").textContent = `${row.queue_downloading ?? 0} bezig · ${row.queue_failed ?? 0} mislukt${row.downloads_paused ? " · gepauzeerd" : ""}`;

    [["cpu", row.cpu_percent], ["memory", row.memory_percent], ["disk", row.disk_percent]].forEach(([name, value]) => {
      setBar(`${name}-bar`, value);
      $(`${name}-label`).textContent = percent(value);
    });
  }

  function renderEvents(events) {
    $("health-events").innerHTML = events.length
      ? events.map((event) => `<article class="event event-${esc(event.severity)}"><b>${esc(event.message)}</b><small>${esc(event.component)} · ${esc(event.created_at)}</small></article>`).join("")
      : '<p class="empty success-text">Geen actieve health-waarschuwingen.</p>';
  }

  async function load(refresh = false) {
    const healthUrl = refresh ? "/api/health?refresh=true" : "/api/health";
    try {
      const [healthResponse, eventsResponse] = await Promise.all([
        fetch(healthUrl, {cache: "no-store"}),
        fetch("/api/health/events?limit=20", {cache: "no-store"}),
      ]);
      if (!healthResponse.ok || !eventsResponse.ok) throw new Error("Health API gaf geen geldig antwoord");
      const health = await healthResponse.json();
      const events = await eventsResponse.json();
      renderHealth(health.health || {});
      renderEvents(events.events || []);
    } catch (error) {
      $("health-diagnosis").textContent = `AI Health kon niet worden geladen: ${error.message}`;
      $("score-card").className = "health-card health-score score-critical";
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("refresh-health")?.addEventListener("click", () => load(true));
    load(false);
    window.setInterval(() => load(false), 15000);
  });
})();