document.addEventListener("DOMContentLoaded", () => {
  const ai = document.getElementById("ai-sidecar-link");
  if (ai) ai.href = `${location.protocol}//${location.hostname}:8041/`;

  // Safari/iOS kan de oude donkere, specifiekere .retry-form-regel behouden.
  // Deze runtime-correctie staat bewust als laatste in de cascade en dwingt alle
  // tekstinvoer in de lichte interface ook werkelijk licht te renderen.
  const style = document.createElement("style");
  style.id = "top40-light-input-hotfix";
  style.textContent = `
    .retry-form input,
    .search-form input,
    .settings-grid input,
    .settings-grid select,
    input[type="text"],
    input[type="search"],
    input:not([type]),
    textarea,
    select {
      background: #ffffff !important;
      color: #181817 !important;
      -webkit-text-fill-color: #181817 !important;
      caret-color: #181817 !important;
      color-scheme: light !important;
      border-color: #d8d4cc !important;
      box-shadow: inset 0 1px 1px rgba(20,20,18,.02) !important;
    }
    .retry-form input:-webkit-autofill,
    .search-form input:-webkit-autofill,
    .settings-grid input:-webkit-autofill {
      -webkit-text-fill-color: #181817 !important;
      -webkit-box-shadow: 0 0 0 1000px #ffffff inset !important;
      box-shadow: 0 0 0 1000px #ffffff inset !important;
    }
    .retry-form input::placeholder,
    .search-form input::placeholder,
    textarea::placeholder {
      color: #96928a !important;
      opacity: 1 !important;
    }
    .ai-recovery-shortcut {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 40px;
      padding: 8px 13px;
      border: 1px solid #d8d4cc;
      border-radius: 10px;
      background: #ffffff;
      color: #181817;
      font-weight: 700;
      text-decoration: none;
      white-space: nowrap;
    }
    .ai-recovery-note {
      display: flex;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
      margin: 0 0 14px;
      padding: 11px 13px;
      border: 1px solid #e6e3dd;
      border-radius: 12px;
      background: #faf9f6;
      color: #5f5c56;
      font-size: 13px;
    }
    .cover-progress-panel[hidden] { display: none !important; }
    .cover-progress-stats {
      display: grid;
      grid-template-columns: repeat(4, minmax(0,1fr));
      gap: 12px;
      margin: 16px 0 8px;
    }
    .cover-progress-stat {
      border: 1px solid #e6e3dd;
      border-radius: 12px;
      background: #faf9f6;
      padding: 12px 14px;
    }
    .cover-progress-stat b { display:block; font-size: 20px; }
    .cover-progress-stat span { color:#77736c; font-size:12px; }
    .cover-progress-current { margin:10px 0 0; color:#69655f; }
    @media (max-width: 760px) {
      .cover-progress-stats { grid-template-columns: repeat(2,minmax(0,1fr)); }
    }
    @media (max-width: 560px) {
      .ai-recovery-note { align-items: stretch; flex-direction: column; }
      .ai-recovery-shortcut { width: 100%; }
      .cover-progress-stats { grid-template-columns: 1fr 1fr; }
    }
  `;
  document.head.appendChild(style);

  const failedList = document.getElementById("failed-list");
  const failedPanel = failedList?.closest(".panel");
  if (failedPanel && !failedPanel.querySelector(".ai-recovery-note")) {
    const note = document.createElement("div");
    note.className = "ai-recovery-note";
    note.innerHTML = `<span><b>AI-herstel actief</b> · analyseert fouten iedere 5 minuten en wisselt automatisch van herstelstrategie.</span><a class="ai-recovery-shortcut" href="${location.protocol}//${location.hostname}:8041/ai-actions" target="_blank" rel="noopener">AI-herstel bekijken</a>`;
    failedList.before(note);
  }
});

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const state = {
    source: null,
    fallbackTimer: null,
    watchdogTimer: null,
    lastDataAt: 0,
    pollBusy: false,
  };
  const labels = {
    pending: "In wachtrij",
    queued: "In wachtrij",
    waiting_retry: "Wacht op retry",
    searching: "Zoeken",
    downloading: "Downloaden",
    validating: "Valideren",
    processing: "Verwerken",
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

  function ensureCoverPanel() {
    let panel = $("cover-progress-panel");
    if (panel) return panel;
    const metrics = document.querySelector(".metric-grid");
    if (!metrics) return null;
    panel = document.createElement("section");
    panel.id = "cover-progress-panel";
    panel.className = "panel cover-progress-panel";
    panel.hidden = true;
    panel.innerHTML = `
      <div class="section-heading compact">
        <div><span class="eyebrow">Albumhoezen</span><h2>Coverarchief aanvullen</h2><p id="cover-progress-subtitle">De bestaande muziekdatabase wordt op de achtergrond aangevuld.</p></div>
        <span class="status-badge status-downloading">Actief</span>
      </div>
      <div class="progress"><span id="cover-progress-bar" style="width:0%"></span></div>
      <div class="cover-progress-stats">
        <div class="cover-progress-stat"><b id="cover-found">0</b><span>Hoezen gevonden</span></div>
        <div class="cover-progress-stat"><b id="cover-checked">0</b><span>Nummers gecontroleerd</span></div>
        <div class="cover-progress-stat"><b id="cover-remaining">0</b><span>Nog te controleren</span></div>
        <div class="cover-progress-stat"><b id="cover-percent">0%</b><span>Controle voltooid</span></div>
      </div>
      <p id="cover-progress-current" class="cover-progress-current"></p>`;
    metrics.insertAdjacentElement("afterend", panel);
    return panel;
  }

  function updateCovers(data) {
    const covers = data.cover_progress || {};
    const panel = ensureCoverPanel();
    if (!panel) return;
    panel.hidden = !covers.visible;
    if (panel.hidden) return;

    setText("cover-found", covers.found ?? 0);
    setText("cover-checked", `${covers.checked ?? 0} / ${covers.total ?? 0}`);
    setText("cover-remaining", covers.remaining ?? 0);
    setText("cover-percent", `${covers.percent ?? 0}%`);
    const bar = $("cover-progress-bar");
    if (bar) bar.style.width = `${Math.max(0, Math.min(100, Number(covers.percent || 0)))}%`;

    const current = [covers.current_artist, covers.current_title].filter(Boolean).join(" — ");
    setText(
      "cover-progress-current",
      current ? `Nu controleren: ${current}` : "Coverworker werkt de achterstand automatisch bij."
    );
    setText(
      "cover-progress-subtitle",
      covers.running
        ? "De continue coverworker vult de achterstand aan en blijft daarna nieuwe nummers automatisch volgen."
        : "Coverworker wordt opnieuw gestart; de voortgang blijft zichtbaar zolang er achterstand is."
    );
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

  function activeDownloadRows(rows) {
    const names = {
      searching: "Zoeken",
      downloading: "Downloaden",
      validating: "Valideren",
      processing: "Verwerken",
    };

    return rows.length
      ? rows.map((row) => {
          const provider = row.preferred_provider
            ? `<small class="active-provider">Bron: ${escapeHtml(row.preferred_provider)}</small>`
            : "";

          return `<article class="active-download-item active-${escapeHtml(row.status)}">
            <div class="active-download-main">
              <span class="active-pulse" aria-hidden="true"></span>
              <div>
                <b>${escapeHtml(row.artist)}</b>
                <span>${escapeHtml(row.title)}</span>
                ${provider}
              </div>
            </div>
            <span class="status-badge status-job-${escapeHtml(row.status)}">
              ${escapeHtml(names[row.status] || row.status)}
            </span>
          </article>`;
        }).join("")
      : `<div class="active-empty">
          <span class="active-empty-dot"></span>
          <div>
            <b>Geen actieve download</b>
            <span>De manager wacht op de volgende beschikbare job.</span>
          </div>
        </div>`;
  }

  async function updateActiveDownloads() {
    const list = $("active-download-list");
    if (!list) return;

    try {
      const response = await fetch("/api/download/active", {
        cache: "no-store",
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();
      const rows = data.items || [];
      const active = Number(data.active_count || rows.length || 0);
      const workers = Number(data.workers || 0);

      setText(
        "active-download-count",
        workers > 0 ? `${active} / ${workers}` : active
      );

      setText(
        "active-worker-summary",
        workers > 0
          ? `${active} van ${workers} workers actief`
          : `${active} actieve download${active === 1 ? "" : "s"}`
      );

      updateHtml(
        "active-download-list",
        JSON.stringify(data),
        activeDownloadRows(rows)
      );
    } catch (_error) {
      setText("active-download-count", "—");
      setText(
        "active-worker-summary",
        "Actieve downloadstatus tijdelijk niet beschikbaar"
      );

      updateHtml(
        "active-download-list",
        "active-error",
        '<p class="empty">Kan actieve downloads nu niet uitlezen.</p>'
      );
    }
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
              <input name="custom_search_query" value="${escapeHtml(query)}" autocomplete="off" autocapitalize="off" spellcheck="false">
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
    updateCovers(data);
    updateArchive(data);
    updateStorage(data);
    updateChart(data, "top40");
    updateChart(data, "tipparade");
    updateQueueAndActivity(data);
    updateActiveDownloads();
    updateFailed(data);
    updateUnavailable(data);
    updateSuccess(data);
  }

  function markDataReceived() {
    state.lastDataAt = Date.now();
    setConnection("online", "Live");
  }

  function updateConnectionHealth() {
    if (!state.lastDataAt) return;

    const age = Date.now() - state.lastDataAt;

    if (age > 30000) {
      setConnection("offline", "Geen actuele data");
    } else if (age > 15000) {
      setConnection("connecting", "Vertraagd");
    }
  }

  async function pollOnce() {
    if (state.pollBusy) return;

    state.pollBusy = true;

    try {
      const response = await fetch("/api/live", {
        cache: "no-store",
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();

      render(data);
      markDataReceived();
    } catch (_error) {
      if (
        !state.lastDataAt ||
        Date.now() - state.lastDataAt > 15000
      ) {
        setConnection("offline", "Offline");
      }
    } finally {
      state.pollBusy = false;
    }
  }

  function startFallback() {
    /*
     * Belangrijk:
     * polling blijft bewust actief naast EventSource.
     *
     * Een geopende SSE-socket betekent niet automatisch dat
     * er nog dashboard-events worden ontvangen.
     */
    if (!state.fallbackTimer) {
      pollOnce();

      state.fallbackTimer = window.setInterval(
        pollOnce,
        5000
      );
    }

    if (!state.watchdogTimer) {
      state.watchdogTimer = window.setInterval(
        updateConnectionHealth,
        5000
      );
    }
  }

  function stopFallback() {
    if (state.fallbackTimer) {
      window.clearInterval(state.fallbackTimer);
      state.fallbackTimer = null;
    }

    if (state.watchdogTimer) {
      window.clearInterval(state.watchdogTimer);
      state.watchdogTimer = null;
    }
  }

  function connect() {
    setConnection("connecting", "Verbinden…");

    /*
     * De HTTP-watchdog wordt altijd gestart.
     * SSE blijft daarnaast de snelle live-update leveren.
     */
    startFallback();

    if (!("EventSource" in window)) {
      return;
    }

    const source = new EventSource("/events");
    state.source = source;

    source.addEventListener("open", () => {
      /*
       * Alleen een open socket is niet genoeg om "Live"
       * te mogen tonen. Daarvoor moet echt data binnenkomen.
       */
      if (!state.lastDataAt) {
        setConnection("connecting", "Verbonden…");
      }
    });

    source.addEventListener("dashboard", (event) => {
      try {
        const data = JSON.parse(event.data);

        render(data);
        markDataReceived();
      } catch (_error) {
        setConnection("offline", "Datafout");
      }
    });

    source.addEventListener("dashboard-error", () => {
      if (
        !state.lastDataAt ||
        Date.now() - state.lastDataAt > 15000
      ) {
        setConnection("offline", "Serverfout");
      }
    });

    source.addEventListener("error", () => {
      if (
        !state.lastDataAt ||
        Date.now() - state.lastDataAt > 15000
      ) {
        setConnection("connecting", "Herverbinden…");
      }

      /*
       * EventSource probeert zelf opnieuw te verbinden.
       * De HTTP-watchdog vangt intussen de live-data op.
       */
      pollOnce();
    });
  }

  /*
   * Na slaapstand, achtergrondtab of terugkeren naar de
   * browser onmiddellijk actuele gegevens ophalen.
   */
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      pollOnce();
    }
  });

  window.addEventListener("online", pollOnce);

  window.addEventListener("beforeunload", () => {
    state.source?.close();
    stopFallback();
  });

  document.addEventListener("DOMContentLoaded", connect);
})();
