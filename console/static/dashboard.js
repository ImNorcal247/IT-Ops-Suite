const PRIORITY_COLORS = {
  Critical: { bg: "rgba(230,90,70,.14)", color: "var(--critical)" },
  High: { bg: "rgba(230,160,60,.14)", color: "var(--high)" },
  Medium: { bg: "rgba(100,140,230,.14)", color: "var(--blue)" },
  Low: { bg: "rgba(90,190,150,.14)", color: "var(--teal)" },
};
const CATEGORY_COLORS = {
  Network: "var(--teal)", Application: "var(--cyan)", Hardware: "var(--violet)",
  Access: "var(--blue)", Database: "var(--success)", Security: "var(--critical)",
};

let teamsByEntity = { "All Entities": [] };

function populateSelect(select, options, selected) {
  select.innerHTML = options.map((o) => `<option value="${escapeHtml(o)}"${o === selected ? " selected" : ""}>${escapeHtml(o)}</option>`).join("");
}

async function loadMeta() {
  const meta = await fetchJSON("/api/tickets/meta");
  teamsByEntity = meta.teams_by_entity;
  populateSelect(document.getElementById("entity-select"), ["All Entities", ...meta.entities], "All Entities");
  populateSelect(document.getElementById("team-select"), ["All Teams", ...teamsByEntity["All Entities"]], "All Teams");
}

function renderDashboard(data) {
  const body = document.getElementById("dashboard-body");
  if (!data.has_data) {
    body.innerHTML = `<div class="muted" style="padding:60px 0;text-align:center">No ticket data found. Run <code>python setup_sample_data.py</code> first.</div>`;
    return;
  }
  if (data.empty) {
    body.innerHTML = `<div class="muted" style="padding:60px 0;text-align:center">No tickets found for this filter.</div>`;
    return;
  }

  const m = data.metrics;
  const pc = data.priority_counts;
  const cc = data.category_counts;
  const maxCount = Math.max(pc.Critical, pc.High, pc.Medium, pc.Low, 1);
  const barHeight = (count) => Math.max(4, Math.round((count / maxCount) * 120));

  const catTotal = Object.values(cc).reduce((a, b) => a + b, 0) || 1;
  let acc = 0;
  const stops = Object.entries(cc).map(([cat, count]) => {
    const start = acc / catTotal;
    acc += count;
    const end = acc / catTotal;
    return `${CATEGORY_COLORS[cat]} ${start}turn ${end}turn`;
  });

  const rowsHtml = data.rows.map((t) => `
    <div class="ticket-row">
      <div style="color:var(--text-softer)">${t.id}</div>
      <div class="ellipsis">${escapeHtml(t.source_entity)}</div>
      <div class="ellipsis">${escapeHtml(t.description)}</div>
      <div>${escapeHtml(t.category)}</div>
      <div><span class="priority-pill" style="background:${(PRIORITY_COLORS[t.priority] || {}).bg || ""};color:${(PRIORITY_COLORS[t.priority] || {}).color || "var(--text)"}">${escapeHtml(t.priority)}</span></div>
      <div class="ellipsis">${escapeHtml(t.assigned_team)}</div>
      <div>${escapeHtml(t.status)}</div>
      <div style="color:var(--text-softer)">${escapeHtml(t.created_date)}</div>
    </div>`).join("");

  body.innerHTML = `
    <div class="metrics-grid">
      <div><div class="metric-value">${m.total}</div><div class="metric-label">Total Tickets</div></div>
      <div><div class="metric-value">${m.entities}</div><div class="metric-label">Source Entities</div></div>
      <div><div class="metric-value">${m.open}</div><div class="metric-label">Open / In Progress</div></div>
      <div><div class="metric-value" style="color:var(--critical)">${m.critical}</div><div class="metric-label">Critical Priority</div></div>
      <div><div class="metric-value">${m.avg_resolution ?? "N/A"}</div><div class="metric-label">Avg Resolution (hrs)</div></div>
    </div>
    <div class="chart-row">
      <div class="card chart-panel">
        <div class="chart-title">Tickets by Priority</div>
        <div class="bar-chart">
          <div class="bar-col"><div class="bar" style="height:${barHeight(pc.Critical)}px;background:var(--critical)"></div><div class="bar-label">Critical (${pc.Critical})</div></div>
          <div class="bar-col"><div class="bar" style="height:${barHeight(pc.High)}px;background:var(--high)"></div><div class="bar-label">High (${pc.High})</div></div>
          <div class="bar-col"><div class="bar" style="height:${barHeight(pc.Medium)}px;background:var(--blue)"></div><div class="bar-label">Medium (${pc.Medium})</div></div>
          <div class="bar-col"><div class="bar" style="height:${barHeight(pc.Low)}px;background:var(--teal)"></div><div class="bar-label">Low (${pc.Low})</div></div>
        </div>
      </div>
      <div class="card chart-panel">
        <div class="chart-title">Tickets by Category</div>
        <div class="donut-row">
          <div class="donut" style="background:conic-gradient(${stops.join(", ")})"></div>
          <div class="donut-legend">
            ${Object.entries(cc).map(([cat, count]) => `<div class="legend-row"><div class="swatch" style="background:${CATEGORY_COLORS[cat]}"></div>${cat} (${count})</div>`).join("")}
          </div>
        </div>
      </div>
    </div>
    <div class="card">
      <div class="ticket-table-header">Raw Ticket Data (${m.total})</div>
      <div>${rowsHtml}</div>
      ${data.has_more ? `<div class="more-count">+${data.more_count} more tickets</div>` : ""}
    </div>
  `;
}

async function refresh() {
  const entity = document.getElementById("entity-select").value;
  const team = document.getElementById("team-select").value;
  const params = new URLSearchParams({ source_entity: entity, assigned_team: team });
  const data = await fetchJSON(`/api/tickets?${params}`);
  renderDashboard(data);
}

document.getElementById("entity-select").addEventListener("change", (e) => {
  const teams = teamsByEntity[e.target.value] || [];
  populateSelect(document.getElementById("team-select"), ["All Teams", ...teams], "All Teams");
  refresh();
});
document.getElementById("team-select").addEventListener("change", refresh);

loadMeta().then(refresh).catch((e) => {
  document.getElementById("dashboard-body").innerHTML = `<div class="error-box">${escapeHtml(e.message)}</div>`;
});
