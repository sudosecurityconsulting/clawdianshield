# ClawdianShield

**Detection Validation Framework for AI-Native and Traditional SOC Platforms**

Built by Kevin Landry — USCG veteran, GMU MS Digital Forensics, founder Sudo Security Consulting LLC.

---

## The Problem

Most organizations have no ground-truth answer to the question: *does my detection stack actually work?*

Vendor-supplied test scenarios are written by the same team that built the model. Dashboards only surface what the system chose to surface. AI-native SOC platforms introduce a second layer of opacity — the model decides what matters, and you trust that decision without evidence.

The cost of blind spots is not theoretical. An undetected lateral movement chain, a missed persistence-path write, an anti-forensics sequence that cleared logs without firing a single alert — these failures only become visible after a breach, and only then with full hindsight.

**ClawdianShield generates deterministic adversary telemetry and measures whether your detection stack caught it.** No vendor bias. No synthetic hallucination. Ground-truth signal and a coverage score your SIEM cannot dispute.

---

## What It Does

- **Generates authentic host-side telemetry** — file tampering, auth anomalies, staging, persistence writes, anti-forensics sequences — using real Docker exec commands on a controlled victim container
- **Scores detection coverage** across five dimensions: detection rate, telemetry completeness, correlation quality, timeliness, and analyst usefulness
- **Maps observed behavior to MITRE ATT&CK techniques** and visualizes coverage against the Unified Kill Chain (Pols, 2017) 18-tactic model
- **Produces AI-powered incident briefs** via Gemini 2.5 Flash — executive summary, attack chain narrative, telemetry gap assessment, and risk rating per run

The scenarios do not ship real exploits or credential attack logic. They produce the signals defenders care about — without depending on target internals or crossing into operationally abusive territory. The point is detection coverage and telemetry quality.

---

## Proof of Execution

When `fim_burst_tamper.json` fires, the execution plane induces real state changes and the host-side observer streams the evidence immediately:

```json
{
  "run_id": "live-fire-001",
  "scenario_id": "fim_burst_001",
  "host": "workstation-1",
  "event_type": "file_create",
  "timestamp": "2026-04-29T01:01:52.906Z",
  "severity": "medium",
  "details": {
    "path": "victim_state/sensitive.conf",
    "sha256": "b7bce5de2b533fd8ad8ea39be699ae4b39bbaaada16e2dd029848c745d0ab816"
  },
  "collector": "file_observer"
}
```

![Executive Overview — 138 ingested events, severity timeseries, event type distribution, severity mix, collector feeds, top mutated paths, and active scenario profile with telemetry coverage assessment](ClawdianShield/docs/screenshot-overview.png)

---

## Architecture

Four planes. Each with a distinct responsibility.

```
Control Plane    — Load scenario JSON → validate safety constraints → build attack plan
Execution Plane  — Translate behaviors → docker exec commands → fire at victim container
Telemetry Plane  — Host-side observers stream JSONL evidence from bind-mounted state
Evaluation Plane — Score expected vs. observed, generate JSON report with blind spots
```

The key design decision: observers run on the **host** (not inside the victim) watching bind-mounted directories. Real artifacts. Real reads. Zero in-process telemetry fabrication.

```
scenarios/<id>.json
        │
        ▼
engine/executor.py                    ← subprocess engine, safety gate, behavior→cmd map
  docker exec clawdian_victim sh -c "<cmd>"
        │                                        ┌──────────────────────────────────┐
        │  artifacts (real)                      │  collectors/file_observer        │
        ▼                                        │  collectors/log_observer         │
  clawdian_victim:/tmp/ClawdianShield --bind-->  │  (host-side watchdog + tail;     │
  clawdian_victim:/var/log             mount     │   emit JSONL via NormalizedEvent) │
                                                 └──────────────┬───────────────────┘
        │                                                       ▼
        ▼                                           evidence/file_events.jsonl
reports/<run_id>_exec_log.json                      evidence/auth_events.jsonl
```

Full PlantUML diagrams: [`ClawdianShield/docs/architecture.puml`](ClawdianShield/docs/architecture.puml)

---

## Quick Start

**Requirements:** Docker Desktop 4.70+ with WSL2 backend. Python 3.11+.

```bash
# 1. Clone
git clone https://github.com/dadopsmateomaddox/ClawdianShield.git
cd ClawdianShield

# 2. Install Python deps
pip install -r ClawdianShield/requirements.txt

# 3. Configure API key for AI briefs (optional — dashboard works without it)
cp ClawdianShield/.env.example ClawdianShield/.env
# Edit .env and add: GEMINI_API_KEY=your_key_here

# 4. Seed demo data (no Docker required — populates dashboard immediately)
python -m ClawdianShield.dashboard.seed_demo --reset

# 5. Launch the dashboard
python -m ClawdianShield.dashboard.server --host 0.0.0.0 --port 8088
# → http://localhost:8088
```

**What success looks like:** Dashboard loads with 138 ingested events, severity timeseries populated, scenario runs visible in the SCENARIO RUNS tab. Click any run and select GENERATE BRIEF to invoke Gemini.

To run a live scenario (requires Docker):

```bash
# Spin up the victim container
docker compose -f ClawdianShield/docker/docker-compose.yml up -d clawdian_victim

# Start observers (Terminal 1)
python -m ClawdianShield.collectors.run \
  --run-id verify-001 \
  --scenario-id fim_burst_001 \
  --host workstation-1

# Fire the scenario (Terminal 2)
python ClawdianShield/engine/executor.py \
  ClawdianShield/engine/scenarios/fim_burst_tamper.json \
  --container clawdian_victim

# Dry-run any scenario without Docker (validates parsing + safety gate)
python ClawdianShield/engine/executor.py \
  ClawdianShield/engine/scenarios/fim_burst_tamper.json --dry-run
```

---

## Scenario Catalog

Ten deterministic crime scenes. Each produces a specific set of defender-relevant artifacts.

| ID | Name | Risk | Hosts | What It Tests |
| :--- | :--- | :--- | :--- | :--- |
| `fim_burst_001` | FIM Burst Tamper Storm | Medium | 1 | File integrity monitoring speed and threshold sensitivity |
| `trusted_binary_blend_001` | Trusted Binary Tamper Blend | Medium | 1 | Detection of tampering via trusted binary abuse |
| `sensitive_config_drift_001` | Sensitive Config Drift | Medium | 1 | Config file monitoring and drift detection |
| `auth_abuse_001` | Synthetic Multi-Host Auth Abuse | High | 2 | Cross-host authentication anomaly correlation |
| `remote_exec_artifacts_001` | Remote Execution Artifact Chain | High | 2 | Lateral movement artifact detection |
| `collection_staging_001` | Collection and Staging Run | High | 1 | Data staging and archive detection |
| `persistence_path_mutation_001` | Persistence Path Mutation | Critical | 1 | Persistence mechanism detection coverage |
| `anti_forensics_pressure_001` | Anti-Forensics Pressure Test | Critical | 1 | Log tampering and cleanup detection |
| `dependency_swap_001` | Dependency Swap / Supply Chain Emulation | Critical | 1 | Software supply chain signal detection |
| `full_storyline_001` | Full Synthetic Intrusion Storyline | High | 2 | End-to-end intrusion chain — auth burst → remote exec → staging → persistence → anti-forensics → cleanup |

---

## Dashboard

A Kibana-style analyst console with real-time WebSocket event streaming.

**Panels:**
- Severity timeseries — event volume and criticality over time
- Event type distribution — file, auth, process signals by category
- MITRE ATT&CK technique coverage mapped to the Unified Kill Chain
- Top mutated paths — file system artifacts ranked by frequency
- Collector feed status — which observers are active
- Scenario step trace — per-step execution timeline with OK/FAIL status
- Live event stream — WebSocket-backed real-time feed

**UKC Visualization:** Three-ring display — IN (Initial Foothold), THROUGH (Network Propagation), OUT (Actions on Objectives). Active tactic arcs illuminate as telemetry fires. If a ring is dim, your SOC has a problem.

**Incident Brief:** Gemini 2.5 Flash generates a SOC-grade markdown brief per run — executive summary, attack chain narrative, telemetry gap assessment, recommended detections, risk rating.

![Scenario Runs Console — Full Synthetic Intrusion Storyline with AI-generated brief showing attack chain narrative and all 23 execution steps](ClawdianShield/docs/screenshot-scenario-runs.png)

![ATT&CK Map — MITRE technique coverage grid with 13 mapped techniques](ClawdianShield/docs/screenshot-attack-map.png)

API endpoints:

| Route | Method | Description |
| :--- | :--- | :--- |
| `/` | GET | Analyst console (SPA) |
| `/api/stats` | GET | Aggregated metrics over buffered evidence |
| `/api/runs` | GET | All exec_log run summaries |
| `/api/events?limit=N` | GET | Last-N buffered NormalizedEvents |
| `/api/attack-map` | GET | MITRE ATT&CK technique mapping per behavior |
| `/api/brief/<run_id>` | GET | Gemini AI incident brief for a completed run |
| `/ws` | WebSocket | Live event push — snapshot on connect, then per-event frames |

The server is read-only. It never mutates evidence or fires scenarios.

---

## SIEM Forwarding — Elastic (Phase 3a)

The `telemetry/forwarders/elastic_shipper.py` shipper bulk-ingests the evidence
JSONL stream into Elasticsearch (`ClawdianShield-events` index) so the same
ground-truth telemetry the dashboard scores can be queried, pivoted, and
alerted on from a real SIEM — not just the built-in console.

Bring up the single-node cluster with `docker compose up -d elasticsearch
kibana`, then run the shipper against `evidence/`. Events land with their full
NormalizedEvent shape — `collector`, `event_type`, `details.path`, `host`,
`run_id`, `scenario_id`, `severity`, `timestamp` — so a `fim_burst_001` run is
fully reconstructable in Kibana Discover.

![Kibana Discover — ClawdianShield-events index, 164 shipped events from a fim_burst_001 run, showing per-event collector/path/severity fields and the ingest-volume timeseries](ClawdianShield/docs/screenshot-elastic-siem.png)

This is the proof the forwarder works end-to-end: host-side observers →
evidence JSONL → Elasticsearch bulk → Kibana, with zero fabricated telemetry
anywhere in the path.

---

## Scoring Model

Every run is graded across five dimensions.

| Dimension | Weight | Question It Answers |
| :--- | :---: | :--- |
| Detection Coverage | 30% | Did the expected detections actually fire? |
| Telemetry Completeness | 25% | Were all required event classes observed? |
| Correlation Quality | 20% | Were cross-host and cross-stage events linked? |
| Timeliness | 15% | Was activity surfaced before the attacker cleaned up? |
| Analyst Usefulness | 10% | Does the alert tell a coherent story? |

---

## Security Model

**What ClawdianShield does:**
- Generate synthetic telemetry signals that mimic real adversary behavior patterns
- Simulate file tampering, authentication abuse, staging, persistence writes, and cleanup
- Measure whether your detection stack catches these signals
- Run entirely within a local Docker environment with no outbound connections

**What ClawdianShield does not do:**
- Execute real exploits or malware payloads
- Compromise real credential material
- Perform actual privilege escalation
- Send data to external infrastructure
- Modify production systems

**Design assumptions:**
- Only run on lab equipment (dedicated victim container with network mode `none`)
- Bind-mounts are host-controlled (`victim_state/` and `victim_logs/` dirs)
- Gemini API key stays in `ClawdianShield/.env` — never committed
- Docker container has no network access by design

**Safe use boundaries:** Single lab victim container. Cleanup phase runs after every scenario. No lateral movement (single container, network mode none). Air-gapped execution.

---

## Telemetry Schema

All observers emit JSONL using the `NormalizedEvent` schema (`ClawdianShield/unification/models.py`, Pydantic v2):

```json
{
  "run_id": "exec-20260426-085200-d32503",
  "scenario_id": "fim_burst_001",
  "host": "workstation-1",
  "event_type": "file_create",
  "timestamp": "2026-04-26T08:52:00.587542+00:00",
  "severity": "medium",
  "details": {"path": "victim_state/sensitive.conf", "sha256": "36d6f..."},
  "collector": "file_observer"
}
```

| Module | Role | Status |
| :--- | :--- | :--- |
| `collectors/file_observer.py` | Watchdog PollingObserver on bind-mounted victim state | Live |
| `collectors/log_observer.py` | Log tailer — regex-classifies pam_unix auth events | Live |
| `collectors/run.py` | Launcher — starts both observers, shared stop event | Live |
| `collectors/correlation.py` | Cross-host adjacency from `details.source_host` | Utility |
| `collectors/normalizer.py` | Dict → NormalizedEvent boundary validator | Utility |
| `collectors/file_events.py` | sha256 snapshot/diff helpers | Utility |

---

## Phase Status

| Phase | Description | Status |
| :--- | :--- | :--- |
| 1 — Core Engine | Scenario executor, Docker victim, safety gate, dry-run mode | Complete |
| 2 — SOC Dashboard | FastAPI + WebSocket console, UKC visualization, ATT&CK map | Complete |
| 2b — AI Intelligence | Gemini brief generation, model selector, cached reports | Complete |
| 3a — Telemetry | Elastic shipper (`telemetry/forwarders/elastic_shipper.py`) — JSONL → Elasticsearch + Kibana | Working (live-verified) |
| 3a — Telemetry | Splunk HEC forwarder (`ClawdianShield/telemetry/`) | Backlog |
| 3b — CVE Intelligence | NVD/CISA KEV feed mapped to observed ATT&CK techniques | Backlog |
| 3c — Scenario Expansion | Container escape, credential access, cloud metadata abuse | Backlog |

---

## Repo Structure

```
ClawdianShield/
├── runner/          executor.py — deterministic subprocess scenario engine + safety gate
├── collectors/      file_observer, log_observer, run (host-side streaming observers)
├── shared/          models.py — Pydantic v2 NormalizedEvent / RunContext schema
├── victim/          Dockerfile.victim — minimal Alpine target image
├── scenarios/       10 JSON scenario definitions
├── dashboard/       server.py — FastAPI + WebSocket + REST; static/ — SPA frontend
├── intelligence/    gemini_client.py — Gemini AI brief generation
├── telemetry/       Splunk HEC forwarder (Phase 3a backlog)
├── detections/      Detection rule stubs (Phase 3 backlog)
├── evidence/        JSONL event output (gitignored)
├── reports/         Exec logs and run scorecards (gitignored, .gitkeep)
├── tests/           Validation harness
├── utils/           JSONL read/write helpers
├── scripts/         Linear backlog bootstrap
├── docs/            PlantUML architecture + sequence diagrams + screenshots
└── docker/          Dockerfile.runner + docker-compose.yml
```

---

## Contributing

Open an issue to request a specific emulation chain, challenge the scorecard weights, or report a detection gap. Branch naming: `cls-<issue-id>/<description>`. Commits reference issue IDs.

Active feedback requests from Detection Engineers, DFIR professionals, and Cloud Architects.

- **GitHub:** Open an issue
- **LinkedIn:** [Kevin Landry](https://www.linkedin.com/in/kevin-landry-cybersecurity)

---

## License

This project is licensed under the **Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)**.

You are free to:

- **Share** — copy and redistribute the material in any medium or format.
- **Adapt** — remix, transform, and build upon the material.

Under the following terms:

- **NonCommercial** — You may not use the material for commercial purposes, including for-profit consulting, commercial SOC validation, or integration into paid security products.

For commercial licensing, enterprise use, or consulting inquiries, please contact **Sudo Security Consulting LLC**.
