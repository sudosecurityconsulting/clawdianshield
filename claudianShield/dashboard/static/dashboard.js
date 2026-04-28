"use strict";

// =====================================================================
// ClawdianShield SOC console — frontend
// Reads /api/stats + /api/runs on load, then live-tails events via /ws.
// =====================================================================

const SEVERITY_COLOR = {
  critical: "#ff3b30",
  high: "#e7664c",
  medium: "#d6bf57",
  low: "#54b399",
  info: "#5f6878",
};
const SEVERITY_ORDER = ["info", "low", "medium", "high", "critical"];

const STATE = {
  events: [],
  runs: [],
  attackMap: {},
  activeRun: null,
  selectedRunId: null,
  paused: false,
  ingestBucket: { ts: Math.floor(Date.now() / 1000), count: 0 },
  ingestRate: 0,
};

const charts = {};

// ---------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", async () => {
  bindTabs();
  bindFilters();
  startClock();
  await Promise.all([loadStats(), loadRuns(), loadAttackMap()]);
  initCharts();
  renderAll();
  connectWebSocket();
  setInterval(refreshStats, 5000);
  setInterval(updateIngestRate, 1000);
});

function bindTabs() {
  document.querySelectorAll(".topnav a").forEach((a) => {
    a.addEventListener("click", () => {
      document.querySelectorAll(".topnav a").forEach((x) => x.classList.remove("active"));
      a.classList.add("active");
      document.querySelectorAll(".tab").forEach((t) => t.classList.add("hidden"));
      const target = document.getElementById(`tab-${a.dataset.tab}`);
      if (target) target.classList.remove("hidden");
    });
  });
}

function bindFilters() {
  ["f-severity", "f-type", "f-host", "f-q", "f-pause"].forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("input", renderEventStream);
    el.addEventListener("change", () => {
      if (id === "f-pause") STATE.paused = el.checked;
      renderEventStream();
    });
  });
}

function startClock() {
  const tick = () => {
    const d = new Date();
    const utc = d.toISOString().substring(11, 19);
    document.getElementById("clock").textContent = `${utc} UTC`;
  };
  tick();
  setInterval(tick, 1000);
}

// ---------------------------------------------------------------------
// REST loaders
// ---------------------------------------------------------------------

async function loadStats() {
  const r = await fetch("/api/stats");
  const stats = await r.json();
  STATE.stats = stats;
  STATE.activeRun = stats.latest_run || null;
}

async function loadRuns() {
  const r = await fetch("/api/runs");
  STATE.runs = await r.json();
  if (STATE.runs.length && !STATE.selectedRunId) {
    STATE.selectedRunId = STATE.runs[0].run_id;
  }
}

async function loadAttackMap() {
  const r = await fetch("/api/attack-map");
  STATE.attackMap = await r.json();
}

async function refreshStats() {
  await loadStats();
  await loadRuns();
  renderKPIs();
  renderTimeseries();
  renderTypes();
  renderSeverity();
  renderCollectors();
  renderTopTables();
  renderActiveRun();
  renderRunsList();
  renderAttackMap();
  renderActiveAttack();
}

// ---------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------

function connectWebSocket() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/ws`);
  setWsStatus("warn", "WS CONNECTING");
  ws.onopen = () => setWsStatus("ok", "WS LIVE");
  ws.onclose = () => {
    setWsStatus("crit", "WS RECONNECTING");
    setTimeout(connectWebSocket, 2000);
  };
  ws.onerror = () => setWsStatus("crit", "WS ERROR");
  ws.onmessage = (msg) => {
    try {
      const m = JSON.parse(msg.data);
      if (m.kind === "hello" && Array.isArray(m.snapshot)) {
        STATE.events = m.snapshot.slice(-1000);
        renderEventStream();
      } else if (m.kind === "event" && m.event) {
        ingestEvent(m.event);
      }
    } catch (e) {
      console.error("ws parse", e);
    }
  };
}

function setWsStatus(level, text) {
  const pill = document.getElementById("ws-pill");
  pill.classList.remove("ok", "warn", "crit");
  pill.classList.add(level);
  pill.innerHTML = `<span class="dot"></span> ${text}`;
}

function ingestEvent(evt) {
  STATE.events.push(evt);
  if (STATE.events.length > 2000) STATE.events.shift();
  STATE.ingestBucket.count += 1;

  if (!STATE.paused) appendStreamRow(evt);
  // KPIs/charts refreshed off the periodic poll to avoid jitter on every event.
}

function updateIngestRate() {
  const now = Math.floor(Date.now() / 1000);
  if (now !== STATE.ingestBucket.ts) {
    STATE.ingestRate = STATE.ingestBucket.count;
    STATE.ingestBucket = { ts: now, count: 0 };
    document.getElementById("ingest-rate").textContent = `ingest ${STATE.ingestRate} ev/s`;
    const stats = document.getElementById("stream-stats");
    if (stats) stats.textContent = `${STATE.events.length} events · ${STATE.ingestRate}/s`;
  }
}

// ---------------------------------------------------------------------
// Charts
// ---------------------------------------------------------------------

function initCharts() {
  Chart.defaults.color = "#8a93a3";
  Chart.defaults.borderColor = "#1c2330";
  Chart.defaults.font.family = "ui-monospace, Menlo, Consolas, monospace";
  Chart.defaults.font.size = 11;

  charts.timeseries = new Chart(document.getElementById("chart-timeseries"), {
    type: "bar",
    data: { labels: [], datasets: [] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 250 },
      plugins: { legend: { position: "bottom", labels: { boxWidth: 10 } } },
      scales: {
        x: { stacked: true, grid: { color: "#161c25" } },
        y: { stacked: true, grid: { color: "#161c25" }, beginAtZero: true },
      },
    },
  });

  charts.types = new Chart(document.getElementById("chart-types"), {
    type: "bar",
    data: { labels: [], datasets: [] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: "y",
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: "#161c25" }, beginAtZero: true },
        y: { grid: { display: false } },
      },
    },
  });

  charts.severity = new Chart(document.getElementById("chart-severity"), {
    type: "doughnut",
    data: { labels: [], datasets: [] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: "62%",
      plugins: { legend: { position: "right", labels: { boxWidth: 10 } } },
    },
  });

  charts.collectors = new Chart(document.getElementById("chart-collectors"), {
    type: "bar",
    data: { labels: [], datasets: [] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false } },
        y: { grid: { color: "#161c25" }, beginAtZero: true },
      },
    },
  });
}

// ---------------------------------------------------------------------
// Renderers
// ---------------------------------------------------------------------

function renderAll() {
  renderKPIs();
  renderTimeseries();
  renderTypes();
  renderSeverity();
  renderCollectors();
  renderTopTables();
  renderActiveRun();
  renderRunsList();
  renderEventStream();
  renderAttackMap();
  renderActiveAttack();
}

function renderKPIs() {
  const t = (STATE.stats && STATE.stats.totals) || {};
  document.getElementById("kpi-total").textContent = (t.events ?? 0).toLocaleString();
  document.getElementById("kpi-critical").textContent = t.critical ?? 0;
  document.getElementById("kpi-high").textContent = t.high ?? 0;
  document.getElementById("kpi-medium").textContent = t.medium ?? 0;
  document.getElementById("kpi-hosts").textContent = t.hosts ?? 0;
  document.getElementById("kpi-runs").textContent = t.runs ?? 0;
}

function renderTimeseries() {
  const series = (STATE.stats && STATE.stats.timeseries) || [];
  const labels = series.map((b) => b.bucket.substring(11));
  const datasets = SEVERITY_ORDER.map((sev) => ({
    label: sev,
    data: series.map((b) => b[sev] || 0),
    backgroundColor: SEVERITY_COLOR[sev],
    borderColor: SEVERITY_COLOR[sev],
    borderWidth: 0,
    stack: "sev",
    barThickness: 12,
  }));
  charts.timeseries.data.labels = labels;
  charts.timeseries.data.datasets = datasets;
  charts.timeseries.update();
}

function renderTypes() {
  const by = (STATE.stats && STATE.stats.by_type) || {};
  const entries = Object.entries(by).sort((a, b) => b[1] - a[1]).slice(0, 10);
  charts.types.data.labels = entries.map((e) => e[0]);
  charts.types.data.datasets = [{
    data: entries.map((e) => e[1]),
    backgroundColor: "#1ba9f5",
    borderColor: "#1ba9f5",
  }];
  charts.types.update();
}

function renderSeverity() {
  const by = (STATE.stats && STATE.stats.by_severity) || {};
  const labels = SEVERITY_ORDER.filter((s) => by[s]);
  const data = labels.map((s) => by[s]);
  charts.severity.data.labels = labels;
  charts.severity.data.datasets = [{
    data,
    backgroundColor: labels.map((s) => SEVERITY_COLOR[s]),
    borderColor: "#0b0e13",
    borderWidth: 2,
  }];
  charts.severity.update();
}

function renderCollectors() {
  const by = (STATE.stats && STATE.stats.by_collector) || {};
  const entries = Object.entries(by).sort((a, b) => b[1] - a[1]);
  charts.collectors.data.labels = entries.map((e) => e[0]);
  charts.collectors.data.datasets = [{
    data: entries.map((e) => e[1]),
    backgroundColor: "#00bfb3",
    borderColor: "#00bfb3",
  }];
  charts.collectors.update();
}

function renderTopTables() {
  const paths = (STATE.stats && STATE.stats.top_paths) || [];
  const users = (STATE.stats && STATE.stats.top_users) || [];
  const pathBody = document.querySelector("#tbl-paths tbody");
  const userBody = document.querySelector("#tbl-users tbody");
  pathBody.innerHTML = paths.length
    ? paths.map((r) => `<tr><td>${escapeHtml(r.path)}</td><td class="num">${r.count}</td></tr>`).join("")
    : `<tr><td colspan="2" class="empty-hint">no path mutations observed yet</td></tr>`;
  userBody.innerHTML = users.length
    ? users.map((r) => `<tr><td>${escapeHtml(r.account)}</td><td class="num">${r.count}</td></tr>`).join("")
    : `<tr><td colspan="2" class="empty-hint">no auth events observed yet</td></tr>`;
}

function renderActiveRun() {
  const run = STATE.activeRun;
  const meta = document.getElementById("active-run-meta");
  const summary = document.getElementById("active-run-summary");
  const footerHost = document.getElementById("footer-host");
  if (!run) {
    meta.textContent = "no run loaded";
    summary.innerHTML = `<div class="empty-hint">Run a scenario via <code>python -m runner.executor scenarios/&lt;file&gt;.json</code> to populate this panel.</div>`;
    footerHost.textContent = "--";
    return;
  }
  footerHost.textContent = `run ${run.run_id} · ${run.container || "n/a"}`;
  meta.textContent = `${run.scenario_id || "?"} · ${run.status || "?"}`;

  const meta_dl = `
    <dl class="run-meta-list">
      <dt>RUN_ID</dt><dd>${escapeHtml(run.run_id)}</dd>
      <dt>SCENARIO</dt><dd>${escapeHtml(run.scenario_name || run.scenario_id || "?")}</dd>
      <dt>CONTAINER</dt><dd>${escapeHtml(run.container || "?")}</dd>
      <dt>STARTED</dt><dd>${escapeHtml(run.started_at || "?")}</dd>
      <dt>COMPLETED</dt><dd>${escapeHtml(run.completed_at || "?")}</dd>
      <dt>STEPS</dt><dd>${(run.steps || []).length} planned</dd>
      <dt>STATUS</dt><dd>${escapeHtml(run.status || "?")}</dd>
    </dl>`;

  const cov = run.telemetry_coverage || {};
  const covRows = Object.entries(cov).map(([k, v]) => {
    const ok = (v.produced_by || []).length > 0;
    const cls = ok ? "ok" : "gap";
    const label = ok ? "covered" : "gap";
    const producers = (v.produced_by || []).join(", ") || "—";
    return `<div class="coverage-row ${cls}">
      <span class="pill">${label}</span>
      <span style="flex:1">${escapeHtml(k)}</span>
      <span style="color:var(--text-mute)">${escapeHtml(producers)}</span>
    </div>`;
  }).join("");

  summary.innerHTML = `
    <div>${meta_dl}</div>
    <div>
      <div class="panel-sub" style="margin-bottom:6px;letter-spacing:0.16em;color:var(--text-mute);font-size:10px">TELEMETRY COVERAGE</div>
      <div class="coverage-list">${covRows || '<div class="empty-hint">no telemetry expectations recorded</div>'}</div>
    </div>`;
}

function renderRunsList() {
  const tbody = document.querySelector("#tbl-runs tbody");
  if (!STATE.runs.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="empty-hint">no scenario runs in reports/</td></tr>`;
    return;
  }
  tbody.innerHTML = STATE.runs.map((r) => {
    const sel = r.run_id === STATE.selectedRunId ? "background:#162028;" : "";
    return `<tr data-run="${escapeHtml(r.run_id)}" style="cursor:pointer;${sel}">
      <td>${escapeHtml(r.run_id)}</td>
      <td>${escapeHtml(r.scenario_id || "?")}</td>
      <td><span class="sev-cell ${statusToClass(r.status)}">${escapeHtml(r.status || "?")}</span></td>
      <td>${escapeHtml(r.started_at || "?")}</td>
    </tr>`;
  }).join("");
  tbody.querySelectorAll("tr").forEach((tr) => {
    tr.addEventListener("click", () => {
      STATE.selectedRunId = tr.dataset.run;
      renderRunsList();
      renderRunDetail();
    });
  });
  renderRunDetail();
}

function statusToClass(status) {
  if (!status) return "sev-info";
  if (status === "completed") return "sev-low";
  if (status === "completed_with_failures") return "sev-high";
  if (status === "dry_run") return "sev-info";
  return "sev-medium";
}

function renderRunDetail() {
  const run = STATE.runs.find((r) => r.run_id === STATE.selectedRunId);
  const meta = document.getElementById("run-detail-meta");
  const body = document.getElementById("run-detail");
  if (!run) {
    meta.textContent = "select a run";
    body.innerHTML = `<div class="empty-hint">No run selected.</div>`;
    return;
  }
  meta.textContent = `${run.scenario_id || "?"} · ${run.status || "?"}`;
  const steps = (run.steps || []).map((s) => `
    <div class="step ${s.status || "ok"}">
      <span class="marker"></span>
      <span class="step-id">${escapeHtml(s.step_id || "?")}</span>
      <span class="behavior">${escapeHtml(s.behavior || "?")}</span>
      <span class="status">${escapeHtml(s.status || "?")}</span>
      <span class="cmd">${escapeHtml(s.command || "")}</span>
    </div>`).join("");

  const gaps = run.coverage_gaps || [];
  const gapsHtml = gaps.length
    ? gaps.map((g) => `<div class="coverage-row gap"><span class="pill">gap</span>${escapeHtml(g)}</div>`).join("")
    : `<div class="coverage-row ok"><span class="pill">ok</span>full telemetry coverage</div>`;

  body.innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:12px">
      <div>
        <div class="panel-sub" style="font-size:10px;letter-spacing:0.18em;color:var(--text-mute);margin-bottom:6px">METADATA</div>
        <dl class="run-meta-list">
          <dt>RUN_ID</dt><dd>${escapeHtml(run.run_id)}</dd>
          <dt>BEHAVIORS</dt><dd>${escapeHtml((run.behaviors_planned || []).join(" → "))}</dd>
          <dt>STARTED</dt><dd>${escapeHtml(run.started_at || "?")}</dd>
          <dt>COMPLETED</dt><dd>${escapeHtml(run.completed_at || "?")}</dd>
          <dt>FAILURES</dt><dd>${(run.step_failures || []).length}</dd>
        </dl>
      </div>
      <div>
        <div class="panel-sub" style="font-size:10px;letter-spacing:0.18em;color:var(--text-mute);margin-bottom:6px">COVERAGE GAPS</div>
        <div class="coverage-list">${gapsHtml}</div>
      </div>
    </div>

    <div class="brief-toolbar">
      <div class="brief-toolbar-left">
        <span class="panel-sub">AI INTELLIGENCE</span>
        <select id="brief-model" class="brief-model">
          <option value="">gemini-3-pro-preview (default)</option>
          <option value="gemini-3-pro-preview">gemini-3-pro-preview</option>
          <option value="gemini-pro-latest">gemini-pro-latest</option>
          <option value="gemini-2.5-pro">gemini-2.5-pro</option>
          <option value="gemini-2.5-flash">gemini-2.5-flash</option>
          <option value="gemini-flash-latest">gemini-flash-latest</option>
        </select>
      </div>
      <div class="brief-toolbar-right">
        <button id="brief-generate" class="btn btn-primary">GENERATE BRIEF</button>
        <button id="brief-regenerate" class="btn">REGEN</button>
      </div>
    </div>
    <div id="brief-panel" class="brief-panel"></div>

    <div class="panel-sub" style="font-size:10px;letter-spacing:0.18em;color:var(--text-mute);margin:12px 0 6px 0">EXECUTION STEPS</div>
    <div class="step-list">${steps || '<div class="empty-hint">no steps recorded</div>'}</div>`;

  document.getElementById("brief-generate").addEventListener("click", () => fetchBrief(run.run_id, false));
  document.getElementById("brief-regenerate").addEventListener("click", () => fetchBrief(run.run_id, true));
  // auto-load any cached brief
  loadCachedBrief(run.run_id);
}

async function loadCachedBrief(runId) {
  try {
    const r = await fetch(`/api/runs/${encodeURIComponent(runId)}/brief`);
    if (r.ok) {
      const data = await r.json();
      renderBrief(data, true);
    }
  } catch (_) {
    /* no cache; expected */
  }
}

async function fetchBrief(runId, regenerate) {
  const panel = document.getElementById("brief-panel");
  if (!panel) return;
  const sel = document.getElementById("brief-model");
  const model = sel ? sel.value : "";
  panel.innerHTML = `<div class="brief-loading">
    <span class="spinner"></span>
    <span>Querying ${escapeHtml(model || "gemini-3-pro-preview")} … building incident brief from ${(STATE.events || []).length} events</span>
  </div>`;
  try {
    const params = new URLSearchParams();
    if (model) params.set("model", model);
    if (regenerate) params.set("regenerate", "true");
    const url = `/api/runs/${encodeURIComponent(runId)}/brief${params.toString() ? "?" + params.toString() : ""}`;
    const r = await fetch(url, { method: "POST" });
    const data = await r.json();
    if (!r.ok) {
      panel.innerHTML = `<div class="brief-error">⚠ ${escapeHtml(data.detail || r.statusText)}</div>`;
      return;
    }
    renderBrief(data, false);
  } catch (e) {
    panel.innerHTML = `<div class="brief-error">⚠ ${escapeHtml(e.message || String(e))}</div>`;
  }
}

function renderBrief(data, fromCache) {
  const panel = document.getElementById("brief-panel");
  if (!panel) return;
  const md = data.brief_markdown || "";
  let html = "";
  try {
    html = window.DOMPurify.sanitize(window.marked.parse(md));
  } catch (e) {
    html = `<pre>${escapeHtml(md)}</pre>`;
  }
  const meta = [
    `<span class="meta-key">model</span> ${escapeHtml(data.model || "?")}`,
    `<span class="meta-key">generated</span> ${escapeHtml((data.generated_at || "").substring(0, 19).replace("T", " "))}`,
    data.prompt_tokens != null ? `<span class="meta-key">prompt_tok</span> ${data.prompt_tokens}` : "",
    data.completion_tokens != null ? `<span class="meta-key">resp_tok</span> ${data.completion_tokens}` : "",
    fromCache ? `<span class="meta-key cached">cached</span>` : `<span class="meta-key fresh">live</span>`,
  ].filter(Boolean).join("  ·  ");
  panel.innerHTML = `
    <div class="brief-meta">${meta}</div>
    <div class="brief-markdown">${html}</div>`;
}

function renderEventStream() {
  const tbody = document.querySelector("#tbl-events tbody");
  const filtered = STATE.events.filter(matchesFilters);
  tbody.innerHTML = filtered.slice(-500).reverse().map((evt) => rowHtml(evt)).join("");
  document.getElementById("stream-stats").textContent = `${filtered.length} events · ${STATE.ingestRate}/s`;
}

function appendStreamRow(evt) {
  if (!matchesFilters(evt)) return;
  const tbody = document.querySelector("#tbl-events tbody");
  if (!tbody) return;
  const tr = document.createElement("tr");
  tr.className = "flash";
  tr.innerHTML = innerRow(evt);
  tbody.insertBefore(tr, tbody.firstChild);
  while (tbody.children.length > 500) tbody.removeChild(tbody.lastChild);
}

function rowHtml(evt) {
  return `<tr>${innerRow(evt)}</tr>`;
}
function innerRow(evt) {
  const sev = (evt.severity || "info").toLowerCase();
  const ts = (evt.timestamp || "").replace("T", " ").substring(0, 19);
  return `
    <td class="ts">${escapeHtml(ts)}</td>
    <td><span class="sev-cell sev-${sev}">${sev}</span></td>
    <td>${escapeHtml(evt.host || "")}</td>
    <td>${escapeHtml(evt.collector || "")}</td>
    <td>${escapeHtml(evt.event_type || "")}</td>
    <td class="det">${escapeHtml(formatDetails(evt.details))}</td>
  `;
}

function formatDetails(d) {
  if (!d || typeof d !== "object") return "";
  return Object.entries(d).map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`).join("  ");
}

function matchesFilters(evt) {
  const sev = document.getElementById("f-severity")?.value || "";
  const type = document.getElementById("f-type")?.value || "";
  const host = document.getElementById("f-host")?.value || "";
  const q = (document.getElementById("f-q")?.value || "").toLowerCase();
  if (sev && (evt.severity || "").toLowerCase() !== sev) return false;
  if (type && !(evt.event_type || "").includes(type)) return false;
  if (host && !(evt.host || "").includes(host)) return false;
  if (q) {
    const hay = JSON.stringify(evt).toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}

function renderAttackMap() {
  const grid = document.getElementById("attack-grid");
  const active = new Set((STATE.activeRun?.behaviors_planned) || []);
  grid.innerHTML = Object.entries(STATE.attackMap).map(([behavior, techniques]) => {
    const cls = active.has(behavior) ? "attack-cell active" : "attack-cell";
    const items = techniques.map((t) => `<li><span class="tid">${escapeHtml(t.id)}</span>${escapeHtml(t.name)}</li>`).join("");
    return `<div class="${cls}"><h4>${escapeHtml(behavior)}</h4><ul>${items}</ul></div>`;
  }).join("");
}

function renderActiveAttack() {
  const meta = document.getElementById("active-attack-meta");
  const list = document.getElementById("active-attack-list");
  const techniques = (STATE.stats && STATE.stats.attack_techniques) || [];
  if (!STATE.activeRun) {
    meta.textContent = "no run loaded";
    list.innerHTML = `<div class="empty-hint">no scenario run yet</div>`;
    return;
  }
  meta.textContent = `${STATE.activeRun.scenario_id || "?"} · ${techniques.length} techniques`;
  if (!techniques.length) {
    list.innerHTML = `<div class="empty-hint">scenario behaviors did not map to any ATT&CK techniques</div>`;
    return;
  }
  list.innerHTML = techniques.map((t) => `
    <div class="active-attack-row">
      <span class="tid">${escapeHtml(t.id)}</span>
      <span style="flex:1">${escapeHtml(t.name)}</span>
      <span class="behavior">${escapeHtml(t.behavior || "")}</span>
    </div>`).join("");
}

// ---------------------------------------------------------------------
// utils
// ---------------------------------------------------------------------
function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
