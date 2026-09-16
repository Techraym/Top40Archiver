(() => {
  'use strict';

  const $ = (s) => document.querySelector(s);
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt = (v) => (v === null || v === undefined || v === '') ? '—' : v;
  const statusLabels = {
    complete:'Compleet', needs_metadata:'Metadata nodig', needs_cover:'Cover nodig', needs_genre:'Genre nodig',
    pending_analysis:'Analyse wacht', low_confidence:'Lage confidence', warning:'Waarschuwing',
    scan_error:'Scanfout', audio_corrupt:'Audio beschadigd'
  };
  let searchTimer = null;
  let refreshBusy = false;

  function banner(message, kind='error') {
    const el = $('#api-banner');
    if (!el) return;
    if (!message) { el.textContent=''; el.className='api-banner hidden'; return; }
    el.textContent = message;
    el.className = `api-banner ${kind}`;
  }

  async function api(url, options={}) {
    const response = await fetch(url, {cache:'no-store', ...options});
    let payload = null;
    try { payload = await response.json(); } catch (_) { /* handled below */ }
    if (!response.ok) throw new Error(payload?.detail || payload?.message || `HTTP ${response.status}`);
    return payload ?? {};
  }

  function fmtTime(value) {
    if (value === null || value === undefined) return '—';
    const n = Number(value);
    if (!Number.isFinite(n)) return '—';
    const m = Math.floor(n / 60);
    const s = (n - m * 60).toFixed(1).padStart(4, '0');
    return `${m}:${s}`;
  }

  function statusClass(status) {
    return `status ${String(status || '').replace(/[^a-z_]/g, '')}`;
  }

  async function loadSummary() {
    const d = await api('/api/summary');
    $('#score').textContent = `${Number(d.average_score || 0).toFixed(1)}%`;
    $('#total').textContent = d.total ?? 0;
    $('#missing-cover').textContent = d.missing_cover ?? 0;
    $('#missing-genre').textContent = d.missing_genre ?? 0;
    $('#missing-radio').textContent = d.missing_radio ?? 0;
    $('#audio-corrupt').textContent = d.audio_corrupt ?? 0;
    $('#radio-threshold').textContent = `${Math.round(Number(d.radio_write_confidence || .84) * 100)}%`;

    const s = d.state || {};
    const running = !!s.running;
    $('#scan-button').disabled = running;
    $('#scan-size').disabled = running;
    $('#run-pill').textContent = running ? 'bezig' : 'gereed';
    $('#run-pill').className = `pill ${running ? 'running' : ''}`;
    $('#run-title').textContent = running ? 'Controle & herstel draait' : (d.last_run ? 'Laatste controle gereed' : 'Nog geen scan uitgevoerd');
    $('#run-processed').textContent = s.processed ?? d.last_run?.processed ?? 0;
    $('#run-skipped').textContent = s.skipped ?? d.last_run?.skipped ?? 0;
    $('#run-repaired').textContent = s.repaired ?? d.last_run?.repaired ?? 0;
    $('#run-failed').textContent = s.failed ?? d.last_run?.failed ?? 0;
    const total = Number(s.total || d.last_run?.total_files || 0);
    const done = Number(s.processed || 0) + Number(s.skipped || 0);
    $('#progress-bar').style.width = running && total ? `${Math.min(100, done / total * 100)}%` : (d.last_run ? '100%' : '0%');
    $('#current-file').textContent = running
      ? `${s.current || 0}/${total || '?'} · ${s.current_file || 'voorbereiden…'}`
      : (d.last_run ? `Laatste run: ${d.last_run.processed} verwerkt, ${d.last_run.failed} mislukt.` : 'Ongewijzigde complete bestanden worden automatisch overgeslagen.');
    return running;
  }

  async function loadTracks() {
    const params = new URLSearchParams({limit:'250'});
    const status = $('#status').value;
    const q = $('#search').value.trim();
    if (status) params.set('status', status);
    if (q) params.set('q', q);
    const d = await api(`/api/tracks?${params.toString()}`);
    const body = $('#tracks-body');
    body.innerHTML = (d.items || []).map((x) => {
      const warnings = Array.isArray(x.warning_fields) && x.warning_fields.length ? `<small class="warn">${esc(x.warning_fields.join(' · '))}</small>` : '';
      const missing = Array.isArray(x.missing_fields) && x.missing_fields.length ? `<small>mist: ${esc(x.missing_fields.join(', '))}</small>` : '';
      return `<tr>
        <td><b>${esc(x.artist || 'Onbekend')} — ${esc(x.title || 'Onbekend')}</b><small title="${esc(x.file_path)}">${esc(x.file_path)}</small>${missing}</td>
        <td><span class="${statusClass(x.scan_status)}">${esc(statusLabels[x.scan_status] || x.scan_status)}</span>${warnings}</td>
        <td>${fmt(x.quality_score)}%</td>
        <td>${x.cover_present ? '✓' : '—'}${x.cover_width ? `<small>${x.cover_width}×${x.cover_height}</small>` : ''}</td>
        <td>${esc(fmt(x.genre))}</td>
        <td>${fmtTime(x.intro_end)}<small>${x.radio_confidence != null ? `conf. ${Math.round(x.radio_confidence*100)}%` : ''}</small></td>
        <td>${fmtTime(x.outro_start)}<small>mix ${fmtTime(x.safe_mixout_start)}</small></td>
        <td>${x.lufs == null ? '—' : Number(x.lufs).toFixed(1)}<small>peak ${x.true_peak == null ? '—' : Number(x.true_peak).toFixed(1)} dBTP</small></td>
      </tr>`;
    }).join('') || '<tr><td colspan="8">Geen resultaten voor dit filter.</td></tr>';
  }

  async function loadEvents() {
    const d = await api('/api/events?limit=30');
    $('#events-list').innerHTML = (d.items || []).map((e) => `<article class="event">
      <span class="event-dot ${esc(e.event_type)}"></span>
      <div><b>${esc(e.event_type === 'error' ? 'Fout' : e.event_type === 'repaired' ? 'Hersteld' : 'Gecontroleerd')}</b>
      <span>${esc((e.file_path || '').split('/').pop())}</span><small>${esc(e.detail || '')} · ${esc(e.created_at || '')}</small></div>
    </article>`).join('') || '<p class="muted">Nog geen activiteit.</p>';
  }

  async function refreshAll(showErrors=true) {
    if (refreshBusy) return;
    refreshBusy = true;
    try {
      await Promise.all([loadSummary(), loadTracks(), loadEvents()]);
      banner('');
    } catch (error) {
      console.error(error);
      if (showErrors) banner(`8085 kon data niet laden: ${error.message}`);
    } finally {
      refreshBusy = false;
    }
  }

  async function startScan() {
    const maxFiles = Number($('#scan-size').value || 25);
    if (maxFiles >= 1000000 && !window.confirm('De volledige bibliotheek verwerken? Dit kan lang duren.')) return;
    $('#scan-button').disabled = true;
    banner('Scan wordt gestart…', 'info');
    try {
      const result = await api(`/api/scan?max_files=${encodeURIComponent(maxFiles)}`, {method:'POST'});
      if (!result.ok && result.running) throw new Error(result.message || 'Er draait al een scan.');
      banner(result.message || 'Controle & herstel gestart.', 'success');
      await loadSummary();
    } catch (error) {
      banner(`Starten mislukt: ${error.message}`);
      $('#scan-button').disabled = false;
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    $('#core-link').href = `${location.protocol}//${location.hostname}:8040/`;
    $('#scan-button').addEventListener('click', startScan);
    $('#refresh-button').addEventListener('click', () => refreshAll(true));
    $('#status').addEventListener('change', () => loadTracks().catch((e) => banner(`Filter laden mislukt: ${e.message}`)));
    $('#search').addEventListener('input', () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => loadTracks().catch((e) => banner(`Zoeken mislukt: ${e.message}`)), 250);
    });
    refreshAll(true);
    setInterval(() => loadSummary().catch((e) => banner(`Status verversen mislukt: ${e.message}`)), 3000);
    setInterval(() => Promise.all([loadTracks(), loadEvents()]).catch((e) => banner(`Resultaten verversen mislukt: ${e.message}`)), 12000);
  });
})();
