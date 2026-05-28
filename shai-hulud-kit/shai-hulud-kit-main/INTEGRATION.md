# INTEGRATION.md — Instructions for Claude Code

> **You are Claude Code, and the user has pointed you at this folder.** Read this file first. It tells you what's here, how to assess the user's environment, and what to install. Don't skip steps. Don't dump everything in at once. Ask when unsure.

---

## What this kit is

A defensive toolkit for the active **Shai-Hulud / TeamPCP** supply chain campaign (npm + PyPI, ongoing since April 2026). It combines:

- **Machine-level audit** (`scripts/shai-hulud-audit.{ps1,sh}`) — scans installed packages anywhere on the system against live OSV.dev data
- **Project-level Python audit** (`scripts/detect_compromise.py` v1.1) — in-tree scanner with 9 checks: PEP 508 regex, npm package@version matching, `.pth` exec, workflow tamper, git remote C2 + IP, `.claude/` and `.vscode/` persistence detection, spoofed commit author, campaign string markers, self-check. SARIF 2.1.0 output for GitHub Security tab.
- **CI workflow templates** (`ci/`) — pip-audit + per-manifest ephemeral venv + osv-scanner + SARIF upload
- **Pre-commit hooks** (`git-hooks/`) — block commits on critical findings
- **Slash command** (`claude-code/commands/pooptin.md`) — `/pooptin` invocation from any Claude Code session
- **Docs** (`docs/`) — threat model, hardening guide, IOC checklist, single-dev hygiene

Two layers solving two different problems. Don't pick one — they're complementary.

**Critical note on Claude Code persistence:** TeamPCP specifically targets Claude Code via `.claude/settings.json` `SessionStart_hook` + dropped payload files at `.claude/execution.js` and `.claude/setup.mjs`. The project-level scanner detects this; if Claude Code finds these files during integration, treat as a confirmed compromise (see `docs/IOC_CHECKLIST.md`).

---

## Step 1: Read the user's intent

The user pointed you here. What did they say?

| User said | Plan |
|---|---|
| "Install globally" or "make /pooptin work everywhere" | Global install only (Section 4A) |
| "Add to this project" or "wire this up" | Project install only (Section 4B) |
| "Both" or "set up everything" | Both (Section 4A then 4B) |
| "Share with a friend" or "I have nothing" | Full install + verification (Section 4A + 4B + 4C) |
| Anything ambiguous | **ASK before doing anything** |

---

## Step 2: Assess the environment

Run these checks silently before proposing a plan:

### OS detection
```bash
# Check OS — affects which audit script to install
uname -s 2>/dev/null   # Darwin / Linux / MINGW* / MSYS*
# Or for Windows:
echo $env:OS           # PowerShell: "Windows_NT"
```

### Tooling check
- `pwsh --version` — PowerShell 7+ available? (cross-platform; preferred for the .ps1 audit script)
- `powershell.exe --version` — Windows PowerShell fallback?
- `python3 --version` and `python --version` — which Python is on PATH?
- `pip-audit --version` — already installed?
- `osv-scanner --version` — already installed?
- `git --version` — in a git repo?

### Claude Code install state
- `~/.claude/commands/` exists? → user has Claude Code installed globally
- `~/.shai-hulud/` exists with files? → **prior install — read what's there before overwriting**

### Project detection (if relevant)
Look in the project directory for:
- `package.json` → npm project
- `requirements*.txt`, `pyproject.toml`, `Pipfile`, `uv.lock`, `poetry.lock` → Python project
- `.git/` → git-managed (pre-commit hook possible)
- `.github/workflows/` → uses GitHub Actions (CI integration possible)
- `CLAUDE.md` → has Claude Code conventions (read it)
- Existing `scripts/detect_compromise.py` or similar → **partial setup; merge, don't replace**
- Existing `docs/security/` → has security docs (augment, don't overwrite)

### Surface the assessment to the user

Before installing anything, tell the user what you found and what you're about to do. Example:

> I see you're on macOS, working in a Python project at `~/work/myapp` with a git repo and existing CI workflows. You don't have `/pooptin` installed globally yet. Here's what I propose:
>
> **Global:**
> - Install `shai-hulud-audit.sh` to `~/.shai-hulud/`
> - Install `/pooptin` slash command to `~/.claude/commands/`
>
> **Project (`~/work/myapp`):**
> - Add `scripts/detect_compromise.py` and its tests
> - Add `.github/workflows/supply-chain-audit.yml` (new file — won't touch your existing workflows)
> - Add `.git/hooks/pre-commit` (or merge if you already have one)
> - Append supply-chain section to `CLAUDE.md`
> - Add `docs/security/` with 4 reference docs
>
> Proceed? Or want to skip any of these?

---

## Step 3: Install rules

### Never overwrite without asking
- If a target file exists, read it first.
- Identical content → skip silently.
- Different content → show the user a brief summary of differences and ask before replacing.
- `CLAUDE.md` → **APPEND only**, never overwrite.

### Never install partially-completed work
- If a step fails (e.g., chmod fails, mkdir denied), stop and report. Don't leave half-installed files.

### Respect existing structure
- If the project has `scripts/` already, use it. If not, create it.
- If the project's CI workflows are in a non-standard location, ask before adding to `.github/workflows/`.
- If the user's git hooks dir is overridden (`core.hooksPath`), respect that.

### Adapt to project conventions
- If the project uses `uv`, generate `uv.lock` hashes instead of `pip-compile`.
- If the project uses `poetry`, suggest `poetry export` for hash-pinned files.
- If the project has its own pre-commit framework (`pre-commit`, `lefthook`), suggest integrating there instead of overwriting `.git/hooks/`.

---

## Step 4: Installation procedures

### 4A. Global install (machine-level)

Target locations:
- Windows: `%USERPROFILE%\.shai-hulud\` and `%USERPROFILE%\.claude\commands\`
- macOS/Linux: `~/.shai-hulud/` and `~/.claude/commands/`

Steps:
1. Create `~/.shai-hulud/` if missing.
2. Copy the **right** audit script for the OS:
   - Windows or anywhere with `pwsh`: `scripts/shai-hulud-audit.ps1`
   - macOS/Linux without `pwsh`: `scripts/shai-hulud-audit.sh` (chmod +x)
   - Optionally copy both — they coexist.
3. Create `~/.claude/commands/` if missing.
4. Copy `claude-code/commands/pooptin.md` to `~/.claude/commands/pooptin.md`.
5. Verify: run `/pooptin status` (it'll say "no prior scan found" — that's correct on first install).

### 4B. Project install (project-level)

Only do this if the user is in a project directory. **Verify** with the user which directory before writing files.

For a **Python project**:
1. Create `scripts/` if missing. Copy:
   - `scripts/detect_compromise.py` → `<project>/scripts/`
   - `scripts/audit_deps.sh` and `.bat` → `<project>/scripts/`
   - `scripts/sandbox_install.sh` and `.bat` → `<project>/scripts/`
2. Create `tests/` if missing. Copy:
   - `tests/test_detect_compromise.py` → `<project>/tests/`
3. If `.github/workflows/` exists, **read existing workflows first**:
   - If no supply chain audit workflow exists → copy `ci/supply-chain-audit.yml`.
   - If one exists → propose merging the jobs from this kit's workflow.
4. If `.github/dependabot.yml` doesn't exist → copy `ci/dependabot.yml`.
   - If it exists → propose merging the config (don't overwrite).
5. Install pre-commit hook:
   - If no `.git/hooks/pre-commit` exists → copy `git-hooks/pre-commit`, chmod +x.
   - If one exists → propose appending the audit invocation.
6. Append `claude-code/CLAUDE-snippet.md` content to project's `CLAUDE.md` (create if missing).
7. Create `docs/security/` if missing. Copy:
   - `docs/THREAT_MODEL.md` → `docs/security/SUPPLY_CHAIN_THREAT_MODEL.md`
   - `docs/HARDENING.md` → `docs/security/HARDENING.md`
   - `docs/IOC_CHECKLIST.md` → `docs/security/IOC_DETECTION_CHECKLIST.md`
   - `docs/SINGLE_DEV_CHECKLIST.md` → `docs/security/SINGLE_DEV_CHECKLIST.md`

For an **npm-only project** (no Python):
- Skip `detect_compromise.py` and `audit_deps.sh`.
- Still install pre-commit hook (it invokes the global audit script).
- Install CI workflow with Python jobs disabled or removed.
- Append CLAUDE-snippet.

For a **mixed project** (Python + npm): full install.

For a **non-project directory**: don't install project files. Suggest global-only install.

### 4C. Verification

After install:
1. Tell the user what was created/modified — concrete list, paths.
2. Suggest a verification command: `/pooptin quick` (global) or `./scripts/detect_compromise.py` (project).
3. Show the next-actions list:
   - Add user's GitHub username to `CLAUDE.md` if they want exfil-repo checks
   - Generate `requirements-hashed.txt` if the project doesn't have one (command in `docs/HARDENING.md`)
   - Optionally enable Dependabot in repo settings
   - Run the audit once interactively before relying on the pre-commit hook

---

## Step 5: When to ask vs decide

**Decide silently** (don't bother the user):
- Which OS-appropriate script to install
- Whether to create missing directories
- Whether to chmod +x scripts on Unix
- Whether to add `.shai-hulud-cache/` to `.gitignore` if you create cache files

**Ask the user** (one question at a time, ideally):
- Which project to install into (if multiple candidates or you're unsure of cwd)
- Whether to overwrite a non-identical existing file
- Which Python version to target (if multiple installed and project doesn't pin)
- Whether to merge into an existing CI workflow vs create a new one
- Whether to install pre-commit hook now or wait
- Whether to share their GitHub username for exfil-repo checks

**Always show before doing**:
- Any file overwrite
- Any modification to `CLAUDE.md`, CI workflows, `.gitignore`, `dependabot.yml`

---

## Component reference

### `scripts/`
| File | Purpose | Platform |
|---|---|---|
| `shai-hulud-audit.ps1` | Machine-level audit, 3 modes (quick/project/deep), OSV.dev live query, structural IOC checks | Windows (PS 5.1+) or any OS with `pwsh` 7+ |
| `shai-hulud-audit.sh` | Same audit, bash port | macOS / Linux |
| `detect_compromise.py` | Project-level Python audit: PEP 508 regex, `.pth` exec check, workflow tamper check, git remote redaction | Python 3.8+ cross-platform |
| `audit_deps.sh` / `.bat` | Local pip-audit driver across all `requirements*.txt` | Unix / Windows |
| `sandbox_install.sh` / `.bat` | Install a dep into disposable venv with `--only-binary :all:`, `--require-hashes` when possible | Unix / Windows |

### `tests/`
| File | Purpose |
|---|---|
| `test_detect_compromise.py` | Property tests covering bypass classes for each regex in `detect_compromise.py` |

### `claude-code/`
| File | Purpose |
|---|---|
| `commands/pooptin.md` | Claude Code slash command. Goes to `~/.claude/commands/pooptin.md` |
| `CLAUDE-snippet.md` | Block to append to project `CLAUDE.md` files |

### `git-hooks/`
| File | Purpose |
|---|---|
| `pre-commit` | bash pre-commit hook — runs both global audit and `detect_compromise.py` if present |
| `pre-commit.ps1` | PowerShell-only pre-commit alternative for Windows-only setups |

### `ci/`
| File | Purpose |
|---|---|
| `supply-chain-audit.yml` | GitHub Actions workflow: 3 jobs (pip-audit + per-manifest venv + osv-scanner) |
| `dependabot.yml` | Dependabot config with weekly grouped + immediate security PRs |

### `docs/`
| File | Audience |
|---|---|
| `THREAT_MODEL.md` | Strategic — attack surface, what's defended, what's deferred |
| `HARDENING.md` | Operational — verified commands for every common task |
| `IOC_CHECKLIST.md` | Incident response — post-compromise checks, credential rotation order |
| `SINGLE_DEV_CHECKLIST.md` | Personal — pragmatic hygiene without enterprise tooling |

---

## Cross-platform notes

- **PowerShell scripts work on macOS/Linux** if `pwsh` (PowerShell 7+) is installed. They use no Windows-only cmdlets except the Sysmon log read in deep mode (which gracefully skips on other OSes).
- **bash scripts don't work on Windows cmd** but do work in Git Bash, WSL, and MSYS.
- **Python scripts work everywhere Python 3.8+ runs.**
- The slash command's `pooptin.md` invokes `pwsh` first, then falls back to `bash` on the `.sh` script. Either works.

---

## Threat context (as of late May 2026)

| Date | Wave | Impact |
|---|---|---|
| Mar 2026 | Trivy compromise | Aqua Security scanner |
| Apr 2026 | Bitwarden CLI | `@bitwarden/cli` npm |
| Apr 2026 | Mini Shai-Hulud (SAP) | `@cap-js/sqlite`, others |
| May 11, 2026 | TanStack wave | 42 `@tanstack/*` packages, SLSA-attested |
| May 12, 2026 | **Toolkit open-sourced** | GitHub + BreachForums "contest" |
| May 2026 | durabletask + disk wiper | PyPI, **destructive payload** |
| May 19, 2026 | AntV wave | 323 packages in 22 minutes |

Totals as of late May: **1,055+ malicious versions across 502+ unique packages**. The toolkit being public means copycat waves are now expected daily. PyPI exposure is escalating; npm still bears the brunt.

---

## What this kit will NOT do

- Auto-rotate credentials (manual remediation only — too risky to automate)
- Auto-remove compromised packages (transitive deps and lock files need careful handling)
- Phone home with telemetry (everything stays local)
- Self-update (review and pull new versions manually so you trust what you're running)
- Replace a real security program at a company (this is for solo and small-team devs)

---

## When all else fails

If anything in this folder is unclear, or the user's setup is too unusual to map to the above, **just ask the user what they want**. The kit is opinionated but it's also just files — you can install partially, in a different order, or not at all. The goal is the user being safer, not following these instructions to the letter.
