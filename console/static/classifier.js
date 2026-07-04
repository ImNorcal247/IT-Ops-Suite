const PRIORITY_COLOR = { Critical: "var(--critical)", High: "var(--high)", Medium: "var(--blue)", Low: "var(--teal)" };

const descriptionInput = document.getElementById("description-input");
const contextInput = document.getElementById("context-input");
const classifyBtn = document.getElementById("classify-btn");
const result = document.getElementById("result");

async function runClassify() {
  const description = descriptionInput.value.trim();
  if (!description) return;
  classifyBtn.disabled = true;
  result.innerHTML = `<div class="muted">Classifying…</div>`;
  try {
    const r = await fetchJSON("/api/classify", {
      method: "POST",
      body: JSON.stringify({ description, context: contextInput.value.trim() }),
    });
    const actions = (r.immediate_actions || []).map((text, i) => `<div style="font:400 13.5px/1.5 var(--font-body);color:var(--text-soft)">${i + 1}. ${escapeHtml(text)}</div>`).join("");
    result.innerHTML = `
      <div class="card" style="padding:26px 28px">
        <div class="result-grid">
          <div class="result-cell"><div class="value">${escapeHtml(r.category)}</div><div class="label">${escapeHtml(r.subcategory)}</div></div>
          <div class="result-cell"><div class="value" style="color:${PRIORITY_COLOR[r.priority] || "var(--text)"}">${escapeHtml(r.priority)}</div><div class="label">Priority</div></div>
          <div class="result-cell"><div class="value">${escapeHtml(r.assigned_team)}</div><div class="label">Assigned Team</div></div>
        </div>
        <div class="muted" style="margin-bottom:18px">Estimated resolution time: <span style="color:var(--text)">${escapeHtml(r.estimated_resolution_time)}</span></div>
        <div style="font:600 13px var(--font-body);color:var(--text);margin-bottom:10px">Immediate Actions</div>
        <div style="display:flex;flex-direction:column;gap:6px;margin-bottom:18px">${actions}</div>
        <div class="muted" style="margin-bottom:10px"><strong style="color:var(--text-soft)">Similar incidents:</strong> ${escapeHtml((r.similar_incidents || []).join(", "))}</div>
        <div class="muted"><strong style="color:var(--text-soft)">Escalate if:</strong> ${escapeHtml(r.escalate_if)}</div>
      </div>`;
  } catch (e) {
    result.innerHTML = `<div class="error-box">${escapeHtml(e.message)}</div>`;
  } finally {
    classifyBtn.disabled = false;
  }
}

classifyBtn.addEventListener("click", runClassify);
