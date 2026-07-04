const KIND_LABELS = { servicenow: "ServiceNow", clickup: "ClickUp", zendesk: "Zendesk" };
const KIND_BADGE_COLOR = { servicenow: "var(--blue)", clickup: "var(--violet)", zendesk: "var(--teal)" };
const INTERVAL_OPTIONS = [
  [0, "Manual only"], [15, "Every 15 min"], [30, "Every 30 min"],
  [60, "Every hour"], [360, "Every 6 hours"], [1440, "Every 24 hours"],
];

function intervalSelectHtml(selected) {
  return `<select class="select source-interval" style="font-size:12px;padding:6px 10px">
    ${INTERVAL_OPTIONS.map(([v, label]) => `<option value="${v}"${v === selected ? " selected" : ""}>${label}</option>`).join("")}
  </select>`;
}

function sourceCardHtml(s) {
  const lastSynced = s.last_synced_at
    ? `Last synced ${new Date(s.last_synced_at).toLocaleString()} — ${s.last_sync_count} ticket(s)`
    : "Never synced";
  return `
    <div class="card" style="padding:14px 18px;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap" data-source-id="${s.id}">
      <div>
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
          <span style="font:600 13px var(--font-body);color:var(--text)">${escapeHtml(s.label)}</span>
          <span style="font:600 10.5px var(--font-body);padding:2px 8px;border-radius:10px;background:${KIND_BADGE_COLOR[s.kind]};color:var(--on-accent)">${KIND_LABELS[s.kind]}</span>
        </div>
        <div class="muted" style="font-size:12px">${lastSynced}</div>
        <div class="source-feedback muted" style="font-size:12px;margin-top:4px"></div>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        ${intervalSelectHtml(s.sync_interval_minutes)}
        <div class="chip" data-action="test">Test</div>
        <div class="chip" data-action="sync">Sync Now</div>
        <div class="chip" data-action="remove" style="color:var(--critical)">Remove</div>
      </div>
    </div>`;
}

async function loadSources() {
  const data = await fetchJSON("/api/tickets/sources");
  const list = document.getElementById("sources-list");
  list.innerHTML = data.sources.length
    ? data.sources.map(sourceCardHtml).join("")
    : `<div class="muted" style="font-size:12px">No connections configured yet — add one below.</div>`;

  list.querySelectorAll("[data-source-id]").forEach((card) => {
    const id = card.dataset.sourceId;
    const feedback = card.querySelector(".source-feedback");
    card.querySelector('[data-action="test"]').addEventListener("click", async () => {
      feedback.textContent = "Testing…";
      try {
        const r = await fetchJSON(`/api/tickets/sources/${id}/test`, { method: "POST" });
        feedback.textContent = r.message;
        feedback.style.color = r.ok ? "var(--success)" : "var(--critical)";
      } catch (e) {
        feedback.textContent = e.message;
        feedback.style.color = "var(--critical)";
      }
    });
    card.querySelector('[data-action="sync"]').addEventListener("click", async () => {
      feedback.textContent = "Syncing…";
      feedback.style.color = "var(--text-softer)";
      try {
        const r = await fetchJSON(`/api/tickets/sources/${id}/sync`, { method: "POST" });
        feedback.textContent = `Synced ${r.count} ticket(s).`;
        feedback.style.color = "var(--success)";
        await loadSources();
        if (typeof loadMeta === "function") await loadMeta().then(refresh);
      } catch (e) {
        feedback.textContent = e.message;
        feedback.style.color = "var(--critical)";
      }
    });
    card.querySelector('[data-action="remove"]').addEventListener("click", async () => {
      if (!confirm(`Remove "${card.querySelector("span").textContent}"? Already-imported tickets stay in the dashboard.`)) return;
      await fetchJSON(`/api/tickets/sources/${id}`, { method: "DELETE" });
      await loadSources();
    });
    card.querySelector(".source-interval").addEventListener("change", async (e) => {
      feedback.textContent = "Saving…";
      feedback.style.color = "var(--text-softer)";
      try {
        await fetchJSON(`/api/tickets/sources/${id}`, {
          method: "PATCH",
          body: JSON.stringify({ sync_interval_minutes: parseInt(e.target.value, 10) }),
        });
        feedback.textContent = "Saved.";
        feedback.style.color = "var(--success)";
      } catch (err) {
        feedback.textContent = err.message;
        feedback.style.color = "var(--critical)";
      }
    });
  });
}

document.getElementById("add-source-btn").addEventListener("click", async () => {
  const errorEl = document.getElementById("add-source-error");
  errorEl.innerHTML = "";
  const body = {
    label: document.getElementById("src-label").value,
    kind: document.getElementById("src-kind").value,
    instance: document.getElementById("src-instance").value,
    username: document.getElementById("src-username").value,
    token: document.getElementById("src-token").value,
    list_or_view_id: document.getElementById("src-list").value,
    sync_interval_minutes: parseInt(document.getElementById("src-interval").value, 10),
  };
  try {
    await fetchJSON("/api/tickets/sources", { method: "POST", body: JSON.stringify(body) });
    ["src-label", "src-instance", "src-username", "src-token", "src-list"].forEach((id) => (document.getElementById(id).value = ""));
    document.getElementById("src-interval").value = "0";
    await loadSources();
  } catch (e) {
    errorEl.innerHTML = `<div class="error-box">${escapeHtml(e.message)}</div>`;
  }
});

document.getElementById("sync-all-btn").addEventListener("click", async () => {
  const btn = document.getElementById("sync-all-btn");
  btn.textContent = "Syncing…";
  try {
    const { results } = await fetchJSON("/api/tickets/sources/sync-all", { method: "POST" });
    const failed = results.filter((r) => !r.ok);
    btn.textContent = failed.length
      ? `Done, ${failed.length} failed`
      : `Synced ${results.length} source(s)`;
    await loadSources();
    if (typeof loadMeta === "function") await loadMeta().then(refresh);
  } catch (e) {
    btn.textContent = "Sync All Now";
    alert(e.message);
  } finally {
    setTimeout(() => (btn.textContent = "Sync All Now"), 4000);
  }
});

document.getElementById("upload-btn").addEventListener("click", async () => {
  const resultEl = document.getElementById("upload-result");
  const label = document.getElementById("upload-label").value;
  const fileInput = document.getElementById("upload-file");
  if (!label.trim() || !fileInput.files.length) {
    resultEl.innerHTML = `<div class="error-box">Enter a label and choose a file first.</div>`;
    return;
  }
  const formData = new FormData();
  formData.append("source_entity", label);
  formData.append("file", fileInput.files[0]);

  resultEl.innerHTML = `<div class="muted">Uploading…</div>`;
  try {
    const response = await fetch("/api/tickets/upload", { method: "POST", body: formData });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
    resultEl.innerHTML = `<div style="color:var(--success);font-size:13px">Imported ${data.count} ticket(s).</div>`;
    fileInput.value = "";
    document.getElementById("upload-label").value = "";
    if (typeof loadMeta === "function") await loadMeta().then(refresh);
  } catch (e) {
    resultEl.innerHTML = `<div class="error-box">${escapeHtml(e.message)}</div>`;
  }
});

loadSources();
