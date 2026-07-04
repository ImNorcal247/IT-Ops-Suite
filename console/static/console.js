// Shared helpers for every console screen: theme persistence + a small
// fetch wrapper. No framework/bundler — plain DOM manipulation per screen.

(function () {
  const STORAGE_KEY = "itops-theme";

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    const toggle = document.getElementById("theme-toggle");
    if (toggle) toggle.classList.toggle("on", theme === "light");
  }

  function initTheme() {
    const stored = localStorage.getItem(STORAGE_KEY) || "dark";
    applyTheme(stored);
  }

  function toggleTheme() {
    const current = document.documentElement.getAttribute("data-theme") || "dark";
    const next = current === "light" ? "dark" : "light";
    localStorage.setItem(STORAGE_KEY, next);
    applyTheme(next);
  }

  window.itops = window.itops || {};
  window.itops.initTheme = initTheme;
  window.itops.toggleTheme = toggleTheme;

  document.addEventListener("DOMContentLoaded", initTheme);
})();

async function fetchJSON(url, options) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = data && data.detail ? data.detail : `Request failed (${response.status})`;
    throw new Error(message);
  }
  return data;
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value == null ? "" : String(value);
  return div.innerHTML;
}

// Claude's free-text answers aren't instructed to avoid markdown, so a
// **bold** phrase now and then is expected — render just that, nothing else.
function renderAnswer(value) {
  return escapeHtml(value).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}
