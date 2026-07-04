const MODE_LABELS = {
  mock: "Mock (no external system)",
  clickup: "ClickUp only",
  servicenow: "ServiceNow only",
  both: "Both — dual write",
};
const MODE_KEYS = ["mock", "clickup", "servicenow", "both"];

let state = { mode: "mock", dry_run: true };

function renderSegmented() {
  const el = document.getElementById("mode-segmented");
  el.innerHTML = MODE_KEYS.map((k) => `<div class="segmented-option${state.mode === k ? " active" : ""}" data-mode="${k}">${MODE_LABELS[k]}</div>`).join("");
  el.querySelectorAll(".segmented-option").forEach((opt) => {
    opt.addEventListener("click", () => {
      state.mode = opt.dataset.mode;
      render();
    });
  });
}

function render() {
  renderSegmented();
  document.getElementById("clickup-fields").style.display = state.mode === "clickup" || state.mode === "both" ? "block" : "none";
  document.getElementById("servicenow-fields").style.display = state.mode === "servicenow" || state.mode === "both" ? "block" : "none";
  document.getElementById("warning").innerHTML = state.mode !== "mock" && !state.dry_run
    ? `<div class="warning-box">Dry run is OFF — ticket creation and duplicate comments will write to the real system(s) below.</div>`
    : "";
  const toggle = document.getElementById("dry-run-toggle");
  toggle.classList.toggle("on", state.dry_run);
}

document.getElementById("dry-run-toggle").addEventListener("click", () => {
  state.dry_run = !state.dry_run;
  render();
});

document.getElementById("test-clickup-btn").addEventListener("click", async () => {
  const token = document.getElementById("cu-token").value;
  const resultEl = document.getElementById("cu-result");
  resultEl.textContent = "Testing…";
  resultEl.style.color = "var(--text-softer)";
  try {
    const data = await fetchJSON("/api/settings/test-clickup", { method: "POST", body: JSON.stringify({ token }) });
    resultEl.textContent = data.message;
    resultEl.style.color = data.ok ? "var(--success)" : "var(--critical)";
  } catch (e) {
    resultEl.textContent = e.message;
    resultEl.style.color = "var(--critical)";
  }
});

document.getElementById("test-servicenow-btn").addEventListener("click", async () => {
  const instance = document.getElementById("sn-instance").value;
  const username = document.getElementById("sn-user").value;
  const password = document.getElementById("sn-pass").value;
  const resultEl = document.getElementById("sn-result");
  resultEl.textContent = "Testing…";
  resultEl.style.color = "var(--text-softer)";
  try {
    const data = await fetchJSON("/api/settings/test-servicenow", { method: "POST", body: JSON.stringify({ instance, username, password }) });
    resultEl.textContent = data.message;
    resultEl.style.color = data.ok ? "var(--success)" : "var(--critical)";
  } catch (e) {
    resultEl.textContent = e.message;
    resultEl.style.color = "var(--critical)";
  }
});

document.getElementById("save-btn").addEventListener("click", async () => {
  const body = {
    mode: state.mode,
    dry_run: state.dry_run,
    clickup_token: document.getElementById("cu-token").value,
    clickup_default_list: document.getElementById("cu-list").value,
    clickup_lists: {},
    servicenow_instance: document.getElementById("sn-instance").value,
    servicenow_username: document.getElementById("sn-user").value,
    servicenow_password: document.getElementById("sn-pass").value,
  };
  const note = document.getElementById("saved-note");
  try {
    const data = await fetchJSON("/api/settings", { method: "POST", body: JSON.stringify(body) });
    note.textContent = `Saved. Active backend: ${MODE_LABELS[data.mode]}${data.dry_run ? " (dry run)" : ""}`;
  } catch (e) {
    note.textContent = "";
    document.getElementById("warning").innerHTML = `<div class="error-box">${escapeHtml(e.message)}</div>`;
  }
});

async function init() {
  const data = await fetchJSON("/api/settings");
  state.mode = data.mode;
  state.dry_run = data.dry_run;
  document.getElementById("cu-list").value = data.clickup_default_list || "";
  document.getElementById("sn-instance").value = data.servicenow_instance || "";
  document.getElementById("sn-user").value = data.servicenow_username || "";
  render();
}

init();
