const EXAMPLE_QUESTIONS = [
  "Which team has the most open tickets?",
  "How many critical tickets are still open?",
  "What's the average resolution time for Network tickets?",
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
  result.innerHTML = `<div class="muted">Thinking…</div>`;
  try {
    const data = await fetchJSON("/api/ask-data", { method: "POST", body: JSON.stringify({ question }) });
    let html = `
      <div class="muted" style="margin-bottom:10px">Your question:</div>
      <div class="answer-question">${escapeHtml(question)}</div>
      <div class="answer-row">
        <div class="answer-avatar" style="background:var(--cyan)"></div>
        <div class="answer-bubble">${renderAnswer(data.answer)}</div>
      </div>`;
    if (data.sql) {
      html += `
        <details style="margin-top:16px;padding:12px 16px;border-radius:8px;background:var(--bg-band);border:1px solid var(--border-soft)">
          <summary style="cursor:pointer;font:500 11.5px var(--font-body);color:var(--text-softer)">Show generated SQL and raw results</summary>
          <pre style="margin-top:10px;white-space:pre-wrap;font:400 12px var(--font-mono);color:var(--text-soft)">${escapeHtml(data.sql)}</pre>
          <pre style="margin-top:6px;white-space:pre-wrap;font:400 11.5px var(--font-mono);color:var(--text-softer)">${escapeHtml(JSON.stringify(data.rows, null, 2))}</pre>
        </details>`;
    }
    result.innerHTML = html;
  } catch (e) {
    result.innerHTML = `<div class="error-box">${escapeHtml(e.message)}</div>`;
  } finally {
    askBtn.disabled = false;
  }
}

askBtn.addEventListener("click", runAsk);
input.addEventListener("keydown", (e) => { if (e.key === "Enter") runAsk(); });
