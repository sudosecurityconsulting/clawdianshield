# Contributing to ClawdianShield

Thank you for your interest. ClawdianShield is a defensive security-research platform — contributions should stay within that boundary.

## How to Contribute

1. **Open an issue first** — describe the detection gap, emulation chain, or scoring change you have in mind. This keeps changes reviewable and on-mission.
2. **Fork the repo** and create a branch from `main`:
   ```bash
   git checkout -b cls-<issue-id>/short-description
   ```
3. **Commit with context.** Reference the issue in your commit messages (`refs #42`).
4. **Open a Pull Request** against `main`. Summarize what changed and why.

## Branch Naming

| Prefix | Use |
|--------|-----|
| `cls-<id>/` | Feature or fix tracked by a GitHub issue |
| `docs/` | Documentation-only changes |
| `chore/` | Tooling, CI, dependency bumps |

## What We Need

- **Detection Engineers:** Challenge the scoring weights. Add emulation chains that expose detection gaps.
- **DFIR professionals:** New scenario JSON for attacker techniques that leave distinctive forensic artifacts.
- **Cloud Architects:** Phase 3b+ SIEM integrations (Splunk HEC, Sentinel CEF) — see `platform/telemetry/`.

## What's Out of Scope

- Real exploit payloads, credential attack logic, or anything that crosses into operationally abusive territory.
- Deception/honeypot features — that's a separate project (PatriotPot).
- SIEM integrations beyond the Elastic stack until Phase 3 Docker validation is complete.

## Code Style

Python only. Follow PEP 8. No new dependencies without a clear justification in the PR description.

## Questions

Open an issue or reach out on [LinkedIn](https://www.linkedin.com/in/kevin-landry-cybersecurity).
