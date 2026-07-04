const problemInput = document.getElementById("problem-input");
const submitBtn = document.getElementById("submit-btn");
const stagesEl = document.getElementById("stages");
const bannerEl = document.getElementById("banner");

function stageLine(html) {
  const div = document.createElement("div");
  div.className = "stage-row";
  div.innerHTML = html;
  stagesEl.appendChild(div);
}

function handleEvent(evt) {
  const r = evt.result || {};
  if (evt.stage === "triage") {
    stageLine(`<span style="color:var(--success)">✅</span> <strong>Triage</strong> → ${escapeHtml(r.category)}/${escapeHtml(r.subcategory)} · ${escapeHtml(r.priority)}`);
  } else if (evt.stage === "duplicate_check") {
    const reasoning = r.reasoning ? ` — ${escapeHtml(r.reasoning)}` : "";
    stageLine(`<span style="color:var(--success)">✅</span> <strong>Duplicate check</strong> → duplicate=${r.is_duplicate}${reasoning}`);
  } else if (evt.stage === "assignment") {
    stageLine(`<span style="color:var(--success)">✅</span> <strong>Assignment</strong> → ${escapeHtml(r.assignment_group)}`);
  } else if (evt.stage === "create") {
    stageLine(`<span style="color:var(--success)">✅</span> <strong>Ticket created</strong> → ${escapeHtml(r.ticket_id || "unknown")}`);
  } else if (evt.stage === "final") {
    document.getElementById("running-line")?.remove();
    if (r.action === "linked_to_existing") {
      bannerEl.innerHTML = `<div class="result-banner">Linked as duplicate of <strong>${escapeHtml(r.linked_ticket_id)}</strong> — no new ticket created.</div>`;
    } else {
      bannerEl.innerHTML = `<div class="result-banner">Ticket <strong>${escapeHtml(r.ticket_id)}</strong> created and routed to <strong>${escapeHtml(r.assignment_group)}</strong></div>`;
    }
  } else if (evt.stage === "error") {
    document.getElementById("running-line")?.remove();
    bannerEl.innerHTML = `<div class="error-box">${escapeHtml(r.error || "Pipeline failed.")}</div>`;
  }
}

async function runPipeline() {
  const raw_input = problemInput.value.trim();
  if (!raw_input) return;
  submitBtn.disabled = true;
  stagesEl.innerHTML = `<div class="stage-pending" id="running-line">⏳ Running pipeline…</div>`;
  bannerEl.innerHTML = "";

  try {
    const response = await fetch("/api/orchestrator/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ raw_input }),
    });
    if (!response.ok || !response.body) {
      throw new Error(`Request failed (${response.status})`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sepIndex;
      while ((sepIndex = buffer.indexOf("\n\n")) !== -1) {
        const chunk = buffer.slice(0, sepIndex);
        buffer = buffer.slice(sepIndex + 2);
        if (chunk.startsWith("data: ")) {
          handleEvent(JSON.parse(chunk.slice(6)));
        }
      }
    }
  } catch (e) {
    document.getElementById("running-line")?.remove();
    bannerEl.innerHTML = `<div class="error-box">${escapeHtml(e.message)}</div>`;
  } finally {
    submitBtn.disabled = false;
  }
}

submitBtn.addEventListener("click", runPipeline);
problemInput.addEventListener("keydown", (e) => { if (e.key === "Enter") runPipeline(); });
