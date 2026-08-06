(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  let activeRange = "24h";

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

  function chartSvg(rows, series, options = {}) {
    if (!rows.length) return '<div class="chart-empty">Nog onvoldoende meetpunten.</div>';
    const width = 640;
    const height = 220;
    const pad = 18;
    const min = Number(options.min ?? 0);
    const values = rows.flatMap((row) => series.map((item) => Number(row[item.key] || 0)));
    const maximum = Math.max(Number(options.max ?? 0), ...values, 1);
    const x = (index) => pad + (rows.length === 1 ? 0 : index * (width - pad * 2) / (rows.length - 1));
    const y = (value) => height - pad - ((Number(value) - min) / Math.max(1, maximum - min)) * (height - pad * 2);
    const grid = [0.25, 0.5, 0.75].map((part) => `<line class="chart-grid-line" x1="${pad}" y1="${height * part}" x2="${width - pad}" y2="${height * part}"></line>`).join("");
    const paths = series.map((item, seriesIndex) => {
      const points = rows.map((row, index) => `${x(index).toFixed(1)},${y(row[item.key]).toFixed(1)}`).join(" ");
      const dash = seriesIndex ? ' stroke-dasharray="7 5"' : "";
      return `<polyline class="chart-line"${dash} points="${points}"><title>${esc(item.label)}</title></polyline>`;
    }).join("");
    const labels = series.map((item, index) => `<span>${index ? "┄" : "━"} ${esc(item.label)}</span>`).join(" · ");
    return `<svg class="trend-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(options.label || "Trendgrafiek")}">${grid}${paths}</svg><small>${labels}</small>`;
  }

  function renderTrends(data) {
    const summary = data.summary || {};
    const rows = data.rows || [];
    $("trend-score-average").textContent = `${summary.score_average ?? 0}%`;
    $("trend-score-minimum").textContent = `${summary.score_minimum ?? 0}%`;
    $("trend-availability").textContent = `${summary.availability_percent ?? 0}%`;
    $("trend-cpu-average").textContent = `${summary.cpu_average ?? 0}%`;
    $("trend-samples").textContent = summary.sample_count ?? 0;
    $("trend-diagnosis").textContent = summary.diagnosis || "Geen trenddiagnose beschikbaar.";

    $("score-chart").innerHTML = chartSvg(rows, [{key: "score", label: "Health"}], {max: 100, label: "Gezondheidsscore"});
    $("load-chart").innerHTML = chartSvg(rows, [{key: "cpu_percent", label: "CPU"}, {key: "memory_percent", label: "Geheugen"}], {max: 100, label: "CPU en geheugen"});
    $("disk-chart").innerHTML = chartSvg(rows, [{key: "disk_percent", label: "Opslag"}], {max: 100, label: "Opslaggebruik"});
    $("queue-chart").innerHTML = chartSvg(rows, [{key: "queue_pending", label: "Wachtend"}, {key: "queue_failed", label: "Mislukt"}], {label: "Downloadwachtrij"});
  }

  async function load(refresh = false) {
    const healthUrl = refresh ? "/api/health?refresh=true" : "/api/health";
    try {
      const [healthResponse, eventsResponse, trendsResponse] = await Promise.all([
        fetch(healthUrl, {cache: "no-store"}),
        fetch("/api/health/events?limit=20", {cache: "no-store"}),
        fetch(`/api/health/trends?range=${encodeURIComponent(activeRange)}`, {cache: "no-store"}),
      ]);
      if (!healthResponse.ok || !eventsResponse.ok || !trendsResponse.ok) throw new Error("Health API gaf geen geldig antwoord");
      const health = await healthResponse.json();
      const events = await eventsResponse.json();
      const trends = await trendsResponse.json();
      renderHealth(health.health || {});
      renderEvents(events.events || []);
      renderTrends(trends);
    } catch (error) {
      $("health-diagnosis").textContent = `AI Health kon niet worden geladen: ${error.message}`;
      $("score-card").className = "health-card health-score score-critical";
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("refresh-health")?.addEventListener("click", () => load(true));
    document.querySelectorAll("[data-range]").forEach((button) => {
      button.addEventListener("click", () => {
        activeRange = button.dataset.range || "24h";
        document.querySelectorAll("[data-range]").forEach((item) => item.classList.toggle("active", item === button));
        load(false);
      });
    });
    load(false);
    window.setInterval(() => load(false), 15000);
  });
})();