# Changelog

All notable changes to ClawdianShield are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Changed
- Refactored repository structure into `core/`, `platform/`, `scenarios/`, and `examples/` packages.
- Standardized project name to **ClawdianShield** across all paths, imports, and documentation.
- Deduplicated `AGENTS.md` / `CLAUDE.md` — `AGENTS.md` is now canonical; `CLAUDE.md` is a pointer.
- Relocated `PHASE3_STATUS.md` to `ClawdianShield/docs/`.
- Expanded `CONTRIBUTING.md` and `CODE_OF_CONDUCT.md` from stubs to full documents.
- Added `ARCHITECTURE.md` with full four-plane component and data-flow diagrams.
- Organized root clutter: stray ZIPs → `archive/`, cheat sheet → `docs/`, LNK scanner → `tools/`.

---

## [0.4.0] — 2026-06-07 · Phase 3a: Elastic Telemetry (live-verified)

### Added
- `platform/telemetry/forwarders/elastic_shipper.py` — JSONL → Elasticsearch bulk ingest via `helpers.bulk`, index-template creation, graceful no-op when `ELASTICSEARCH_URL` unset.
- `scripts/seed_all_scenarios.py` — walks `scenarios/single-host/*.json`, generates evidence JSONL, emits one exec-log per scenario, then bulk-ships all events to Elasticsearch.
- `docker/docker-compose.yml` — added `elasticsearch:8.11.0`, `kibana:8.11.0`, and `metricbeat` sidecar with persistent volume and healthchecks.
- `platform/intelligence/confluence_publisher.py` — aggregates exec_log + AI brief + evidence into styled HTML and publishes/updates via Confluence REST API.
- Kibana Discover pivot verified end-to-end: 164 events shipped from a `fim_burst_001` run, full `NormalizedEvent` shape queryable by collector/path/severity/run_id.

### Changed
- `requirements.txt`: added `elasticsearch>=8.11.0`, `atlassian-python-api>=3.41.0`.
- `.env.example`: documented `ELASTICSEARCH_URL`, `KIBANA_URL`, `CONFLUENCE_URL`, `CONFLUENCE_TOKEN`.

---

## [0.3.0] — 2026-05-27 · Dashboard Screenshots Refresh

### Changed
- Refreshed dashboard screenshots in `ClawdianShield/docs/` to reflect current UI state.
- Removed outdated screenshots from previous dashboard iterations.

---

## [0.2.0] — 2026-05-15 · Phase 2b: Gemini AI Incident Briefs

### Added
- `core/intelligence/gemini_client.py` — Gemini 2.5 Flash integration; generates SOC-grade markdown briefs per run (executive summary, attack chain narrative, gap assessment, risk rating).
- Model selector in the dashboard UI — choose Gemini model before brief generation.
- Brief caching in `reports/<run_id>_brief.json`; subsequent loads served from cache.
- `GET /api/brief/<run_id>` endpoint on the FastAPI server.

### Changed
- Dashboard SCENARIO RUNS tab now shows "GENERATE BRIEF" button per run; brief renders in a side panel with full markdown formatting.

---

## [0.1.0] — 2026-04-29 · Phase 1 + 2: Core Engine and SOC Dashboard

### Added
- `core/runner/executor.py` — subprocess engine, safety gate, behavior→command map; `docker exec` against `clawdian_victim`.
- Ten hand-authored scenario JSON files covering FIM burst, trusted binary abuse, config drift, auth abuse, remote exec, staging, persistence writes, anti-forensics, dependency swap, and a full intrusion storyline.
- `core/observers/file_observer.py` — watchdog `PollingObserver` on bind-mounted victim state; emits `NormalizedEvent` JSONL.
- `core/observers/log_observer.py` — log tailer with regex classification of PAM/auth events.
- `core/models/event_schema.py` — `NormalizedEvent` and `RunContext` Pydantic v2 schema.
- `core/evaluation/scorer.py` — five-dimension detection scoring (coverage, completeness, correlation, timeliness, analyst usefulness).
- `platform/dashboard/server.py` — FastAPI server with WebSocket live event push and REST API.
- Dashboard SPA: severity timeseries, event type distribution, UKC three-ring visualization (Pols, 2017 18-tactic model), ATT&CK technique map, scenario step trace, live event stream.
- `core/runner/atomic_converter.py` — converts Atomic Red Team YAML to ClawdianShield scenario JSON.
- Docker victim container (`clawdian_victim`) with network mode `none`; bind-mounts for `victim_state/` and `victim_logs/`.
- `docker-compose.yml` for victim container lifecycle.
- `platform/dashboard/seed_demo.py` — populates evidence and reports for offline dashboard demos (no Docker required).

[Unreleased]: https://github.com/sudosecurityconsulting/clawdianshield/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/sudosecurityconsulting/clawdianshield/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/sudosecurityconsulting/clawdianshield/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/sudosecurityconsulting/clawdianshield/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/sudosecurityconsulting/clawdianshield/releases/tag/v0.1.0
