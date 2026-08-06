(() => {
  "use strict";
  document.addEventListener("DOMContentLoaded", () => {
    const actions = document.querySelector(".header-actions");
    if (!actions || document.getElementById("ai-sidecar-link")) return;
    const link = document.createElement("a");
    link.id = "ai-sidecar-link";
    link.className = "button quiet";
    link.textContent = "AI";
    link.title = "Open het afzonderlijke AI Operations Center op poort 8041";
    link.href = `${window.location.protocol}//${window.location.hostname}:8041/`;
    actions.appendChild(link);
  });
})();
