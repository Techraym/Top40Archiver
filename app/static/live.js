document.addEventListener("DOMContentLoaded", () => {
  const ai = document.getElementById("ai-sidecar-link");
  if (ai) ai.href = `${location.protocol}//${location.hostname}:8041/`;
});

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const state = { source: null, fallbackTimer: null };
  const labels = {
    pending: "In wachtrij",
    downloading: "Bezig",
    downloaded: "Gedownload",
    failed: "Mislukt",
    unavailable: "Niet online beschikbaar",
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function setText(id, value) {
    const el = $(id);
    if (!el || el.textContent === String(value)) return;
    el.textContent = String(value);
  }

  function setConnection(mode, text) {
    const pill = $("live-connection");
    if (pill) {
      pill.className = `live-pill ${mode}`;
      pill.innerHTML = '<span class="live-dot"></span>' + escapeHtml(text);
    }
    setText("footer-live-state", text.toLowerCase());
  }

  function interactionInside(el) {
    if (!el) return false;
    const active = document.activeElement;
    if (active && el.contains(active)) return true;
    const selection = window.getSelection?.();
    if (!selection || selection.isCollapsed || !selection.rangeCount) return false;
    const node = selection.getRangeAt(0).commonAncestorContainer;
    return el.contains(node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement);
  }

  function updateHtml(id, signature, html, protect = false) {
    const el = $(id);
    if (!el || el.dataset.signature === signature) return;
    if (protect && interactionInside(el)) return;
    el.innerHTML = html;
    el.dataset.signature = signature;
  }

  function setHistoryBadge(status, label) {
    const el = $("history-status-badge");
    if (!el) return;
    [...el.classList].forEach((name) => {
      if (name.startsWith("history-")) el.classList.remove(name);
    });
    el.classList.add(`history-${status}`);
    el.textContent = label;
  }

  function updateMetrics(data) {
    const counts = data.status_counts || {};
    setText("live-updated-at", data.rendered_at || "—");
    setText("metric-latest-edition", data.latest_top40?.edition_key || "—");
    setText("metric-latest-tipparade", data.latest_tipparade?.edition_key || "—");
    setText("metric-total-tracks", data.total ?? 0);
    setText("metric-downloaded-count", counts.downloaded ?? 0);
    setText("metric-downloaded-percent", `${data.download_chart?.downloaded_percent ?? 0}% geregistreerd`);
    setText("metric-queue-count", (counts.pending ?? 0) + (counts.downloading ?? 0));
    setText("metric-queue-summary", `${counts.pending ?? 0} wachtend · ${counts.downloading ?? 0} bezig`);
    setText("metric-failed-count", counts.failed ?? 0);
    setText("metric-failed-summary", `${counts.unavailable ?? 0} niet online beschikbaar`);
    setText("queue-count", (counts.pending ?? 0) + (counts.downloading ?? 0));
    setText("failed-count", counts.failed ?? 0);
    setText("unavailable-count", counts.unavailable ?? 0);
    setText("success-count", counts.downloaded ?? 0);
  }

  function updateArchive(data) {
    const progress = data.history_progress || {};
    const current = Boolean(progress.is_current);
    const card = $("archive-card");
    if (card) card.classList.toggle("is-current", current);

    setText("archive-title", progress.title || "Historisch archief opbouwen");
    setText("archive-subtitle", progress.subtitle || "");
    setHistoryBadge(progress.status || "idle", progress.status_label || "Onbekend");
    setText("history-percent", `${progress.percent ?? 0}%`);
    setText("history-top40-percent", `${progress.top40?.percent ?? 0}%`);
    setText("history-tipparade-percent", `${progress.tipparade?.percent ?? 0}%`);
    setText("history-next-label", progress.next_label || "—");
    setText("history-next-caption", progress.next_caption || "Volgende edities");

    const bar = $("history-progress-bar");
    if (bar) bar.style.width = `${Math.max(0, Math.min(100, Number(progress.percent || 0)))}%`;

    setText(
      "history-last-edition",
      `Top 40 laatst: ${data.history_last_edition || "—"} · Tipparade laatst: ${data.tip_history_last_edition || "—"}`
    );
    const completedAt = $("history-completed-at");
    if (completedAt) {
      completedAt.hidden = !progress.completed_at;
      completedAt.textContent = progress.completed_at ? `Archief voltooid: ${progress.completed_at}` : "";
    }
    const error = $("history-last-error");
    const errorText = data.history_last_error || data.tip_history_last_error || "";
    if (error) {
      error.hidden = !errorText;
      error.textContent = errorText;
    }
    if ($("history-controls")) $("history-controls").hidden = current;
    if ($("current-controls")) $("current-controls").hidden = !current;
  }

  function updateStorage(data) {
    const storage = data.storage || {};
    const good = Boolean(storage.exists && storage.writable);
    const stateEl = $("storage-state");
    if (stateEl) stateEl.className = `storage-state ${good ? "ok" : "bad"}`;
    setText("storage-icon", good ? "✓" : "!");
    setText("storage-title", good ? "USB-C schrijfbaar" : !storage.exists ? "USB-C niet gevonden" : "USB-C niet schrijfbaar");
    setText("storage-path", storage.path || "—");

    const mp3Count = Number(storage.mp3_count || 0);
    const musicSize = storage.music_size_label || "0 B";
    const percentLabel = storage.used_percent_label ?? storage.used_percent ?? 0;
    setText("storage-free", `${storage.free_gb ?? 0} GB vrij · ${mp3Count} MP3 · ${musicSize}`);
    setText("storage-used", `${percentLabel}% gebruikt`);

    const actualPercent = Math.max(0, Math.min(100, Number(storage.used_percent || 0)));
    const visualPercent = actualPercent > 0 ? Math.max(0.25, actualPercent) : 0;
    const bar = $("storage-progress-bar");
    if (bar) {
      bar.style.width = `${visualPercent}%`;
      bar.title = `${percentLabel}% werkelijk gebruikt`;
    }

    const spotify = $("spotify-state");
    if (spotify) spotify.className = `storage-state ${data.spotify_configured ? "ok" : "bad"}`;
    setText("spotify-icon", data.spotify_configured ? "✓" : "!");
    setText("spotify-title", `Spotify-controle ${data.spotify_configured ? "actief" : "niet ingesteld"}`);
  }

  function chartRows(rows, statusLabels) {
    return rows.length
      ? rows.map((row) => {
          const cover = row.cover_url
            ? `<img class="track-cover" src="${escapeHtml(row.cover_url)}" alt="" loading="lazy" referrerpolicy="no-referrer">`
            : '<span class="cover-placeholder">&#9835;</span>';
          return `
          <tr class="${row.is_new ? "new" : ""}">
            <td><span class="position">${escapeHtml(row.position)}</span></td>
            <td><div class="artist-cell">${cover}<b>${escapeHtml(row.artist)}</b></div></td>
            <td>${escapeHtml(row.title)} ${row.is_new ? '<span class="new-label">NIEUW</span>' : ""}</td>
            <td><span class="status-badge status-${escapeHtml(row.download_status)}">${escapeHtml(statusLabels[row.download_status] || row.download_status)}</span></td>
          </tr>`;
        }).join("")
      : '<tr><td colspan="4" class="empty">Nog geen editie verwerkt.</td></tr>';
  }

  function updateChart(data, type) {
    const isTop = type === "top40";
    const latest = isTop ? data.latest_top40 : data.latest_tipparade;
    const rows = isTop ? (data.top40_entries || []) : (data.tipparade_entries || []);
    const titleId = isTop ? "latest-chart-title" : "tipparade-chart-title";
    const sourceId = isTop ? "latest-source-link" : "tipparade-source-link";
    const bodyId = isTop ? "latest-chart-body" : "tipparade-chart-body";
    const label = isTop ? "Top 40" : "Tipparade";
    setText(titleId, `${label}${latest ? ` — ${latest.edition_key}` : ""}`);
    const source = $(sourceId);
    if (source) {
      source.hidden = !latest;
      source.href = latest?.source_url || "#";
    }
    updateHtml(bodyId, JSON.stringify(rows), chartRows(rows, data.status_labels || labels));
  }

  function compactRows(rows, statusLabels) {
    return rows.length
      ? rows.map((row) => `<article><div><b>${escapeHtml(row.artist)}</b><span>${escapeHtml(row.title)}</span></div><span class="status-badge status-${escapeHtml(row.download_status)}">${escapeHtml(statusLabels[row.download_status] || row.download_status)}</span></article>`).join("")
      : '<p class="empty">Geen gegevens.</p>';
  }

  function updateQueueAndActivity(data) {
    const statusLabels = data.status_labels || labels;
    const queue = data.queue || [];
    const activity = data.activity || [];
    updateHtml("queue-list", JSON.stringify(queue), queue.length ? compactRows(queue, statusLabels) : '<p class="empty">De wachtrij is leeg.</p>');
    updateHtml("activity-list", JSON.stringify(activity), activity.length ? compactRows(activity, statusLabels) : '<p class="empty">Nog geen activiteit.</p>');
  }

  function updateFailed(data) {
    const rows = data.failed || [];
    const html = rows.length
      ? rows.map((row) => {
          const query = row.custom_search_query || `${row.artist} - ${row.title}`;
          return `<article>
            <div class="failed-head"><div><b>${escapeHtml(row.artist)} — ${escapeHtml(row.title)}</b><small>${escapeHtml(row.download_attempts)} poging(en) · Spotify: ${escapeHtml(row.spotify_status || "unchecked")}</small></div><span class="status-badge status-failed">Mislukt</span></div>
            <details><summary>Technische details tonen</summary><pre>${escapeHtml(row.error_message || "Geen foutmelding opgeslagen")}</pre></details>
            <form method="post" action="/track/${encodeURIComponent(row.id)}/query" class="retry-form">
              <input name="custom_search_query" value="${escapeHtml(query)}">
              <button>Opnieuw zoeken</button>
              <button type="submit" class="unavailable" formaction="/track/${encodeURIComponent(row.id)}/unavailable" formnovalidate>Niet online beschikbaar</button>
            </form>
          </article>`;
        }).join("")
      : '<p class="empty success-text">Geen mislukte downloads.</p>';
    updateHtml("failed-list", JSON.stringify(rows), html, true);
  }

  function updateUnavailable(data) {
    const rows = data.unavailable || [];
    const panel = $("unavailable-panel");
    if (panel) panel.hidden = rows.length === 0;
    const html = rows.length
      ? rows.map((row) => `<article>
          <div><b>${escapeHtml(row.artist)}</b><span>${escapeHtml(row.title)}</span></div>
          <form method="post" action="/track/${encodeURIComponent(row.id)}/restore"><button class="secondary">Opnieuw in wachtrij</button></form>
        </article>`).join("")
      : "";
    updateHtml("unavailable-list", JSON.stringify(rows), html, true);
  }

  function updateSuccess(data) {
    const rows = data.success || [];
    const html = rows.length
      ? rows.map((row) => `<article><span>✓</span><div><b>${escapeHtml(row.artist)} — ${escapeHtml(row.title)}</b><small>${escapeHtml(row.mp3_filename || "MP3 opgeslagen")}</small></div></article>`).join("")
      : '<p class="empty">Nog geen downloads.</p>';
    updateHtml("success-list", JSON.stringify(rows), html);
  }

  function render(data) {
    if (!data?.ok) return;
    updateMetrics(data);
    updateArchive(data);
    updateStorage(data);
    updateChart(data, "top40");
    updateChart(data, "tipparade");
    updateQueueAndActivity(data);
    updateFailed(data);
    updateUnavailable(data);
    updateSuccess(data);
  }

  async function pollOnce() {
    try {
      const response = await fetch("/api/live", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      render(await response.json());
      setConnection("online", "Live");
    } catch (_error) {
      setConnection("offline", "Offline");
    }
  }

  function startFallback() {
    if (state.fallbackTimer) return;
    pollOnce();
    state.fallbackTimer = window.setInterval(pollOnce, 3000);
  }

  function stopFallback() {
    if (!state.fallbackTimer) return;
    window.clearInterval(state.fallbackTimer);
    state.fallbackTimer = null;
  }

  function connect() {
    setConnection("connecting", "Verbinden…");
    if (!("EventSource" in window)) {
      startFallback();
      return;
    }
    const source = new EventSource("/events");
    state.source = source;
    source.addEventListener("open", () => {
      stopFallback();
      setConnection("online", "Live");
    });
    source.addEventListener("dashboard", (event) => {
      try {
        render(JSON.parse(event.data));
        setConnection("online", "Live");
      } catch (_error) {
        setConnection("offline", "Datafout");
      }
    });
    source.addEventListener("dashboard-error", () => setConnection("offline", "Serverfout"));
    source.addEventListener("error", () => {
      setConnection("offline", "Herverbinden…");
      startFallback();
    });
  }

  window.addEventListener("beforeunload", () => {
    state.source?.close();
    stopFallback();
  });
  document.addEventListener("DOMContentLoaded", connect);
})();
