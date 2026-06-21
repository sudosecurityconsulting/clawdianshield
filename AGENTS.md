# ClawdianShield — AGENTS.md

Git root: `d:/MasterVault/SUDO` — all paths in this file are relative to the git root unless stated otherwise.

## Zero-Fail Pathing

**Always operate from the git root: `d:/MasterVault/SUDO`**

- Never assume a subdirectory as CWD. If unsure, run `git rev-parse --show-toplevel` to verify.
- The repo has 70+ directories. Do not navigate by intuition. Use explicit absolute paths.
- Shell: Git Bash (Unix syntax). Use forward slashes. `/d/MasterVault/SUDO/` not `D:\`.

Key paths (the four pipeline packages spell **S-U-D-O** — internal architecture label, not a literal `sudo`):

```text
ClawdianShield/                        ← main project
ClawdianShield/core/observers/         ← (S) file_observer, log_observer, normalizer, correlation
ClawdianShield/core/models/            ← (U) NormalizedEvent, RunContext, ExecutionReceipt schemas
ClawdianShield/core/evaluation/        ← (D) coverage_scorer.py, gap_analyzer.py
ClawdianShield/core/intelligence/      ← (O) gemini_client.py, confluence_publisher.py
ClawdianShield/core/runner/            ← executor.py, atomic_converter.py
ClawdianShield/platform/dashboard/     ← FastAPI server + vanilla JS SPA (server.py + static/)
ClawdianShield/platform/eval/          ← Agent benchmark plane (drop_agent.py, benchmark.py, adapters/)
ClawdianShield/platform/telemetry/     ← Phase 3 Splunk/Elastic forwarders (scaffolded, not wired)
ClawdianShield/engine/                 ← Docker victim container definition
ClawdianShield/scenarios/              ← scenario JSON (single-host/, atomic/)
ClawdianShield/evidence/               ← JSONL event streams (sensors write here)
ClawdianShield/reports/                ← exec_log.json + brief.json + benchmark.json per run
ClawdianShield/.env                    ← GEMINI_API_KEY lives here (never commit)
```

## Running the Dashboard

```bash
cd /d/MasterVault/SUDO/ClawdianShield
python3 -m dashboard.server --evidence-dir evidence --reports-dir reports
# Opens on http://localhost:8088
```

Kill the server via PowerShell: `Stop-Process -Id <PID> -Force`
Find PID: `netstat -ano | grep ":8088"`

## Python Environment

No venv — system Python 3.14.3 at `/c/Users/MyPC/AppData/Local/Microsoft/WindowsApps/python3`.
`fastapi`, `uvicorn`, `watchdog`, `python-dotenv`, `google-genai` are installed system-wide.

## Architecture (Actor → Observer → Intelligence)

```text
engine/scenarios/*.json
    ↓ engine/executor.py (docker exec into clawdian_victim)
Docker victim container (clawdian_victim)
    ↓ bind-mounts → victim_state/ + victim_logs/
Host sensors (file_observer, log_observer)
    ↓ JSONL → evidence/
FastAPI dashboard (server.py)
    ↓ WebSocket + REST
Browser dashboard (dashboard.js)
    ↓ GENERATE BRIEF → Gemini 2.5 Flash
Analyst brief (reports/<run_id>_brief.json)
```

## Agent Benchmark Plane

`platform/eval/` provides a drop-in evaluation harness for any SIEM/EDR agent:

- `drop_agent.py` — copies a binary into `clawdian_victim` via `docker cp` and starts it with `docker exec -d`
- `adapters/file_drain.py` — reads JSONL alerts from `victim_logs/agent_alerts.jsonl` (bind-mounted `/var/log/`)
- `benchmark.py` — joins alerts against `exec_log.json` ground truth; outputs TP/FN/FP + latency per technique
- `fake_agent.sh` — shell fixture that writes synthetic alerts; use to validate the pipeline before wiring a real agent

Benchmark results land in `reports/<run_id>_benchmark.json` and surface in the **Agent Benchmark** dashboard tab.

## Phase Status

- Phase 1 — Core Engine: **COMPLETE**
- Phase 2 — Dashboard + UKC visualization: **COMPLETE**
- Phase 2b — Gemini AI briefs: **COMPLETE**
- Phase 3 — Splunk HEC telemetry: **BACKLOG** (`ClawdianShield/telemetry/` scaffolded, not wired)
- Phase 4 — Scenario Expansion: **IN PROGRESS** — 12 new lab-safe scenarios (credential_hunting, lateral_movement, container_escape, ransomware_sim, web_shell, process_injection, etc.); full Atomic Red Team library in `scenarios/atomic/`; expand to 50+ hand-authored scenarios covering all MITRE kill-chain stages (Phase 3 backlog)
- Phase 5 — Agent Benchmark: **COMPLETE** (`platform/eval/`)
- Phase 6 — AI Red-Teaming (PyRIT): **COMPLETE** — AI Attacks tab in dashboard reads `evidence/ai_events.jsonl`; PyRIT targets `/brief` endpoint to test LLM analyst poisoning; expand PyRIT coverage to all ATLAS tactics (Phase 3 backlog)

## Rewind UI (Planned — Not Yet Built)

A future "Rewind" feature will replay a scenario run's event timeline interactively.
**If building the Rewind UI as a React component:**

- Use `react-grid-layout` for all dashboard panel layout — pinned grid, no free-floating elements
- Install: `npm install react-grid-layout`
- Panels must not overlap or reorder on resize
- Keep it inside `ClawdianShield/dashboard/` unless a separate `rewind/` app is justified

## Dashboard Stack (Current)

Vanilla JS — no React, no bundler. `dashboard.js` + `index.html` + `style.css`.

- Charts: Chart.js (CDN)
- UKC visualization: custom SVG in `renderKillChain()` — Stellar Cyber ring style, Pols (2017) 18-tactic model
- Do NOT introduce a bundler or framework without explicit instruction.

## Key Behaviors / Standing Rules

- The `orchestration.gemini_client` import in `server.py` tries `from ClawdianShield.orchestration.gemini_client` first (git root CWD), falls back to `from orchestration.gemini_client` (run from inside `ClawdianShield/`).
- `clawdian_victim` Docker container: restart with `docker start clawdian_victim`. Network mode is `none`.
- Scenario safety constraints must pass before executor runs. `dependency_swap` and `real_exploit_custom` are intentionally skipped in suite runs.
- Evidence JSONL is append-only. Collectors use polling (not inotify) for Windows host volume compatibility.
- Agent benchmark: `victim_logs/agent_alerts.jsonl` is the shared path (host side) for AUT alert output. The container sees it as `/var/log/agent_alerts.jsonl`. No compose changes needed.

## Do Not

- Do not commit `.env`, `reports/`, or `evidence/` — they are gitignored or contain keys/telemetry.
- Do not start Splunk (`clawdian_splunk`) — Phase 3 is backlog.
- Do not introduce honeypot/deception features — PatriotPot/HoneyBomb already covers that plane.
- Do not add SIEM integrations yet — CerberusMesh covers that; Phase 3 is post-Docker-validation.
- Do not pad responses or explain ATT&CK/SIEM/forensics basics to the user (Kevin). He teaches this.
