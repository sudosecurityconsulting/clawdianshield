# ClawdianShield

**A detection engineering lab and adversary emulation pipeline.** This is a working, deterministic, zero-outbound digital crime scene designed to produce the exact telemetry your SOC is likely missing right now.

> [!IMPORTANT]
> **Status: Phase 3a (Telemetry Observer) is LIVE.**
> End-to-end verified: `fim_burst_tamper.json` produced 6 authentic file events; `synthetic_auth_abuse.json` produced 6 auth events. This project demonstrates real-world telemetry collection, not just slide-deck theory.

---

## **The Point: Real-World Value for Startups and Enterprises**

Most security portfolios are just a stack of certs and CTF writeups. ClawdianShield is different. It solves a specific business problem: **Validation.**

Small startups cannot afford a $50,000 red team engagement just to see if their open-source logging works. Enterprise SOCs have millions invested in SIEMs, but often have no idea if their detection logic actually fires until a breach happens.

This system acts as a **black-box adversary emulation engine**. It:
1. Induces defender-relevant artifacts in a controlled lab.
2. Measures whether your detection stack caught them.
3. Brutally scores your coverage gaps.

The scenarios don't use real exploit or credential attack logic (but can be programmed to do so in a controlled, air-gapped environment). This version is designed to produce the *signals* that defenders care about - auth anomalies, file tampering chains, cross-host traces, staging activity, persistence-path writes, anti-forensics signals - without depending on target internals or shipping anything operationally abusive. The point is detection coverage and telemetry quality, not malware cosplay.

---

## **Architecture: The Four Planes**

```text
Control Plane    - Load scenario JSON -> validate safety constraints -> build attack plan
Execution Plane  - Translate behaviors -> docker exec commands -> fire at victim
Telemetry Plane  - Host-side observers stream JSONL evidence from bind-mounted state
Evaluation Plane - Score expected vs. observed, generate JSON report with blind spots
```

**Authentic Observation:** The observers run on the *host* (not inside the victim) watching bind-mounted directories. This provides real artifacts and real reads with zero in-process telemetry fabrication.

The execution and observation flow:

```text
scenarios/<id>.json
        │
        ▼
runner/executor.py                    <- subprocess engine (Phase 2)
  safety gate
  behavior -> command map
  docker exec clawdian_victim sh -c "<cmd>"
        │                                          ┌─────────────────────────────┐
        │  artifacts                               │  collectors/file_observer   │
        ▼  (real)                                  │  collectors/log_observer    │
  clawdian_victim:/tmp/clawdianshield  --bind-->   │  (host-side, watchdog +     │
  clawdian_victim:/var/log              mount      │   tail; emit JSONL via      │
                                                   │   shared.models.NormalizedEvent)
                                                   └─────────────┬───────────────┘
        │                                                        ▼
        ▼                                              evidence/file_events.jsonl
reports/<run_id>_exec_log.json                         evidence/auth_events.jsonl
```

Full diagram: [`docs/architecture.puml`](docs/architecture.puml)  
Bootstrap sequence: [`docs/sequence-bootstrap.puml`](docs/sequence-bootstrap.puml)

---

## **The Menu of Mayhem (Scenario Catalog)**

| ID | Name | Risk | Hosts |
| :--- | :--- | :--- | :--- |
| `fim_burst_001` | FIM Burst Tamper Storm | Medium | 1 |
| `trusted_binary_blend_001` | Trusted Binary Tamper Blend | Medium | 1 |
| `sensitive_config_drift_001` | Sensitive Config Drift | Medium | 1 |
| `auth_abuse_001` | Synthetic Multi-Host Auth Abuse | High | 2 |
| `remote_exec_artifacts_001` | Remote Execution Artifact Chain | High | 2 |
| `collection_staging_001` | Collection and Staging Run | High | 1 |
| `persistence_path_mutation_001` | Persistence Path Mutation | Critical | 1 |
| `anti_forensics_pressure_001` | Anti-Forensics Pressure Test | Critical | 1 |
| `dependency_swap_001` | Dependency Swap / Supply Chain Emulation | Critical | 1 |
| `full_storyline_001` | Full Synthetic Intrusion Storyline | High | 2 |

The full storyline chains auth burst -> remote execution artifacts -> enumeration/staging -> persistence-path mutation -> anti-forensics -> cleanup. One run, seven stages, one scorecard.

---

## **The Scorecard**

Every run is graded across five dimensions. If your stack is blind, this will tell you exactly where:

*   **Detection Coverage (30%)**: Did the expected detections actually fire?
*   **Telemetry Completeness (25%)**: Were all required event classes observed?
*   **Correlation Quality (20%)**: Were cross-host and cross-stage events linked?
*   **Timeliness (15%)**: Was activity surfaced before the attacker cleaned up?
*   **Analyst Usefulness (10%)**: Does the alert tell a coherent story?

---

## **How It Is Built (RE Claw Code)**

I follow a workflow called **RE Claw Code**: Reverse engineering discipline and Incident Response paranoia applied to software development.

*   **Tracking:** Every component maps to a **Linear** issue.
*   **Git Flow:** Every branch and commit references an issue ID (`CLS-<id>`).
*   **AI Pair Programming:** Implementation via **Claude Code CLI** and **GitHub Copilot**. I dictate the physics of the universe; they just build the furniture.

The project backlog was seeded programmatically via `scripts/linear-bootstrap.js`. The GitHub <-> Linear sync is wired via `.github/workflows/linear-sync.yml` - PR merges close Linear issues automatically.

---

## **Repo Structure**

```text
clawdianShield/
├── runner/          executor.py - deterministic subprocess scenario engine
├── collectors/      file_observer, log_observer, run (host-side streaming observers);
│                    correlation, normalizer, file_events (helpers)
├── shared/          models.py - Pydantic NormalizedEvent / RunContext schema
├── victim/          Dockerfile.victim - minimal alpine target image
├── scenarios/       JSON scenario definitions (10 scenarios + test fixtures)
├── victim_state/    bind-mounted to /tmp/clawdianshield in victim (gitignored)
├── victim_logs/     bind-mounted to /var/log in victim (gitignored)
├── evidence/        JSONL event output from observers (gitignored)
├── reports/         executor logs and run scorecards (gitignored, .gitkeep)
├── tests/           validation harness
├── utils/           shared helpers (JSONL read/write)
├── scripts/         Linear backlog bootstrap
├── docs/            PlantUML architecture and sequence diagrams
└── docker/          Dockerfile.runner + docker-compose.yml
```

---

## **Running It**

```bash
# 1. Dry-run (no Docker required - validates parsing, safety gate, and plan)
python runner/executor.py scenarios/fim_burst_tamper.json --dry-run

# 2. Spin up the victim container
docker compose -f docker/docker-compose.yml up -d clawdian_victim

# 3. Start the host-side observers (Terminal 1)
python -m collectors.run \
  --run-id verify-001 \
  --scenario-id fim_burst_001 \
  --host workstation-1

# 4. Fire the scenario (Terminal 2)
python runner/executor.py scenarios/fim_burst_tamper.json --container clawdian_victim
```

Two output streams land per run:

- `reports/<run-id>_exec_log.json` - executor's per-step trace, telemetry coverage, and gap analysis.
- `evidence/{file_events,auth_events}.jsonl` - host-side observers' streamed `NormalizedEvent` records (one JSON object per line) describing every file-system change in the bind-mounted victim state and every classified line in the bind-mounted auth log.

---

## **SOC / IR Dashboard**

A Kibana-styled analyst console reads the same JSONL evidence and exec_log
reports, surfaces severity timeseries, MITRE ATT&CK technique coverage, top
mutated paths, scenario step traces, and a live WebSocket-backed event stream.

```bash
# 1. install dashboard deps (FastAPI + uvicorn already in requirements.txt)
pip install -r requirements.txt

# 2. (optional) seed believable evidence so the dashboard has data without
#    needing the full Docker observer stack online
python -m dashboard.seed_demo --reset

# 3. launch the console
python -m dashboard.server          # http://127.0.0.1:8088

# 4. (optional, in a second terminal) keep the live stream flowing during a
#    presentation by appending synthetic events at ~2 events/sec
python -m dashboard.live_demo --eps 2
```

Endpoints:

- `GET /` - analyst console (single-page app)
- `GET /api/stats` - aggregated metrics over buffered evidence
- `GET /api/runs` - every `reports/*_exec_log.json` run summary
- `GET /api/events?limit=N` - last-N buffered NormalizedEvents
- `GET /api/attack-map` - MITRE ATT&CK technique mapping per behavior
- `WS /ws` - live event push (snapshot on connect, then per-event frames)

The server is read-only - it never mutates evidence or fires scenarios.

---

## **Local Setup**

```bash
# 1. Clone
git clone https://github.com/dadopsmateomaddox/clawdianShield.git
cd clawdianShield

# 2. Python deps
pip install -r requirements.txt

# 3. Node deps (Linear tooling only)
npm install

# 4. Configure secrets - never commit real values
cp .env.example .env
# Edit .env - add LINEAR_API_KEY and ANTHROPIC_API_KEY

# 5. Seed Linear backlog (idempotent - skips existing issues)
npm run bootstrap-linear
```

**Environment:** Docker Desktop 4.70+ with WSL2 backend. PowerShell 7+ recommended.

---

## **Telemetry Schema**

All observers emit JSONL to `evidence/` using the `NormalizedEvent` schema from `shared/models.py` (Pydantic v2):

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

| Module | Description | Status |
| --- | --- | --- |
| `collectors/file_observer.py` | Host-side watchdog PollingObserver on bind-mounted victim state dir | live |
| `collectors/log_observer.py` | Host-side log tailer on bind-mounted `/var/log/auth.log`; regex-classifies pam_unix events | live |
| `collectors/run.py` | Convenience launcher: start both observers, share stop event, write to `evidence/` | live |
| `collectors/correlation.py` | Cross-host adjacency from `details.source_host` | utility |
| `collectors/normalizer.py` | Dict -> NormalizedEvent boundary helper | utility |
| `collectors/file_events.py` | sha256 snapshot/diff helpers used by file_observer | utility |

---

## **Project Management**

**Linear:** ClawdianShield project, team ClawCode_V-ClaudeCode  
**Branch naming:** `cls-<issue-id>/<short-description>`  
**Commits:** `CLS-<id>: <message>`  
**Milestones:** MVP Baseline -> Telemetry -> Detections -> Scenarios -> Evidence -> Portfolio Packaging

GitHub PRs are linked to Linear issues automatically via `.github/workflows/linear-sync.yml`. When a PR is merged from a branch named `cls-<id>/...`, the corresponding Linear issue is closed.

---

## **Security Notes**

- `.env` is gitignored and cursorignored - never committed
- `.env.example` contains only placeholders - safe to commit
- All secrets are loaded via `dotenv` at runtime
- Rotate any key that has been visible in a terminal, chat, or log

---

## **Detailed Status**

**Phase 1 - Complete.**  
Core scenario definitions (10), Docker environment, and project tooling.

**Phase 2 - Scenario Engine complete.**  
`runner/executor.py`: deterministic subprocess engine, behavior -> `docker exec` shell command map, per-step execution log, telemetry coverage gap analysis. Safety gate enforces lab-only constraints before any execution. Dry-run mode validates scenarios without Docker.

**Phase 3a - Telemetry Observer live.**  
Path A authentic-observation telemetry plane: `clawdian_victim` (alpine + tini, no syslog daemon) wired into `docker/docker-compose.yml` with `/tmp/clawdianshield` and `/var/log` bind-mounted to host directories. Host-side observers (`collectors/file_observer.py` via watchdog `PollingObserver`, `collectors/log_observer.py` via tail-and-classify) stream `NormalizedEvent` JSONL into `evidence/`. End-to-end verified: `fim_burst_tamper.json` produced 6 file events; `synthetic_auth_abuse.json` produced 6 auth events (5 failures, 1 success with extracted account name).

**Phase 3b - Scenario expansion.**  
Three host-fit threat-vector scenarios on deck (no architectural change required): `container_escape_signals_001` (capability probes, mount enumeration, runC-style symlink chains), `credential_access_signals_001` (synthetic SSH key drops, sudoers tampering), `cloud_metadata_abuse_001` (synthetic IMDSv2 SSRF chain, IAM token staging). Network/application-layer attacks (SQLi, DoS, MitM) are explicitly deferred to a future hybrid-mode network plane.

---

## **Collaboration & Contact**

I am actively looking for feedback from **Detection Engineers, DFIR professionals, and Cloud Architects**.

*   **LinkedIn**: [Insert Your LinkedIn URL Here]
*   **GitHub**: Open an issue to request a specific emulation chain.
