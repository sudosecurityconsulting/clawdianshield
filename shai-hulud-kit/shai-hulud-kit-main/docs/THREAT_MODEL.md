# Supply Chain Threat Model

Strategic view of the Shai-Hulud / TeamPCP campaign and what this kit defends against.

## The campaign

**Active since:** April 2026
**Estimated actor:** Financially motivated criminal group (likely Russian/CIS-based — Russian locale acts as kill switch in payloads). Aliases include TeamPCP, DeadCatx3, PCPcat, ShellForce, CipherForce. Cats + Dune theming.
**Initial access:** Maintainer credential phishing → 2FA bypass → npm/PyPI publish access.
**Open-sourced:** May 12, 2026, on public GitHub + BreachForums as a "contest." Copycat waves now expected daily.

## Attack surface (Python)

| Vector | Description | Defended by |
|---|---|---|
| **sdist `setup.py` execution** | Source distributions execute arbitrary Python during install via `setup.py`. | `--only-binary :all:` in `sandbox_install` and CI |
| **`.pth` auto-execution** | Files matching `*.pth` in `site-packages` whose lines start with `import` are auto-executed at interpreter startup. Persistence vector. | `detect_compromise.py` `.pth` exec regex with MULTILINE + exact-match allowlist |
| **`__init__.py` side effects** | Package init code runs on every `import`. | Hash-pinned lockfile + audit-installed-venv |
| **Build hooks (PEP 517/518)** | `pyproject.toml` `build-system.requires` runs during build. | `--only-binary :all:` in sandbox |
| **CI workflow scripts** | `.github/workflows/*.yml` can be modified to `curl \| bash` malicious payloads. | `detect_compromise.py` workflow regex |
| **Compromised maintainer commits** | Backdoor in a popular package. | OSV.dev queries via pip-audit and osv-scanner |
| **C2 git remote** | Backdoored repo points HEAD at C2-controlled mirror. | `detect_compromise.py` git remote check |
| **`.claude/` persistence** | TeamPCP drops `.claude/execution.js` + `.claude/setup.mjs` and adds a `SessionStart_hook` to `.claude/settings.json` so payload re-runs on every Claude Code session start. Same pattern in `.vscode/`. | `detect_compromise.py` `check_persistence_paths`, audit script persistence-file check |
| **Spoofed commits** | Commits authored as `claude@users.noreply.github.com` or `dependabot[bot]@users.noreply.github.com` to bury malicious changes in legitimate-looking history. | `detect_compromise.py` `check_spoofed_commits` (WARN) |
| **Campaign string markers** | Hardcoded strings like `LongLiveTheResistanceAgainstMachines`, `__DAEMONIZED`, `A Mini Shai-Hulud has Appeared` appear in payload files. | `detect_compromise.py` `check_campaign_markers` |

## Attack surface (npm)

| Vector | Description | Defended by |
|---|---|---|
| **post-install scripts** | `package.json` `scripts.{pre,post}install` runs arbitrary code. | `shai-hulud-audit` flags packages with install scripts; `npm config set ignore-scripts true` (manual) |
| **Tarball tamper** | Attacker republishes under same version. | Lockfile (`package-lock.json`) hash verification |
| **Typosquats** | `react-dom` vs `reactdom`. | Out of scope for this kit; review your `package.json` |
| **Compromised maintainer publish** | New malicious version of legit package. | OSV.dev queries; offline IOC list as fallback |

## What this kit defends against (in scope)

- **Detect** compromised PyPI packages already declared in `requirements*.txt`
- **Detect** `.pth` persistence in site-packages (including subdirs and `_vendor`)
- **Detect** suspicious workflow patterns (pipe-to-shell, base64 decode, runner token exfil)
- **Detect** git remotes pointing at C2 domains
- **Detect** GitHub repos under user's account with exfil-marker descriptions
- **Detect** 2099-dated commits (TeamPCP signature)
- **Detect** Shai-Hulud / TeamPCP DNS resolution traces (deep mode)
- **Block** install of new packages via sandbox with `--only-binary :all:` + `--require-hashes`
- **Lock** dependency versions cryptographically via `requirements-hashed.txt`
- **Continuous monitoring** via Dependabot security PRs + nightly CI cron

## What this kit does NOT defend against (deferred / out of scope)

| Threat | Why deferred |
|---|---|
| **Compromised CI runner** | Mitigated only by self-hosted runners or ephemeral cloud VMs. Beyond scope for a solo dev. |
| **Compromised dev machine via different vector** (browser exploit, phishing) | Use `docs/SINGLE_DEV_CHECKLIST.md` for personal hygiene; this kit only covers supply chain. |
| **Typosquatted package not in offline IOC list** | OSV.dev catches many but not all. Review new deps manually. |
| **Compromised package manager binary itself** (npm, pip) | Outside scope. Verify via OS package manager or known good distributions. |
| **Compromised Python interpreter** | Same as above. |
| **State-actor-grade APT** | TeamPCP is financially motivated, not state-sponsored. APT defense requires real SOC, not pragmatic dev hygiene. |
| **Vendored / bundled dependencies** | If a package vendors malicious code, OSV.dev may not have an advisory for it. Audit before accepting major version bumps. |

## Defense layers

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 4: Continuous (Dependabot + nightly CI cron)             │
│  Catches: post-publish advisories                                │
├─────────────────────────────────────────────────────────────────┤
│  Layer 3: CI (pip-audit + per-manifest venv + osv-scanner)      │
│  Catches: vulnerable transitives, advisory matches, OSV deltas   │
├─────────────────────────────────────────────────────────────────┤
│  Layer 2: Pre-commit (detect_compromise.py + machine audit)     │
│  Catches: in-repo IOCs, machine compromise indicators            │
├─────────────────────────────────────────────────────────────────┤
│  Layer 1: Install-time (sandbox_install + --only-binary)        │
│  Catches: sdist code execution, unhashed tampering               │
└─────────────────────────────────────────────────────────────────┘
```

Each layer catches what the layers above it would miss. Don't skip layers — they're cheap individually.

## Acceptable risks

- **OSV.dev lag.** OSV indexes most public databases but new advisories take hours to surface. Pre-commit catches anything published before the dev started working; nightly CI catches anything published since.
- **False positives.** A few legitimate packages have install scripts (`node-sass`, `puppeteer`). The kit flags them as warnings, not alerts. Review and accept.
- **--only-binary :all: blocks legitimate sdist-only packages.** Falls back to allowing sdist with a log message. The fallback is monitored in CI logs.

## IOC data sources

- **Primary:** [copyleftdev/mini-shai-hulud-dragnet](https://github.com/copyleftdev/mini-shai-hulud-dragnet) (CC-BY-4.0) — forensic JSONL dataset with 47 IOCs across 14 kinds, attribution to AS209101 IP Vendetta Inc. The IOC constants in `detect_compromise.py` are seeded from this dataset.
- **Live:** OSV.dev batch API (`https://api.osv.dev/v1/querybatch`) — queried directly by `shai-hulud-audit.{ps1,sh}` for every installed package. Free, no auth required.
- **Reference reading:** Phoenix Security's writeup on the [Sha1-Hulud / Shai-Hulud worm analysis](https://phoenix.security/sha1-hulud-shai-hulud-worm-analysis-persistence-iocs/) is the most thorough public dissection of TeamPCP TTPs as of late May 2026.

Update the IOC constants in `detect_compromise.py` and the audit scripts whenever new waves are disclosed. The dragnet repo is the canonical source — pull `data/iocs.jsonl` and merge new entries.
