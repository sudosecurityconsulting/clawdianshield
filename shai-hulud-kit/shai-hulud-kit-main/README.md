# Shai-Hulud Kit

A drop-in supply chain audit + hardening toolkit for the active **Shai-Hulud / TeamPCP** campaign (npm + PyPI, ongoing since April 2026).

## What this is

One folder. Point Claude Code at it. Claude Code reads `INTEGRATION.md` and installs the right pieces for your setup — whether you have nothing yet, partial hardening already, or just want the `/pooptin` slash command globally.

Two layers, both included:

- **Machine-level audit** (`scripts/shai-hulud-audit.{ps1,sh}`) — scans installed packages anywhere on your machine, queries OSV.dev live, checks system IOCs (DNS, env vars, git anomalies, GitHub exfil repos).
- **Project-level audit** (`scripts/detect_compromise.py` v1.1) — in-tree Python scanner with 9 checks: PEP 508 regex, npm package@version matching, `.pth` exec, workflow tamper, git remote C2 + IP, `.claude/`/`.vscode/` persistence detection, spoofed commit authors, campaign string markers, self-check. 64 property tests included. SARIF 2.1.0 output for GitHub Security tab.

**New in v1.1** (uses [copyleftdev/mini-shai-hulud-dragnet](https://github.com/copyleftdev/mini-shai-hulud-dragnet) IOC data):
- Detects TeamPCP's Claude Code persistence vector (`.claude/execution.js`, `.claude/setup.mjs`, `SessionStart_hook` in `.claude/settings.json`)
- npm package@version matching from `package.json` and `package-lock.json`
- C2 IP `94.154.172.43` (AS209101 IP Vendetta Inc.) and apex domain `checkmarx.cx`
- Campaign string markers (`LongLiveTheResistanceAgainstMachines`, `__DAEMONIZED`, etc.)
- Spoofed git commit author detection
- SARIF 2.1.0 output — CI workflow uploads to GitHub Security tab

## Quickstart for the user

Drop this folder somewhere accessible. Then in any Claude Code session:

```
look at /path/to/shai-hulud-kit and integrate it. set up /pooptin globally
and also wire the project tools into the current project.
```

Claude Code will read `INTEGRATION.md`, assess your OS / project type / existing tools, and install the right pieces. It won't overwrite anything without asking.

For a friend starting from scratch:

```
look at /path/to/shai-hulud-kit. i have nothing set up. install everything
relevant for my system.
```

## What you get

After install:

- **`/pooptin`** slash command in Claude Code (any project) — invokes the machine audit
- **`/pooptin quick`** — current-project scan, <30s, runs on pre-commit
- **`/pooptin deep`** — full machine scan including env vars, credential file inventory
- **`/pooptin status`** — last scan summary
- **Pre-commit hook** that blocks commits on critical findings
- **GitHub Actions workflow** with pip-audit + per-manifest ephemeral venv + osv-scanner
- **Dependabot config** with weekly grouped + immediate security PRs
- **4 docs** for threat model, hardening, IOC response, and solo-dev hygiene

## Layout

```
shai-hulud-kit/
├── INTEGRATION.md              ← Claude Code reads this first
├── README.md                   ← You're here
├── scripts/
│   ├── shai-hulud-audit.ps1   ← Machine audit (PowerShell / pwsh)
│   ├── shai-hulud-audit.sh    ← Machine audit (bash, macOS/Linux)
│   ├── detect_compromise.py   ← Project audit (Python, all OS)
│   ├── audit_deps.{sh,bat}    ← Local pip-audit driver
│   └── sandbox_install.{sh,bat} ← Isolated dep install
├── tests/
│   └── test_detect_compromise.py  ← 44 property tests
├── claude-code/
│   ├── commands/pooptin.md    ← Slash command
│   └── CLAUDE-snippet.md      ← Project CLAUDE.md addition
├── git-hooks/
│   ├── pre-commit             ← bash version
│   └── pre-commit.ps1         ← PowerShell version
├── ci/
│   ├── supply-chain-audit.yml ← GitHub Actions workflow
│   └── dependabot.yml         ← Dependabot config
└── docs/
    ├── THREAT_MODEL.md
    ├── HARDENING.md
    ├── IOC_CHECKLIST.md
    └── SINGLE_DEV_CHECKLIST.md
```

## Manual install (without Claude Code)

If you'd rather install by hand or you don't have Claude Code yet:

### Global (machine-level audit)

```bash
# macOS / Linux
mkdir -p ~/.shai-hulud
cp scripts/shai-hulud-audit.sh ~/.shai-hulud/
chmod +x ~/.shai-hulud/shai-hulud-audit.sh
~/.shai-hulud/shai-hulud-audit.sh --mode quick
```

```powershell
# Windows
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.shai-hulud" | Out-Null
Copy-Item scripts/shai-hulud-audit.ps1 "$env:USERPROFILE\.shai-hulud\"
& "$env:USERPROFILE\.shai-hulud\shai-hulud-audit.ps1" -Mode quick
```

### Per-project (Python audit)

```bash
# Copy the script and tests into your repo
cp scripts/detect_compromise.py <your-repo>/scripts/
cp tests/test_detect_compromise.py <your-repo>/tests/

# Run it
python <your-repo>/scripts/detect_compromise.py --root <your-repo>

# Run tests to verify
python -m unittest <your-repo>/tests/test_detect_compromise.py
```

### CI

Copy `ci/supply-chain-audit.yml` to `<your-repo>/.github/workflows/`.
Copy `ci/dependabot.yml` to `<your-repo>/.github/`.

### Pre-commit hook

```bash
# Unix
cp git-hooks/pre-commit <your-repo>/.git/hooks/pre-commit
chmod +x <your-repo>/.git/hooks/pre-commit
```

```powershell
# Windows (PowerShell variant)
Copy-Item git-hooks/pre-commit.ps1 <your-repo>/.git/hooks/pre-commit.ps1
```

## Threat context (late May 2026)

| Date | Wave | Impact |
|---|---|---|
| Apr 2026 | Bitwarden CLI | `@bitwarden/cli` npm |
| May 11 | TanStack wave | 42 `@tanstack/*` packages (SLSA-attested) |
| May 12 | **Toolkit open-sourced** | GitHub + BreachForums |
| May | durabletask + disk wiper | PyPI (destructive) |
| May 19 | AntV wave | 323 packages in 22 minutes |

**1,055+ malicious versions across 502+ unique packages** as of late May. With the toolkit public, copycat waves are now daily.

## Exit codes

All audit scripts use the same exit codes:

- `0` — clean, safe to commit
- `1` — warnings present (review before commit)
- `2` — alerts present (do not commit, treat machine as potentially compromised)
- `3` — script error (bad args, missing deps, etc.)

Pre-commit hook blocks on exit code 2.

## What this kit will not do

- Auto-rotate credentials (too risky to automate)
- Auto-remove compromised packages (transitive deps need careful handling)
- Phone home with telemetry (everything stays local)
- Self-update (review before upgrading so you trust what's running)

## License

Public domain / use as you wish. No warranty.
