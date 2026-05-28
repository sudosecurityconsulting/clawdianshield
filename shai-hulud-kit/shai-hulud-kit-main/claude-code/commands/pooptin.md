---
description: Supply chain audit — scans installed packages and project files for Shai-Hulud / TeamPCP indicators
argument-hint: "[quick|project|deep|status] [--deep] [--json]"
---

# /pooptin — Supply Chain Audit

You are running the Shai-Hulud / TeamPCP supply chain audit. This protects the user from the active npm + PyPI compromise campaign.

## What to do

Parse the user's argument (after `/pooptin`):

| Arg | Behavior |
|---|---|
| (none) or `quick` | Run quick scan of current project, <30s |
| `project` | Scan a specific path the user provides |
| `deep` | Full machine scan (~2-5 min, env vars, all dev dirs) |
| `status` | Show last scan summary |
| `--json` | Add to any of the above for machine-readable output |

## Script location

The audit script lives at one of these locations (check in this order):

1. `~/.shai-hulud/shai-hulud-audit.ps1` (PowerShell, preferred)
2. `~/.shai-hulud/shai-hulud-audit.sh` (bash fallback)
3. `<project>/scripts/shai-hulud-audit.{ps1,sh}` (project-local copy)

## Invocation

Prefer the OS-native script. On Windows or anywhere `pwsh` exists, use the `.ps1`. On macOS/Linux without pwsh, use the `.sh`.

```bash
# macOS / Linux
~/.shai-hulud/shai-hulud-audit.sh --mode quick

# Windows
& "$env:USERPROFILE\.shai-hulud\shai-hulud-audit.ps1" -Mode quick

# Either OS with pwsh
pwsh ~/.shai-hulud/shai-hulud-audit.ps1 -Mode quick
```

For JSON output (when you need to parse the result):
```bash
~/.shai-hulud/shai-hulud-audit.sh --mode quick --json
```

## Project-level scan

If `<project>/scripts/detect_compromise.py` exists, run it **in addition to** the machine-level scan. It catches Python-specific patterns (PEP 508 dep parsing, `.pth` exec, workflow tamper) that the machine-level scanner doesn't deep-scan.

```bash
python <project>/scripts/detect_compromise.py --root <project>
```

Combine the two exit codes: if either is ≥2, treat as alert.

## Reporting back to the user

After running the audit:

1. **If clean (exit 0):** brief confirmation. "No findings. Safe to proceed."
2. **If warnings (exit 1):** list the warnings, suggest review but don't block.
3. **If alerts (exit 2):** highlight the alerts in red, list specific findings, **explicitly tell the user not to commit and to consider their machine potentially compromised**. Suggest the actions in `docs/IOC_CHECKLIST.md` if present.
4. **If script error (exit 3):** show stderr, suggest checking that the script exists and dependencies are installed (curl, jq, python3 for bash; PS 5.1+ for PowerShell).

## When NOT to invoke

- The user is asking a question about supply chain security (just answer it, don't run a scan)
- The user is troubleshooting an unrelated issue
- The audit was just run in this session and nothing has changed

## Notes on cost

- Quick scan: ~10-30 seconds, low API usage
- Deep scan: 2-5 minutes, includes OSV.dev batch queries (free, no key needed)
- Cache is 15 minutes by default — repeated quick scans are nearly instant
- Audit results are stored locally at `~/shai-hulud-audit/audit_<timestamp>_<mode>/`
