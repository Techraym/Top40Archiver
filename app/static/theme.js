(() => {
  "use strict";

  const storageKey = "top40theme";

  const moonPath =
    "M20 15.2A8.5 8.5 0 0 1 8.8 4 8.5 8.5 0 1 0 20 15.2z";

  const sunSvg =
    '<circle cx="12" cy="12" r="4"></circle>' +
    '<path d="M12 2v2"></path>' +
    '<path d="M12 20v2"></path>' +
    '<path d="M4.93 4.93l1.41 1.41"></path>' +
    '<path d="M17.66 17.66l1.41 1.41"></path>' +
    '<path d="M2 12h2"></path>' +
    '<path d="M20 12h2"></path>' +
    '<path d="M4.93 19.07l1.41-1.41"></path>' +
    '<path d="M17.66 6.34l1.41-1.41"></path>';

  function currentTheme() {
    return localStorage.getItem(storageKey) === "dark"
      ? "dark"
      : "light";
  }

  function updateButtons(theme) {
    document.querySelectorAll(".theme-toggle").forEach(button => {
      const svg = button.querySelector("svg");

      if (!svg) return;

      if (theme === "dark") {
        svg.innerHTML = sunSvg;
        button.setAttribute("title", "Lichte modus");
        button.setAttribute("aria-label", "Lichte modus");
      } else {
        svg.innerHTML = '<path d="' + moonPath + '"></path>';
        button.setAttribute("title", "Donkere modus");
        button.setAttribute("aria-label", "Donkere modus");
      }
    });
  }

  function applyTheme(theme) {
    if (theme === "dark") {
      document.documentElement.setAttribute("data-theme", "dark");
    } else {
      document.documentElement.removeAttribute("data-theme");
    }

    const meta = document.querySelector('meta[name="theme-color"]');

    if (meta) {
      meta.setAttribute(
        "content",
        theme === "dark" ? "#121110" : "#f7f7f5"
      );
    }

    updateButtons(theme);
  }

  function toggleTheme() {
    const next =
      currentTheme() === "dark"
        ? "light"
        : "dark";

    localStorage.setItem(storageKey, next);
    applyTheme(next);
  }

  document.addEventListener("DOMContentLoaded", () => {
    applyTheme(currentTheme());

    document.querySelectorAll(".theme-toggle").forEach(button => {
      button.addEventListener("click", toggleTheme);
    });
  });
})();
