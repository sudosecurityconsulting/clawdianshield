# ClawdianShield — CLAUDE.md
# Git root: d:/MasterVault/SUDO
# All paths in this file are relative to the git root unless stated otherwise.

---

## ⚠️ PROJECT ISOLATION — READ FIRST ⚠️

This repo is **ClawdianShield ONLY**. There are multiple active projects in this workspace:

| Project | Location | Purpose |
|---|---|---|
| **ClawdianShield** | `claudianShield/` | Detection engineering / adversary emulation platform |
| **Terminus Task(s)** | WSL Ubuntu: `~/totp-replay-audit/`, `~/task2/`, `~/task3/` | Snorkel Terminal Bench submissions (completely separate) |

### Hard Rules to Prevent Cross-Contamination
1. **Never reference ClawdianShield code, architecture, or domain when working on a Terminus task.** They are unrelated projects.
2. **Never reference Terminus task code when working on ClawdianShield.** 
3. **Each Terminus task is also isolated from every other Terminus task.** Task A's Dockerfile, oracle, and tests must never reference Task B.
4. **When asked to work on a Terminus task, confirm the task name and path first.** Never assume which task is active.
5. **The Terminus knowledge base lives at:** `terminus-knowledge-base.md` (this repo root) — **READ IT BEFORE STARTING ANY TERMINUS WORK.** It contains critical Harbor platform rules, mount path requirements, common failure modes, and local Docker testing procedures.
6. **Do not pad responses or explain security basics to Kevin.** He is a cybersecurity professional and Terminus EC.

### Active Terminus Tasks
<!-- Update this list when tasks change state -->
- [x] **Task 1 — TOTP Replay Audit** (`~/totp-replay-audit/`) — Submission `42f1a6ed`, EVALUATION_PENDING
- [x] **Task 2 — Auth Anomaly Detection** (`~/task2/`) — Submission `6cab4d62`, EVALUATION_PENDING
- [ ] **Task 3 — IDOR Audit** (`~/task3/`) — Locally validated, awaiting submission slot (E006 concurrency limit)

### STB CLI (runs in WSL Ubuntu)
```bash
stb submissions list --project-id bfe79c33-8ab0-4061-9849-08d3207c9927
stb submissions feedback <submission-id>
```

---

## Zero-Fail Pathing
**Always operate from the git root: `d:/MasterVault/SUDO`**
- Never assume a subdirectory as CWD. If unsure, run `git rev-parse --show-toplevel` to verify.
- The repo has 70+ directories. Do not navigate by intuition. Use explicit absolute paths.
- Shell: Git Bash (Unix syntax). Use forward slashes. `/d/MasterVault/SUDO/` not `D:\`.

Key paths:
```
claudianShield/                  ← main project
claudianShield/dashboard/        ← FastAPI server + vanilla JS frontend
claudianShield/dashboard/static/ ← dashboard.js, index.html, style.css
claudianShield/intelligence/     ← gemini_client.py (AI brief generator)
claudianShield/runner/           ← executor.py (scenario engine)
claudianShield/scenarios/        ← JSON scenario files
claudianShield/evidence/         ← JSONL event streams (collectors write here)
claudianShield/reports/          ← exec_log.json + brief.json per run
claudianShield/.env              ← GEMINI_API_KEY lives here (never commit)
```

## Running the Dashboard
```bash
cd /d/MasterVault/SUDO/claudianShield
python3 -m dashboard.server --evidence-dir evidence --reports-dir reports
# Opens on http://localhost:8088
```
Kill the server via PowerShell: `Stop-Process -Id <PID> -Force`
Find PID: `netstat -ano | grep ":8088"`

## Python Environment
No venv — system Python 3.14.3 at `/c/Users/MyPC/AppData/Local/Microsoft/WindowsApps/python3`.
`fastapi`, `uvicorn`, `watchdog`, `python-dotenv`, `google-genai` are installed system-wide.

## Architecture (Actor → Observer → Intelligence)
```
Scenarios (JSON)
    ↓ executor.py (docker exec into clawdian_victim)
Docker victim container (clawdian_victim)
    ↓ bind-mounts → victim_state/ + victim_logs/
Host collectors (file_observer, log_observer)
    ↓ JSONL → evidence/
FastAPI dashboard (server.py)
    ↓ WebSocket + REST
Browser dashboard (dashboard.js)
    ↓ GENERATE BRIEF → Gemini 2.5 Flash
Analyst brief (reports/<run_id>_brief.json)
```

## Phase Status
- Phase 1 — Core Engine: **COMPLETE**
- Phase 2 — Dashboard + UKC visualization: **COMPLETE**
- Phase 2b — Gemini AI briefs: **COMPLETE**
- Phase 3 — Splunk HEC telemetry: **BACKLOG** (`claudianShield/telemetry/` scaffolded, not wired)

## Rewind UI (Planned — Not Yet Built)
A future "Rewind" feature will replay a scenario run's event timeline interactively.
**If building the Rewind UI as a React component:**
- Use `react-grid-layout` for all dashboard panel layout — pinned grid, no free-floating elements
- Install: `npm install react-grid-layout`
- Panels must not overlap or reorder on resize
- Keep it inside `claudianShield/dashboard/` unless a separate `rewind/` app is justified

## Dashboard Stack (Current)
Vanilla JS — no React, no bundler. `dashboard.js` + `index.html` + `style.css`.
- Charts: Chart.js (CDN)
- UKC visualization: custom SVG in `renderKillChain()` — Stellar Cyber ring style, Pols (2017) 18-tactic model
- Do NOT introduce a bundler or framework without explicit instruction.

## Key Behaviors / Standing Rules
- The `intelligence.gemini_client` import in `server.py` must be `from intelligence.gemini_client` (not `from claudianShield.intelligence.gemini_client`) — server runs from inside `claudianShield/`.
- `clawdian_victim` Docker container: restart with `docker start clawdian_victim`. Network mode is `none`.
- Scenario safety constraints must pass before executor runs. `dependency_swap` and `real_exploit_custom` are intentionally skipped in suite runs.
- Evidence JSONL is append-only. Collectors use polling (not inotify) for Windows host volume compatibility.

## Do Not
- Do not commit `.env`, `reports/`, or `evidence/` — they are gitignored or contain keys/telemetry.
- Do not start Splunk (`clawdian_splunk`) — Phase 3 is backlog.
- Do not introduce honeypot/deception features — PatriotPot/HoneyBomb already covers that plane.
- Do not add SIEM integrations yet — CerberusMesh covers that; Phase 3 is post-Docker-validation.
- Do not pad responses or explain ATT&CK/SIEM/forensics basics to the user (Kevin). He teaches this.
