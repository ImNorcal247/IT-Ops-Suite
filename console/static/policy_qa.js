const EXAMPLE_QUESTIONS = [
  "How long before passwords expire?",
  "What do I do if I suspect a SEV1 incident?",
  "Can I VPN in from my personal laptop?",
];

const input = document.getElementById("question-input");
const askBtn = document.getElementById("ask-btn");
const result = document.getElementById("result");

document.getElementById("example-chips").innerHTML = EXAMPLE_QUESTIONS
  .map((q, i) => `<div class="chip" data-idx="${i}">${escapeHtml(q)}</div>`)
  .join("");
document.querySelectorAll("#example-chips .chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    input.value = EXAMPLE_QUESTIONS[chip.dataset.idx];
    runAsk();
  });
});

async function runAsk() {
  const question = input.value.trim();
  if (!question) return;
  askBtn.disabled = true;
  result.innerHTML = `<div class="muted">Searching policies…</div>`;
  try {
    const data = await fetchJSON("/api/policy-qa", { method: "POST", body: JSON.stringify({ question }) });
    result.innerHTML = `
      <div class="muted" style="margin-bottom:10px">Your question:</div>
      <div class="answer-question">${escapeHtml(question)}</div>
      <div class="answer-row" style="margin-bottom:14px">
        <div class="answer-avatar" style="background:var(--violet)"></div>
        <div class="answer-bubble">${renderAnswer(data.answer)}</div>
      </div>
      <div style="display:flex;gap:10px;align-items:center;padding-left:38px;flex-wrap:wrap">
        <span class="muted" style="font-size:12px">Sources: ${escapeHtml(data.sources && data.sources.length ? data.sources.join(", ") : "none")}</span>
        <span class="badge-success">Confidence: ${escapeHtml(data.confidence)}</span>
      </div>`;
  } catch (e) {
    result.innerHTML = `<div class="error-box">${escapeHtml(e.message)}</div>`;
  } finally {
    askBtn.disabled = false;
  }
}

askBtn.addEventListener("click", runAsk);
input.addEventListener("keydown", (e) => { if (e.key === "Enter") runAsk(); });
