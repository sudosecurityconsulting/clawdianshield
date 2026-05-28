# Hardening Guide

Operational commands for every common supply chain task. Each command is verified against current tooling (pip-audit, osv-scanner, pip-tools as of late May 2026).

## §1 Initial setup

### Generate hash-pinned lockfile

```bash
pip install pip-tools
pip-compile --generate-hashes --output-file=requirements-hashed.txt requirements.txt
```

Regenerate after every dep change. The hashes detect post-publish tampering (a malicious republish under the same version fails `--require-hashes` verification).

For multi-platform projects, generate one lockfile per platform:

```bash
# On Linux
pip-compile --generate-hashes --output-file=requirements-hashed-linux.txt requirements.txt
# On Windows
pip-compile --generate-hashes --output-file=requirements-hashed-windows.txt requirements.txt
```

### Install from hashed lockfile

```bash
pip install --require-hashes -r requirements-hashed.txt
```

## §2 Daily audit

### Quick local audit

```bash
./scripts/audit_deps.sh           # macOS/Linux
.\scripts\audit_deps.bat           # Windows
```

Walks all `requirements*.txt` files, runs `pip-audit` on each.

### Project-level scan

```bash
python scripts/detect_compromise.py
```

Catches PEP 508 dep declarations against known-compromised list, `.pth` exec, workflow tamper, git remote C2.

### Machine-level scan

```bash
~/.shai-hulud/shai-hulud-audit.sh --mode quick    # macOS/Linux
& "$env:USERPROFILE\.shai-hulud\shai-hulud-audit.ps1" -Mode quick    # Windows
```

Or via slash command:
```
/pooptin quick
```

## §3 Adding a new dependency

Always vet first in the sandbox:

```bash
./scripts/sandbox_install.sh requests==2.32.3
```

This creates `.sandbox-venv/`, installs with `--only-binary :all:` (no `setup.py` execution), and runs `pip-audit`. If clean, then promote:

```bash
echo "requests==2.32.3" >> requirements.txt
pip-compile --generate-hashes --output-file=requirements-hashed.txt requirements.txt
git add requirements.txt requirements-hashed.txt
git commit -m "Add requests==2.32.3"
```

## §4 Upgrading a dependency

Same flow:

```bash
./scripts/sandbox_install.sh requests==2.32.4
# If clean:
# Edit requirements.txt to bump
pip-compile --generate-hashes --output-file=requirements-hashed.txt requirements.txt
```

For batch upgrades (e.g., monthly):

```bash
pip-compile --upgrade --generate-hashes --output-file=requirements-hashed.txt requirements.txt
pip install --require-hashes -r requirements-hashed.txt
./scripts/audit_deps.sh
python -m pytest    # run your test suite
```

## §5 CI integration

The workflow at `.github/workflows/supply-chain-audit.yml` runs:

- **`pip-audit`** — PyPA advisory cross-check
- **`audit-installed-venv`** — per-manifest ephemeral venv (catches transitive masking)
- **`osv-scanner`** — Google's independent DB
- **`detect-compromise`** — runs `detect_compromise.py` + tests

Triggers: every push, every PR, nightly cron at 07:00 UTC.

## §6 Pre-commit hook

Install:

```bash
cp git-hooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

Blocks commits on critical findings. Skip in an emergency:

```bash
git commit --no-verify -m "..."
```

Don't make that a habit.

## §7 Dependabot

Copy `ci/dependabot.yml` to `.github/dependabot.yml`. Then in repo Settings → Code security and analysis, enable:

- Dependabot alerts
- Dependabot security updates
- Dependabot version updates

Behavior:
- Weekly grouped non-security PRs (Monday 06:00 UTC, low noise)
- Immediate ungrouped security PRs (so CVEs don't sit in a batch)

## §8 Common remediation patterns

### Vulnerable transitive dep

```bash
# Find the chain
pip show <vulnerable-package>
pipdeptree --reverse --packages <vulnerable-package>

# Add a constraint to bump it
echo "<vulnerable-package>>=<safe-version>" >> requirements.txt
pip-compile --generate-hashes --output-file=requirements-hashed.txt requirements.txt
```

### `.pth` file with executable code

If `detect_compromise.py` flagged a `.pth` file:

1. **Do not commit.**
2. Identify the package that installed it: `pip show <package-name>` then check the package files.
3. If it's legitimate (e.g., editable install via `setuptools`), add the exact content to `PTH_ALLOWLIST_EXACT` in `detect_compromise.py`.
4. If it's not legitimate, treat the machine as potentially compromised. Run `~/.shai-hulud/shai-hulud-audit.sh --mode deep`.

### Suspicious workflow file

If `detect_compromise.py` flagged a workflow:

1. **Check git log on the file:** `git log -p .github/workflows/<file>`
2. Compare against last known-good commit.
3. If the change is unauthorized, revert immediately and run a deep audit.
4. If the change is legitimate (e.g., a setup script you wrote), adjust the regex or move the install to a separate file pinned by hash.

### Compromised dep declared in `requirements.txt`

1. **Remove it from `requirements.txt`.**
2. Find replacement or pin to a pre-compromise version (consult OSV.dev advisory).
3. Regenerate `requirements-hashed.txt`.
4. Run `./scripts/sandbox_install.sh -r requirements.txt` to verify.
5. Treat the machine as potentially compromised if the package was installed at any point. See `IOC_CHECKLIST.md`.

## §9 Tooling versions known to work

As of late May 2026:

| Tool | Version | Notes |
|---|---|---|
| pip-audit | 2.7+ | `--require-hashes` requires hashed lockfile; `--no-deps` incompatible with range pins |
| pip-tools | 7.4+ | `--generate-hashes` for tamper-resistant lockfiles |
| osv-scanner | 2.3.5 | Step action path: `google/osv-scanner-action/osv-scanner-action@v2.3.5` (NOT the reusable workflow path) |
| OSV.dev API | v1 | Free, no key, `https://api.osv.dev/v1/querybatch` |
| Python | 3.11+ | 3.12 ships without `_tkinter` on some platforms; 3.11 is the safer default |
