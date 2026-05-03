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
  renderKillChain();
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

  // Kill chain uses custom canvas rendering, no Chart.js instance needed

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
  renderKillChain();
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

// ============ UNIFIED KILL CHAIN — Pols (2017) 18-Tactic 3-Phase Model ============
// Visual: Stellar Cyber style — solid base ring, active tactic arcs glow on top
// Neon palette: IN=#00ff9f  THROUGH=#00bfff  OUT=#ff2d55

const UKC_ZONES = [
  {
    id: "in", label: "IN", subtitle: "Initial Foothold", color: "#00ff9f",
    ring: [
      { id: "reconn",   label: "Reconnaissance",  tactic: "TA0043", behaviors: [] },
      { id: "resdev",   label: "Resource Dev",     tactic: "TA0042", behaviors: [] },
      { id: "delivery", label: "Delivery",         tactic: "TA0001", behaviors: ["auth_anomalies"] },
      { id: "social",   label: "Social Eng",       tactic: "TA0001", behaviors: ["auth_anomalies"] },
      { id: "exploit",  label: "Exploitation",     tactic: "TA0002", behaviors: ["remote_execution_artifacts"] },
      { id: "persist",  label: "Persistence",      tactic: "TA0003", behaviors: ["persistence_path_changes"] },
      { id: "defev",    label: "Defense Evasion",  tactic: "TA0005", behaviors: ["anti_forensics"] },
      { id: "c2in",     label: "C2",               tactic: "TA0011", behaviors: [] },
    ],
    flow: ["Reconnaissance", "Resource Dev", "C2"],
  },
  {
    id: "through", label: "THROUGH", subtitle: "Network Propagation", color: "#00bfff",
    ring: [
      { id: "pivot",   label: "Pivoting",          tactic: "TA0008", behaviors: [] },
      { id: "disc",    label: "Discovery",         tactic: "TA0007", behaviors: [] },
      { id: "privesc", label: "Priv Escalation",   tactic: "TA0004", behaviors: [] },
      { id: "exec",    label: "Execution",         tactic: "TA0002", behaviors: ["remote_execution_artifacts"] },
      { id: "credacc", label: "Cred Access",       tactic: "TA0006", behaviors: ["auth_anomalies"] },
      { id: "latmov",  label: "Lateral Movement",  tactic: "TA0008", behaviors: [] },
    ],
    flow: ["Pivoting", "Discovery", "Lateral Movement"],
  },
  {
    id: "out", label: "OUT", subtitle: "Actions on Objectives", color: "#ff2d55",
    ring: [
      { id: "collect", label: "Collection",        tactic: "TA0009", behaviors: ["file_tamper", "staging"] },
      { id: "exfil",   label: "Exfiltration",      tactic: "TA0010", behaviors: ["staging", "cleanup"] },
      { id: "impact",  label: "Impact",            tactic: "TA0040", behaviors: ["file_tamper", "anti_forensics"] },
      { id: "obj",     label: "Objectives",        tactic: "TA0040", behaviors: ["file_tamper"] },
    ],
    flow: ["Collection", "Objectives"],
  },
];

function renderKillChain() {
  const container = document.getElementById("ukc-zones");
  const summaryEl = document.getElementById("ukc-summary");
  if (!container) return;

  const stats = STATE.stats || {};
  const techniques = stats.attack_techniques || [];

  let totalActive = 0, totalTactics = 0, totalTechniques = 0;
  const zoneCounts = {};

  const scoredZones = UKC_ZONES.map((zone) => {
    zoneCounts[zone.id] = 0;
    const ring = zone.ring.map((tactic) => {
      const matched = [];
      tactic.behaviors.forEach((b) => {
        techniques.filter((t) => t.behavior === b).forEach((t) => matched.push(t));
      });
      const active = matched.length > 0;
      if (active) { zoneCounts[zone.id]++; totalActive++; }
      totalTactics++;
      totalTechniques += matched.length;
      return { ...tactic, count: matched.length, techniques: matched, active };
    });
    return { zone, ring };
  });

  // -----------------------------------------------------------------------
  // Geometry — stroke-arc method (matches Stellar Cyber ring style)
  // Rm = ring mid-radius (stroke center), band = stroke-width
  // The full ring is a stroked circle; active arcs are drawn on top
  // -----------------------------------------------------------------------
  const VW = 820, VH = 315;
  const Rm = 92;          // mid-radius of the ring band
  const band = 40;        // ring band thickness (stroke-width)
  const Ro = Rm + band/2; // outer edge = 112
  const Ri = Rm - band/2; // inner edge = 72
  const ri = Ri - 8;      // inner center circle radius = 64
  const CY = 147;
  const centers = [{ x: 148, id: "in" }, { x: 408, id: "through" }, { x: 668, id: "out" }];
  const GAP = 2.5;        // degrees gap between segments
  const LABEL_R = Ro + 16; // radius of tactic labels

  function pt(cx, r, deg) {
    const a = (deg - 90) * Math.PI / 180;
    return [cx + r * Math.cos(a), CY + r * Math.sin(a)];
  }
  const f = (n) => n.toFixed(2);

  // Arc path for stroke-based ring segment
  function arcD(cx, r, a1, a2) {
    const [sx, sy] = pt(cx, r, a1);
    const [ex, ey] = pt(cx, r, a2);
    const large = (a2 - a1) > 180 ? 1 : 0;
    // avoid degenerate full-circle arc (SVG ignores start==end)
    return `M ${f(sx)} ${f(sy)} A ${r} ${r} 0 ${large} 1 ${f(ex)} ${f(ey)}`;
  }

  let svgDefs = "", svgBridges = "", svgContent = "";

  scoredZones.forEach(({ zone, ring }, zi) => {
    const cx = centers[zi].x;
    const col = zone.color;
    const n = ring.length;
    const segDeg = 360 / n;
    const zoneActive = zoneCounts[zone.id] > 0;

    // Glow filters
    svgDefs += `
      <filter id="glow-${zone.id}" x="-60%" y="-60%" width="220%" height="220%">
        <feGaussianBlur stdDeviation="7" result="b"/>
        <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
      </filter>
      <filter id="glowsm-${zone.id}" x="-30%" y="-30%" width="160%" height="160%">
        <feGaussianBlur stdDeviation="3.5" result="b"/>
        <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
      </filter>`;

    // ── 1. Base ring — always visible dim outline of the full loop ──
    svgContent += `<circle cx="${cx}" cy="${CY}" r="${Rm}"
      fill="none" stroke="${col}" stroke-width="${band}"
      opacity="${zoneActive ? 0.14 : 0.10}"/>`;

    // ── 2. Per-segment: active arc + tick dividers + labels ──
    ring.forEach((tactic, i) => {
      const a1 = i * segDeg + GAP;
      const a2 = (i + 1) * segDeg - GAP;
      const aMid = (a1 + a2) / 2;

      // Active arc drawn as thick stroke on top of base ring
      if (tactic.active) {
        svgContent += `<path d="${arcD(cx, Rm, a1, a2)}"
          fill="none" stroke="${col}" stroke-width="${band}"
          stroke-linecap="butt" opacity="0.92"
          filter="url(#glowsm-${zone.id})"/>`;
      }

      // Thin dark tick at segment boundary (gives chevron-like divisions)
      const [tx1, ty1] = pt(cx, Ri + 1, i * segDeg);
      const [tx2, ty2] = pt(cx, Ro - 1, i * segDeg);
      svgContent += `<line x1="${f(tx1)}" y1="${f(ty1)}" x2="${f(tx2)}" y2="${f(ty2)}"
        stroke="#0a0d11" stroke-width="2" opacity="0.85"/>`;

      // Tactic label outside the ring
      const [lx, ly] = pt(cx, LABEL_R, aMid);
      // Rotate so text runs tangentially (clockwise) — flip bottom half
      const rot = aMid <= 180 ? aMid - 90 : aMid + 90;
      svgContent += `<text x="${f(lx)}" y="${f(ly)}"
        text-anchor="middle" dominant-baseline="central"
        transform="rotate(${f(rot)},${f(lx)},${f(ly)})"
        font-family="monospace" font-size="6.8" font-weight="${tactic.active ? 700 : 400}"
        fill="${col}" opacity="${tactic.active ? 1 : 0.42}"
        letter-spacing="0.06em">${tactic.label.toUpperCase()}</text>`;
    });

    // ── 3. Inner center circle ──
    svgContent += `<circle cx="${cx}" cy="${CY}" r="${ri}"
      fill="${zoneActive ? col : "#0b0f15"}" stroke="${col}"
      stroke-width="${zoneActive ? 2 : 0.8}"
      opacity="${zoneActive ? 0.94 : 0.35}"
      ${zoneActive ? `filter="url(#glow-${zone.id})"` : ""}/>`;

    // Zone label in center
    const tc = zoneActive ? "#060809" : col;
    const fz = zone.id === "through" ? 11 : 14;
    svgContent += `<text x="${cx}" y="${CY - 8}" text-anchor="middle"
      font-family="monospace" font-size="${fz}" font-weight="900"
      fill="${tc}" letter-spacing="0.1em">${zone.label}</text>`;
    svgContent += `<text x="${cx}" y="${CY + 7}" text-anchor="middle"
      font-family="monospace" font-size="4.8" font-weight="600"
      fill="${tc}" opacity="0.72" letter-spacing="0.14em">${zone.subtitle.toUpperCase()}</text>`;
    if (zoneActive) {
      svgContent += `<text x="${cx}" y="${CY + 19}" text-anchor="middle"
        font-family="monospace" font-size="5" font-weight="700"
        fill="${tc}" opacity="0.65">${zoneCounts[zone.id]}/${ring.length} ACTIVE</text>`;
    }
  });

  // ── Bridge connectors — bezier tubes along ring bottoms ──
  // Drawn into svgBridges so rings render ON TOP and naturally cap the tube endpoints.
  // BY = ring-band center at the bottom; control points dip below so the tube
  // emerges visibly beneath each ring's outer edge (CY + Ro ≈ 259).
  [[0,1],[1,2]].forEach(([a, b]) => {
    const cx_a = centers[a].x, cx_b = centers[b].x;
    const c1 = UKC_ZONES[a].color, c2 = UKC_ZONES[b].color;
    const gid = `brg${a}${b}`;
    const BY = CY + Rm;                       // 239 — ring-band centre at bottom
    const droop = 42;                         // curve dips this many px below BY
    const cp = (cx_b - cx_a) * 0.34;         // bezier control-point x offset
    const bh = 10;                            // tube half-height

    svgDefs += `<linearGradient id="${gid}" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="${c1}" stop-opacity="0.72"/>
      <stop offset="100%" stop-color="${c2}" stop-opacity="0.72"/>
    </linearGradient>`;

    // Centre spine of the tube (cubic bezier)
    // Horizontal tangent at both ends matches the ring's tangent at its bottom-most point.
    const spineTop  = `M ${f(cx_a)} ${f(BY-bh)} C ${f(cx_a+cp)} ${f(BY-bh+droop)}, ${f(cx_b-cp)} ${f(BY-bh+droop)}, ${f(cx_b)} ${f(BY-bh)}`;
    const spineBot  = `C ${f(cx_b-cp)} ${f(BY+bh+droop)}, ${f(cx_a+cp)} ${f(BY+bh+droop)}, ${f(cx_a)} ${f(BY+bh)}`;
    svgBridges += `<path d="${spineTop} L ${f(cx_b)} ${f(BY+bh)} ${spineBot} Z"
      fill="url(#${gid})" opacity="0.62"/>`;

    // Chevron arrow at the lowest midpoint of the droop (t=0.5 → y = BY + droop*0.75)
    const mx  = (cx_a + cx_b) / 2;
    const mY  = BY + droop * 0.75;
    svgBridges += `<polygon points="${f(mx+9)},${f(mY)} ${f(mx-3)},${f(mY-6)} ${f(mx-3)},${f(mY+6)}"
      fill="url(#${gid})" opacity="0.95"/>`;
  });

  const svgHTML = `<svg class="ukc-loops-svg" viewBox="0 0 ${VW} ${VH}" preserveAspectRatio="xMidYMid meet">
    <defs>${svgDefs}</defs>${svgBridges}${svgContent}</svg>`;

  // ── Bottom chevron flow bar ──
  const allFlow = scoredZones.flatMap(({ zone }) =>
    zone.flow.map((label) => ({ label, color: zone.color, id: zone.id }))
  );
  const flowHTML = allFlow.map((item, i) => {
    const isLast = i === allFlow.length - 1;
    const prevZone = i > 0 ? allFlow[i-1].id : null;
    const bc = prevZone && prevZone !== item.id ? " ukc-flow-zone-break" : "";
    return `<div class="ukc-flow-item${bc}" style="--fc:${item.color}" data-cycle="${item.id}">
      <span class="ukc-flow-label">${item.label}</span>
      ${!isLast ? `<span class="ukc-flow-arrow">&#x276F;</span>` : ""}
    </div>`;
  }).join("");

  container.innerHTML = `<div class="ukc-diagram">
    <div class="ukc-loops">${svgHTML}</div>
    <div class="ukc-flow-bar">${flowHTML}</div>
  </div>`;

  if (summaryEl) {
    const pct = Math.round((totalActive / totalTactics) * 100);
    summaryEl.innerHTML =
      `<span class="ukc-stat"><b>${totalTechniques}</b> techniques</span>` +
      `<span class="ukc-sep">&middot;</span>` +
      `<span class="ukc-stat"><b>${totalActive}</b>/${totalTactics} tactics active</span>` +
      `<span class="ukc-sep">&middot;</span>` +
      `<span class="ukc-stat"><b>${pct}%</b> UKC coverage</span>` +
      `<span class="ukc-sep">|</span>` +
      `<span class="ukc-stat zone-in"><b>${zoneCounts.in||0}/8</b> IN</span>` +
      `<span class="ukc-stat zone-through"><b>${zoneCounts.through||0}/6</b> THROUGH</span>` +
      `<span class="ukc-stat zone-out"><b>${zoneCounts.out||0}/4</b> OUT</span>` +
      `<span class="ukc-sep">&middot;</span>` +
      `<span class="ukc-stat" style="opacity:0.38;font-size:9px">Pols (2017) §§3.2-3.4</span>`;
  }
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
          <option value="">gemini-2.5-flash (default)</option>
          <option value="gemini-2.5-flash">gemini-2.5-flash</option>
          <option value="gemini-2.5-pro">gemini-2.5-pro</option>
          <option value="gemini-2.0-flash">gemini-2.0-flash</option>
          <option value="gemini-1.5-pro">gemini-1.5-pro</option>
          <option value="gemini-1.5-flash">gemini-1.5-flash</option>
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
    <span>Querying ${escapeHtml(model || "gemini-2.5-flash")} … building incident brief from ${(STATE.events || []).length} events</span>
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
