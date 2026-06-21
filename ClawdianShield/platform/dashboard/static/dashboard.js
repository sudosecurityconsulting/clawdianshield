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
  benchmarks: [],
  selectedBenchmarkId: null,
  aiAttacks: [],
  aiStats: {},
};

const charts = {};

// ---------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", async () => {
  bindTabs();
  bindFilters();
  startClock();
  await Promise.all([loadStats(), loadRuns(), loadAttackMap(), loadBenchmarks(), loadAiAttacks()]);
  initCharts();
  renderAll();
  connectWebSocket();
  setInterval(refreshStats, 5000);
  setInterval(updateIngestRate, 1000);
  setInterval(async () => { await loadBenchmarks(); renderBenchmarkList(); }, 15000);
  setInterval(async () => { await loadAiAttacks(); renderAiAttacks(); }, 20000);
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

async function loadBenchmarks() {
  const r = await fetch("/api/benchmarks");
  STATE.benchmarks = await r.json();
}

async function loadAiAttacks() {
  const [r1, r2] = await Promise.all([
    fetch("/api/ai-attacks"),
    fetch("/api/ai-attacks/stats"),
  ]);
  STATE.aiAttacks = await r1.json();
  STATE.aiStats = await r2.json();
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
  renderBenchmarkList();
  renderAiAttacks();
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

const RC_PHASES = [
  { id: "reconn",   label: "Reconnaissance",       len: 35,  zone: "in" },
  { id: "resdev",   label: "Resource Development", len: 45,  zone: "in" },
  { id: "delivery", label: "Delivery",             len: 40,  zone: "in" },
  { id: "social",   label: "Social Engineering",   len: 55,  zone: "in" },
  { id: "exploit",  label: "Exploitation",         len: 45,  zone: "in" },
  { id: "persist",  label: "Persistence",          len: 45,  zone: "in" },
  { id: "defev",    label: "Defense Evasion",      len: 50,  zone: "in" },
  { id: "c2in",     label: "Command & Control",    len: 55,  zone: "in" },
  { id: "pivot",    label: "Pivoting",             len: 50,  zone: "through" },
  { id: "disc",     label: "Discovery",            len: 50,  zone: "through" },
  { id: "privesc",  label: "Privilege Escalation", len: 55,  zone: "through" },
  { id: "exec",     label: "Execution",            len: 45,  zone: "through" },
  { id: "credacc",  label: "Credential Access",    len: 50,  zone: "through" },
  { id: "latmov",   label: "Lateral Movement",     len: 55,  zone: "through" },
  { id: "collect",  label: "Collection",           len: 55,  zone: "out" },
  { id: "exfil",    label: "Exfiltration",         len: 110, zone: "out" },
  { id: "impact",   label: "Impact",               len: 110, zone: "out" },
  { id: "obj",      label: "Objectives",           len: 50,  zone: "out" }
];

const PATH_D = `M 20 270 L 100 270 C 170 270, 240 230, 240 140 A 90 90 0 1 0 60 140 C 60 230, 130 270, 210 270 L 360 270 C 430 270, 500 230, 500 140 A 90 90 0 1 0 320 140 C 320 230, 390 270, 470 270 L 620 270 C 690 270, 760 230, 760 140 A 90 90 0 1 0 580 140 C 580 230, 650 270, 730 270 L 800 270`;

let pathLenComputed = false;
let pathTotalLen = 1000;
function precomputePath() {
  if (pathLenComputed) return;
  const tempPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
  tempPath.setAttribute("d", PATH_D);
  const svgTemp = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svgTemp.appendChild(tempPath);
  document.body.appendChild(svgTemp);
  pathTotalLen = tempPath.getTotalLength();
  
  let currentOffset = 0;
  RC_PHASES.forEach(phase => {
    phase.offset = currentOffset;
    const midPct = (currentOffset + phase.len / 2) / 1000;
    const pMid = tempPath.getPointAtLength(midPct * pathTotalLen);
    const p1 = tempPath.getPointAtLength((Math.max(0, midPct - 0.005)) * pathTotalLen);
    const p2 = tempPath.getPointAtLength((Math.min(1, midPct + 0.005)) * pathTotalLen);
    
    let angle = Math.atan2(p2.y - p1.y, p2.x - p1.x) * 180 / Math.PI;
    if (angle > 90 || angle < -90) angle += 180;
    
    phase.pMid = pMid;
    phase.angle = angle;

    const endPct = Math.min(0.999, (currentOffset + phase.len - 2) / 1000);
    phase.pEnd = tempPath.getPointAtLength(endPct * pathTotalLen);
    const pe1 = tempPath.getPointAtLength(Math.max(0, endPct - 0.004) * pathTotalLen);
    const pe2 = tempPath.getPointAtLength(Math.min(0.999, endPct + 0.004) * pathTotalLen);
    phase.angleEnd = Math.atan2(pe2.y - pe1.y, pe2.x - pe1.x) * 180 / Math.PI;

    currentOffset += phase.len;
  });
  
  document.body.removeChild(svgTemp);
  pathLenComputed = true;
}

let replayAnim = null;
let replayMode = false;
let replayProgress = 0;

function playUKCReplay() {
  if (replayAnim) cancelAnimationFrame(replayAnim);
  replayMode = true;
  replayProgress = 0;
  
  const duration = 7500; // 7.5 seconds for slow motion playback
  const start = performance.now();
  
  const frame = (now) => {
    let t = (now - start) / duration;
    if (t > 1) t = 1;
    
    // easeInOutQuad for dramatic slow motion effect
    const ease = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
    replayProgress = ease * 1000;
    
    renderKillChain();
    
    if (t < 1) {
      replayAnim = requestAnimationFrame(frame);
    } else {
      setTimeout(() => {
        replayMode = false;
        renderKillChain();
      }, 3000); // pause at the end for 3s
    }
  };
  
  replayAnim = requestAnimationFrame(frame);
}

const UKC_ZONES = [
  {
    id: "in", label: "IN", subtitle: "Initial Foothold", color: "#10b981",
    ring: [
      { id: "social",   label: "Social Engineering", tactic: "TA0001" },
      { id: "exploit",  label: "Exploitation",       tactic: "TA0002" },
      { id: "persist",  label: "Persistence",        tactic: "TA0003" },
      { id: "defev",    label: "Defense Evasion",    tactic: "TA0005" },
      { id: "c2in",     label: "Command & Control",  tactic: "TA0011" },
    ],
    flow: [
      { id: "reconn",   label: "Reconnaissance" },
      { id: "resdev",   label: "Resource Development" },
      { id: "delivery", label: "Delivery", isTransition: true },
    ],
  },
  {
    id: "through", label: "THROUGH", subtitle: "Network Propagation", color: "#f59e0b",
    ring: [
      { id: "exec",    label: "Execution",           tactic: "TA0002" },
      { id: "privesc", label: "Privilege Escalation",tactic: "TA0004" },
      { id: "latmov",  label: "Lateral Movement",    tactic: "TA0008" },
      { id: "credacc", label: "Credential Access",   tactic: "TA0006" },
    ],
    flow: [
      { id: "pivot",    label: "Pivoting", isTransition: true },
      { id: "disc",     label: "Discovery" },
    ],
  },
  {
    id: "out", label: "OUT", subtitle: "Actions on Objectives", color: "#ef4444",
    ring: [
      { id: "exfil",   label: "Exfiltration", tactic: "TA0010" },
      { id: "impact",  label: "Impact",       tactic: "TA0040" },
    ],
    flow: [
      { id: "collect",  label: "Collection" },
      { id: "obj",      label: "Objectives" },
    ],
  },
];

function renderKillChain() {
  const container = document.getElementById("ukc-zones");
  const summaryEl = document.getElementById("ukc-summary");
  if (!container) return;

  const run = STATE.activeRun || {};
  const score = run.score || {};
  const ukcMapping = score.unified_kill_chain_mapping || {};
  const activePhases = ukcMapping.ukc_phases_represented || [];
  const behaviorsExecuted = ukcMapping.behaviors_executed || [];

  // Detection state: did the sensors actually have eyes on this tactic, or did
  // it execute into a telemetry blind spot? run.telemetry_coverage maps each
  // expected telemetry type -> { expected, produced_by:[behaviors] }. A behavior
  // is "detected" if it produces at least one expected telemetry type that has
  // a producer; an executed behavior that produces nothing expected = a gap the
  // SOC would have missed. UKC_BEHAVIOR_PHASE mirrors detection/scorer.py
  // UKC_MAPPING — keep the two in sync.
  const UKC_BEHAVIOR_PHASE = {
    auth_anomalies: "Credential Access",
    remote_execution_artifacts: "Execution",
    file_tamper: "Impact",
    staging: "Collection",
    persistence_path_changes: "Persistence",
    anti_forensics: "Defense Evasion",
    cleanup: "Defense Evasion",
    exploit_execution: "Exploitation",
    hello_world_custom: "Execution",
  };
  const telemetryCoverage = run.telemetry_coverage || {};
  const hasCoverageData = Object.keys(telemetryCoverage).length > 0;
  const detectedBehaviors = new Set();
  Object.values(telemetryCoverage).forEach((info) => {
    if (info && info.expected && Array.isArray(info.produced_by)) {
      info.produced_by.forEach((b) => detectedBehaviors.add(b));
    }
  });
  // phase label -> 'covered' | 'partial' | 'gap'  (only meaningful when active)
  function phaseCoverState(phaseLabel) {
    if (!hasCoverageData) return "covered"; // older runs: don't regress styling
    const behs = behaviorsExecuted.filter(
      (b) => (UKC_BEHAVIOR_PHASE[b] || "") === phaseLabel
    );
    if (behs.length === 0) return "covered"; // active via mapping, no behavior detail
    const seen = behs.filter((b) => detectedBehaviors.has(b)).length;
    if (seen === behs.length) return "covered";
    if (seen === 0) return "gap";
    return "partial";
  }

  precomputePath();

  let totalActive = 0, totalTactics = 0;
  const zoneCounts = { "in": 0, "through": 0, "out": 0 };

  RC_PHASES.forEach(phase => {
    const isActiveInData = activePhases.includes(phase.label) || activePhases.includes(phase.label.replace(" Engineering", " Eng")); 
    let isActive = false;
    
    if (replayMode) {
      // In slow motion playback, only illuminate active phases IF the tracer has reached their midpoint
      const phaseMid = phase.offset + phase.len / 2;
      if (isActiveInData && replayProgress >= phaseMid) {
        isActive = true;
      }
    } else {
      isActive = isActiveInData;
    }
    
    if (isActive) zoneCounts[phase.zone]++;
    // For totals, use the raw data so the summary doesn't look like it's missing tactics
    totalActive += isActiveInData ? 1 : 0;
    totalTactics++;
    
    // Save current active state for rendering
    phase.currentActive = isActive;
    phase.coverState = isActive ? phaseCoverState(phase.label) : "none";
  });

  // Blind tactics: attacker executed this tactic but it emitted no observed
  // telemetry at all. Distinct from scenario-level telemetry-class gaps below.
  const blindTactics = RC_PHASES.filter((p) => p.coverState === "gap").length;
  const partialTactics = RC_PHASES.filter((p) => p.coverState === "partial").length;
  // Authoritative scenario gap count — SAME field the coverage panel renders,
  // so the ring and the coverage list can never disagree.
  const scenarioGaps = (run.coverage_gaps || []).length;

  const VW = 820, VH = 330;
  const CY = 140;
  
  const PATH_D = `M 20 270 L 100 270 C 170 270, 240 230, 240 140 A 90 90 0 1 0 60 140 C 60 230, 130 270, 210 270 L 360 270 C 430 270, 500 230, 500 140 A 90 90 0 1 0 320 140 C 320 230, 390 270, 470 270 L 620 270 C 690 270, 760 230, 760 140 A 90 90 0 1 0 580 140 C 580 230, 650 270, 730 270 L 800 270`;
  const zCol = { "in": "#22c55e", "through": "#f97316", "out": "#f43f5e" };

  let svgDefs = `
    <filter id="glow-in" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="9" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    <filter id="glow-through" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="9" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    <filter id="glow-out" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="9" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    <filter id="glow-tracer" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  `;

  let svgContent = `<path d="${PATH_D}" fill="none" stroke="#33415a" stroke-width="26" stroke-linecap="round" />`;
  
  RC_PHASES.forEach(phase => {
    const isActive = phase.currentActive;
    // Active segment is colored by DETECTION state, not just "attack reached
    // here": covered = sensors saw it (zone color), partial = amber,
    // gap = executed into a telemetry blind spot (red, pulsing).
    const isGap = isActive && phase.coverState === "gap";
    // gap = desaturated slate, NO glow, faint heartbeat: "no telemetry = no
    // signal". Deliberately not red so a blind tactic never collides with the
    // OUT zone's red identity. covered = zone color, partial = amber.
    const STATE_COL = { covered: zCol[phase.zone], partial: "#f59e0b", gap: "#8b97a8" };
    const col = isActive ? (STATE_COL[phase.coverState] || zCol[phase.zone]) : zCol[phase.zone];
    const opacity = isGap ? 0.62 : (isActive ? 1 : 0.5);
    const gap = 2;
    const segLen = phase.len - (gap * 2);
    const segOffset = phase.offset + gap;

    const segGlow = (isActive && !isGap) ? `filter="url(#glow-${phase.zone})"` : "";
    const pulse = isGap
      ? `<animate attributeName="opacity" values="0.62;0.28;0.62" dur="1.3s" repeatCount="indefinite" />`
      : "";
    svgContent += `<path d="${PATH_D}" fill="none" stroke="${col}" stroke-width="26"
      stroke-dasharray="${segLen} 1000" stroke-dashoffset="-${segOffset}" pathLength="1000"
      opacity="${opacity}" ${segGlow}>${pulse}</path>`;

    if (phase.pEnd) {
      const chs = 11;
      svgContent += `<polygon points="0,${-chs} ${(chs * 0.65).toFixed(1)},0 0,${chs}"
        fill="${col}" opacity="${isActive ? 0.92 : 0.42}"
        transform="translate(${phase.pEnd.x.toFixed(1)},${phase.pEnd.y.toFixed(1)}) rotate(${phase.angleEnd.toFixed(1)})" />`;
    }
    if (isGap && phase.pMid) {
      // ⚠ marker so a missed tactic reads even at a glance / in screenshots
      svgContent += `<text x="${phase.pMid.x}" y="${phase.pMid.y}" text-anchor="middle" dominant-baseline="central"
        transform="rotate(${phase.angle.toFixed(1)}, ${phase.pMid.x}, ${phase.pMid.y}) translate(0,-13)"
        font-family="monospace" font-size="9" font-weight="900" fill="#e2e8f0"
        stroke="#000000" stroke-width="2" paint-order="stroke fill">⚠</text>`;
    }

    const textOp = isActive ? 1 : 0.82;
    const fw = isActive ? 800 : 700;

    svgContent += `<text x="${phase.pMid.x}" y="${phase.pMid.y}" text-anchor="middle" dominant-baseline="central"
      transform="rotate(${phase.angle.toFixed(1)}, ${phase.pMid.x}, ${phase.pMid.y})"
      font-family="monospace" font-size="7.2" font-weight="${fw}"
      fill="#ffffff" stroke="#000000" stroke-width="2.5" paint-order="stroke fill"
      opacity="${textOp}" letter-spacing="0.05em">${phase.label.toUpperCase()}</text>`;
  });
  
  if (replayMode) {
    const tracerOffset = Math.min(replayProgress, 996);
    svgContent += `<path d="${PATH_D}" fill="none" stroke="#ffffff" stroke-width="26" stroke-linecap="round"
      stroke-dasharray="4 1000" stroke-dashoffset="-${tracerOffset}" pathLength="1000"
      filter="url(#glow-tracer)" />`;
  }

  const centerLabels = [
    { cx: 150, id: "in", label: "IN", subtitle: "Initial Foothold" },
    { cx: 410, id: "through", label: "THROUGH", subtitle: "Network Propagation" },
    { cx: 670, id: "out", label: "OUT", subtitle: "Actions on Objectives" }
  ];
  
  centerLabels.forEach(c => {
    const col = zCol[c.id];
    const zoneActive = zoneCounts[c.id] > 0;
    const opacity = zoneActive ? 1 : 0.62;
    svgContent += `<text x="${c.cx}" y="${CY - 6}" text-anchor="middle" font-family="monospace" font-size="26" font-weight="900" fill="${col}" stroke="#000000" stroke-width="1.5" paint-order="stroke fill" opacity="${opacity}" ${zoneActive ? `filter="url(#glow-${c.id})"` : ""}>${c.label}</text>`;
    svgContent += `<text x="${c.cx}" y="${CY + 14}" text-anchor="middle" font-family="monospace" font-size="8" font-weight="700" fill="#ffffff" stroke="#000000" stroke-width="2" paint-order="stroke fill" opacity="${opacity}" letter-spacing="0.1em">${c.subtitle.toUpperCase()}</text>`;
    if (zoneActive) {
      const totalInZone = RC_PHASES.filter(p => p.zone === c.id).length;
      svgContent += `<text x="${c.cx}" y="${CY + 28}" text-anchor="middle" font-family="monospace" font-size="7" font-weight="700" fill="#ffffff" stroke="#000000" stroke-width="1.5" paint-order="stroke fill" opacity="0.9">${zoneCounts[c.id]} / ${totalInZone} ACTIVE</text>`;
    }
  });

  const svgHTML = `<svg class="ukc-loops-svg" viewBox="0 0 ${VW} ${VH}" preserveAspectRatio="xMidYMid meet">
    <defs>${svgDefs}</defs>${svgContent}</svg>`;

  container.innerHTML = `<div class="ukc-diagram">
    <div class="ukc-loops">${svgHTML}</div>
  </div>`;

  if (summaryEl) {
    const pct = Math.round((totalActive / totalTactics) * 100);
    const btnHtml = `<button id="btn-replay-ukc" class="btn" style="padding: 2px 8px; font-size: 10px; margin-right: 12px; background: ${replayMode ? '#ef4444' : '#00bfb3'}; color: ${replayMode ? '#fff' : '#000'}; font-weight: bold; border-radius: 4px; cursor: pointer; border: none;">${replayMode ? '■ STOP' : '► REPLAY'}</button>`;
    
    summaryEl.innerHTML =
      btnHtml +
      `<span class="ukc-stat"><b>${behaviorsExecuted.length}</b> behaviors</span>` +
      `<span class="ukc-sep">&middot;</span>` +
      `<span class="ukc-stat"><b>${totalActive}</b>/${totalTactics} tactics active</span>` +
      `<span class="ukc-sep">&middot;</span>` +
      `<span class="ukc-stat"><b>${pct}%</b> UKC coverage</span>` +
      `<span class="ukc-sep">|</span>` +
      `<span class="ukc-stat zone-in"><b>${zoneCounts.in||0}/8</b> IN</span>` +
      `<span class="ukc-stat zone-through"><b>${zoneCounts.through||0}/6</b> THROUGH</span>` +
      `<span class="ukc-stat zone-out"><b>${zoneCounts.out||0}/4</b> OUT</span>` +
      `<span class="ukc-sep">|</span>` +
      (hasCoverageData
        ? `<span class="ukc-stat" style="color:${scenarioGaps ? '#ef4444' : '#22c55e'}">&#9679; <b>${scenarioGaps}</b> telemetry gap${scenarioGaps === 1 ? '' : 's'}</span>` +
          (blindTactics ? `<span class="ukc-stat" style="color:#8b97a8">&#9888; <b>${blindTactics}</b> blind tactic${blindTactics === 1 ? '' : 's'}</span>` : "") +
          (partialTactics ? `<span class="ukc-stat" style="color:#f59e0b">&#9679; <b>${partialTactics}</b> partial</span>` : "")
        : `<span class="ukc-stat" style="opacity:0.5">coverage n/a</span>`) +
      `<span class="ukc-sep">&middot;</span>` +
      `<span class="ukc-stat" style="opacity:0.38;font-size:9px">Pols (2017) Ground Truth Mapping</span>`;
      
    document.getElementById("btn-replay-ukc").addEventListener("click", () => {
      if (replayMode) {
        if (replayAnim) cancelAnimationFrame(replayAnim);
        replayMode = false;
        renderKillChain();
      } else {
        playUKCReplay();
      }
    });
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
      STATE.activeRun = STATE.runs.find((r) => r.run_id === tr.dataset.run) || STATE.activeRun;
      renderRunsList();
      renderRunDetail();
      renderAttackMap();
      renderActiveAttack();
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
    
    ${run.score ? `
    <div style="margin-bottom: 16px; background: rgba(0,0,0,0.2); padding: 12px; border-radius: 4px; border: 1px solid var(--border);">
      <div class="panel-sub" style="font-size:10px;letter-spacing:0.18em;color:#00bfff;margin-bottom:8px">EXPLICIT METRICS (GROUND TRUTH)</div>
      <div style="display:grid;grid-template-columns:repeat(4, 1fr);gap:12px">
        <div>
          <div style="font-size:9px;color:var(--text-mute)">OVERALL SCORE</div>
          <div style="font-size:18px;font-weight:700;color:var(--text-bright)">${run.score.overall_score}<span style="font-size:10px;color:var(--text-mute)">/100</span></div>
        </div>
        <div>
          <div style="font-size:9px;color:var(--text-mute)">EXECUTION</div>
          <div style="font-size:18px;font-weight:700;color:var(--text-main)">${run.score.metrics?.execution_success?.score}%</div>
        </div>
        <div>
          <div style="font-size:9px;color:var(--text-mute)">VISIBILITY</div>
          <div style="font-size:18px;font-weight:700;color:var(--text-main)">${run.score.metrics?.telemetry_visibility?.score}%</div>
        </div>
        <div>
          <div style="font-size:9px;color:var(--text-mute)">SAFETY</div>
          <div style="font-size:18px;font-weight:700;color:var(--text-main)">${run.score.metrics?.safety_compliance?.score}%</div>
        </div>
      </div>
      <div style="margin-top:8px">
        <div style="font-size:9px;color:var(--text-mute);margin-bottom:4px">UKC PHASES REPRESENTED</div>
        <div style="font-size:11px;color:var(--text-main);display:flex;flex-wrap:wrap;gap:4px">
          ${(run.score.unified_kill_chain_mapping?.ukc_phases_represented || []).map(p => `<span style="background:rgba(255,255,255,0.05);padding:2px 6px;border-radius:2px;border:1px solid rgba(255,255,255,0.1)">${escapeHtml(p)}</span>`).join('')}
        </div>
      </div>
    </div>
    ` : ''}

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
  const activeBehaviors = STATE.activeRun?.behaviors_planned || [];
  const seen = new Set();
  const techniques = [];
  activeBehaviors.forEach((b) => {
    (STATE.attackMap[b] || []).forEach((t) => {
      if (!seen.has(t.id)) { seen.add(t.id); techniques.push({ ...t, behavior: b }); }
    });
  });
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
// Benchmark renderers
// ---------------------------------------------------------------------

function renderBenchmarkList() {
  const tbody = document.querySelector("#tbl-benchmarks tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!STATE.benchmarks.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty-hint">No benchmark runs yet. Run the benchmark scorer after a scenario execution.</td></tr>';
    return;
  }
  STATE.benchmarks.forEach((b) => {
    const tr = document.createElement("tr");
    tr.style.cursor = "pointer";
    if (b.run_id === STATE.selectedBenchmarkId) tr.classList.add("row-selected");
    const rateColor = b.detection_rate_pct >= 80 ? "var(--sev-low)" : b.detection_rate_pct >= 50 ? "var(--sev-med)" : "var(--sev-crit)";
    tr.innerHTML = `
      <td class="mono">${b.run_id}</td>
      <td>${b.agent_name || "—"}</td>
      <td style="color:${rateColor};font-weight:600;">${b.detection_rate_pct ?? "—"}%</td>
      <td style="color:var(--sev-low);">${b.true_positives ?? "—"}</td>
      <td style="color:var(--sev-crit);">${b.false_negatives ?? "—"}</td>
      <td style="color:var(--sev-high);">${b.false_positives ?? "—"}</td>
      <td class="ts">${(b.scored_at || "").substring(0, 19).replace("T", " ")}</td>
    `;
    tr.addEventListener("click", () => {
      STATE.selectedBenchmarkId = b.run_id;
      renderBenchmarkDetail(b);
      renderBenchmarkList();
    });
    tbody.appendChild(tr);
  });
}

function renderBenchmarkDetail(b) {
  // KPI row
  const rateColor = b.detection_rate_pct >= 80 ? "var(--sev-low)" : b.detection_rate_pct >= 50 ? "var(--sev-med)" : "var(--sev-crit)";
  document.getElementById("bm-rate").textContent = `${b.detection_rate_pct ?? "—"}%`;
  document.getElementById("bm-rate").style.color = rateColor;
  document.getElementById("bm-tp").textContent = b.true_positives ?? "—";
  document.getElementById("bm-fn").textContent = b.false_negatives ?? "—";
  document.getElementById("bm-fp").textContent = b.false_positives ?? "—";
  document.getElementById("bm-latency").textContent = b.avg_latency_s != null ? `${b.avg_latency_s}s` : "—";
  document.getElementById("bm-agent").textContent = b.agent_name || "—";

  // Per-step verdicts
  const meta = document.getElementById("bm-detail-meta");
  const detail = document.getElementById("bm-step-detail");
  meta.textContent = b.run_id;
  detail.innerHTML = "";

  const steps = (b.per_step || []).filter(s => s.result !== "unscored");
  if (!steps.length) {
    detail.innerHTML = '<div class="empty-hint">No scoreable steps (all steps lack technique_id labels).</div>';
  } else {
    const table = document.createElement("table");
    table.className = "data-table";
    table.innerHTML = `<thead><tr><th>step</th><th>behavior</th><th>technique</th><th>verdict</th><th>latency</th></tr></thead>`;
    const tbody = document.createElement("tbody");
    steps.forEach(s => {
      const tr = document.createElement("tr");
      const verdictColor = s.result === "detected" ? "var(--sev-low)" : "var(--sev-crit)";
      tr.innerHTML = `
        <td class="mono">${s.step_id}</td>
        <td>${s.behavior}</td>
        <td class="mono">${s.technique_id || "—"}</td>
        <td style="color:${verdictColor};font-weight:600;">${s.result.toUpperCase()}</td>
        <td>${s.latency_s != null ? s.latency_s + "s" : "—"}</td>
      `;
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    detail.appendChild(table);
  }

  // FP panel
  const fpPanel = document.getElementById("bm-fp-panel");
  const fpTbody = document.querySelector("#tbl-bm-fps tbody");
  if (b.false_positive_alerts && b.false_positive_alerts.length) {
    fpPanel.style.display = "";
    fpTbody.innerHTML = "";
    b.false_positive_alerts.forEach(a => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="ts">${(a.timestamp || "").substring(0, 19).replace("T", " ")}</td>
        <td class="mono">${a.technique_id || "—"}</td>
        <td>${a.rule_name || "—"}</td>
        <td>${a.severity || "—"}</td>
      `;
      fpTbody.appendChild(tr);
    });
  } else {
    fpPanel.style.display = "none";
  }
}

// ---------------------------------------------------------------------
// AI Attacks renderers
// ---------------------------------------------------------------------

function renderAiAttacks() {
  const stats = STATE.aiStats || {};
  const attacks = STATE.aiAttacks || [];

  document.getElementById("ai-total").textContent = stats.total ?? "—";
  document.getElementById("ai-success").textContent = stats.successes ?? "—";
  document.getElementById("ai-rate").textContent = stats.total ? `${stats.success_rate_pct}%` : "—";
  document.getElementById("ai-techniques").textContent = Object.keys(stats.by_technique || {}).length || "—";
  const targets = [...new Set(attacks.map(a => a.target).filter(Boolean))];
  document.getElementById("ai-target").textContent = targets[0] || "—";

  const noData = document.getElementById("ai-no-data");
  const dataView = document.getElementById("ai-data-view");
  if (!attacks.length) {
    noData.style.display = "";
    dataView.style.display = "none";
    return;
  }
  noData.style.display = "none";
  dataView.style.display = "";

  // Attack log table
  const tbody = document.querySelector("#tbl-ai-attacks tbody");
  tbody.innerHTML = "";
  [...attacks].reverse().slice(0, 100).forEach(a => {
    const tr = document.createElement("tr");
    tr.style.cursor = "pointer";
    const ok = (a.score || {}).jailbreak_success;
    const scoreVal = (a.score || {}).score_value ?? "—";
    tr.innerHTML = `
      <td class="ts">${(a.timestamp || "").substring(0, 19).replace("T", " ")}</td>
      <td class="mono">${a.atlas_technique || "—"}</td>
      <td>${a.scenario || "—"}</td>
      <td style="color:${ok ? "var(--sev-crit)" : "var(--sev-low)"};font-weight:600;">${ok ? "BYPASSED" : "BLOCKED"}</td>
      <td>${scoreVal}</td>
    `;
    tr.addEventListener("click", () => showAiDetail(a));
    tbody.appendChild(tr);
  });

  // ATLAS chart
  const byTech = stats.by_technique || {};
  const labels = Object.keys(byTech);
  const values = Object.values(byTech);
  if (charts.atlasChart) charts.atlasChart.destroy();
  if (labels.length) {
    const ctx = document.getElementById("chart-atlas-techniques").getContext("2d");
    charts.atlasChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [{ label: "attempts", data: values, backgroundColor: "rgba(255,59,48,0.7)", borderColor: "#ff3b30", borderWidth: 1 }],
      },
      options: { responsive: true, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: "#8b939e", font: { size: 10 } } }, y: { ticks: { color: "#8b939e" }, beginAtZero: true } } },
    });
  }
}

function showAiDetail(a) {
  const panel = document.getElementById("ai-detail-panel");
  const meta = document.getElementById("ai-detail-meta");
  const body = document.getElementById("ai-detail-body");
  panel.style.display = "";
  meta.textContent = `${a.atlas_technique || "?"} · ${a.scenario || "?"}`;
  const score = a.score || {};
  body.innerHTML = `
    <div style="display:grid;grid-template-columns:120px 1fr;gap:6px 16px;margin-bottom:14px;">
      <span style="color:var(--text-dim);">technique</span><span>${a.atlas_technique || "—"} · ${a.atlas_tactic || "—"}</span>
      <span style="color:var(--text-dim);">target</span><span>${a.target || "—"}</span>
      <span style="color:var(--text-dim);">result</span><span style="color:${score.jailbreak_success ? "var(--sev-crit)" : "var(--sev-low)"};">${score.jailbreak_success ? "JAILBREAK SUCCESS" : "BLOCKED"}</span>
      <span style="color:var(--text-dim);">harm_category</span><span>${score.harm_category || "—"}</span>
      <span style="color:var(--text-dim);">score</span><span>${score.score_value ?? "—"}</span>
    </div>
    <div style="margin-bottom:8px;color:var(--text-dim);font-size:11px;">PROMPT</div>
    <pre style="background:var(--bg-elev-2);padding:10px;border-radius:4px;overflow-x:auto;white-space:pre-wrap;word-break:break-word;color:var(--sev-high);">${(a.prompt || "").replace(/</g,"&lt;")}</pre>
    <div style="margin:10px 0 8px;color:var(--text-dim);font-size:11px;">RESPONSE</div>
    <pre style="background:var(--bg-elev-2);padding:10px;border-radius:4px;overflow-x:auto;white-space:pre-wrap;word-break:break-word;">${(a.response || "").replace(/</g,"&lt;")}</pre>
  `;
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
