(() => {
  "use strict";
  const esc = (value) => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  async function load() {
    try {
      const response = await fetch('/api/health/advice?range=24h', {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const headline = data.headline || {};
      document.getElementById('advisor-title').textContent = headline.title || 'Geen advies beschikbaar';
      document.getElementById('advisor-explanation').textContent = headline.explanation || '';
      document.getElementById('advisor-action').textContent = headline.action || 'Geen actie nodig';
      document.getElementById('advisor-score').textContent = `${data.score ?? 0}%`;
      document.getElementById('advisor-confidence').textContent = `${Math.round(Number(headline.confidence || 0) * 100)}% zekerheid`;
      const rows = data.advice || [];
      document.getElementById('advisor-list').innerHTML = rows.length ? rows.map((item) => `<article class="advisor-item ${esc(item.level)}"><b>${esc(item.title)}</b><span>${esc(item.explanation)}</span><small>Aanpak: ${esc(item.action)} · ${Math.round(Number(item.confidence || 0) * 100)}% zekerheid</small></article>`).join('') : '<p class="empty">Geen adviezen.</p>';
    } catch (error) {
      document.getElementById('advisor-title').textContent = 'AI-analyse niet beschikbaar';
      document.getElementById('advisor-explanation').textContent = error.message;
    }
  }
  document.addEventListener('DOMContentLoaded', load);
})();
