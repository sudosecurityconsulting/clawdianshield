# Single-Dev Hardening Checklist

Personal hygiene for solo developers. No VM isolation, no SOC, no Vault. Pragmatic minimum.

## The five-minute setup

If you only have five minutes, do these:

1. **`npm config set ignore-scripts true`** — stops 99% of npm post-install attacks at the cost of having to manually `npm rebuild` some legitimate packages.
2. **Set up `op signin --account my` once and never type your master password into a terminal again** — use the desktop app for auth, CLI inherits the session.
3. **Add this kit's pre-commit hook** to every project (cp + chmod takes 10 seconds).
4. **Run `~/.shai-hulud/shai-hulud-audit.sh --mode deep` today** to baseline. You can't detect "this is new" without knowing what's normal.
5. **Turn on full-disk encryption.** macOS: System Settings → Privacy & Security → FileVault. Windows: BitLocker. Linux: LUKS or use a distro that did it for you.

That's it. You can do the rest later.

## The thirty-minute setup (recommended)

Add to the above:

### Tier 1: Lock down credentials

- **Rotate all tokens older than 90 days.** GitHub PATs, npm tokens, PyPI tokens, cloud provider keys. Use the rotation order in `IOC_CHECKLIST.md` §3.
- **Set up fine-grained GitHub PATs** instead of classic tokens. Scope to specific repos, set expiration ≤90 days.
- **Move all secrets to your password manager.** Not in `.env` files in repos. Not in shell history. Not in Notion. Password manager only.
- **Use SSH keys for git remotes**, not HTTPS with tokens. SSH keys can't be passively scraped from shell history.

### Tier 2: Sandbox dev work

- **Install this kit's `sandbox_install.sh`** in every Python project. Use it for any new dep, not just ones you're suspicious of.
- **Use `--only-binary :all:`** as your default. Add `pip-cli-only-binary` shell alias or configure `pip.conf`:
  ```
  [install]
  only-binary = :all:
  ```
- **Pin npm to a single version of node** via `nvm use` + `.nvmrc`. Update Node only deliberately.
- **For experimental code, use a cloud dev env** (GitHub Codespaces, Gitpod, AWS Cloud9). Disposable, no impact on your local machine.

### Tier 3: Continuous monitoring

- **Set up Dependabot** on every project (5 min per repo).
- **Enable the CI workflow** from `ci/supply-chain-audit.yml`.
- **Subscribe to OSV-Vulns** mailing list or RSS for high-severity advisories.
- **Run `/pooptin deep` weekly.** Friday afternoon while reviewing the week is a good time.

## OS-specific notes

### macOS

- **Gatekeeper:** keep it enabled. System Settings → Privacy & Security → "App Store and identified developers."
- **System Integrity Protection:** never disable, even for "convenience."
- **Little Snitch or LuLu** for outbound network monitoring. Especially useful for catching exfil from a compromised dep.
- **Stop running things as your primary admin user.** Create a separate dev user without admin privileges. Use it for daily work. `sudo` to admin only when needed.

### Linux

- **AppArmor / SELinux:** enable, don't disable.
- **`firejail`** for sandboxing untrusted tools. Lightweight, ships in most distros.
- **`unattended-upgrades`** for security patches. Don't manually defer them past a week.
- **Use `flatpak` over `snap` over OS package** for desktop apps when possible — better isolation.

### Windows

- **Windows Defender:** keep on. Add exclusions only for specific dev directories, not "all of `~/projects/`."
- **Controlled Folder Access:** enable for `Documents`, `Desktop`. Catches ransomware that mass-modifies files.
- **BitLocker:** enable. Save the recovery key to your password manager (not OneDrive).
- **WSL2 for Linux work:** more isolation than running native Linux tools on Windows.
- **PowerShell execution policy:** `RemoteSigned` minimum. Don't `Set-ExecutionPolicy Unrestricted`.

## Habits

These don't take time per-incident, just sustained attention:

- **Read package READMEs before adding a new dep.** Five minutes of skimming has caught many typosquats.
- **Don't `curl ... | bash` install instructions.** Download first, read, then execute.
- **Don't paste random commands from Stack Overflow / Reddit into a terminal.** Especially if they include `sudo` or pipe to `bash`.
- **Be suspicious of "quick fix" GitHub Actions in PRs.** A workflow that adds `run: curl ... | bash` is a red flag, full stop.
- **Re-read package.json `scripts` after `npm install`.** Some malicious packages modify yours.

## What you can deliberately skip

For a solo dev, these are usually overkill:

- **Hardware security keys (YubiKey) for git signing.** Useful, but adoption friction is real. SSH keys + password manager is sufficient.
- **Air-gapped backup machine.** Sounds great, expensive to maintain. Cloud backup (Backblaze, Arq) with versioning + immutability is good enough.
- **Self-hosted CI runners.** Default GitHub-hosted runners are fine for the scale of solo work. Self-hosted introduces its own attack surface.
- **Full network segmentation at home.** A VLAN for IoT and a VLAN for work is the bar, but most home routers can't do it cleanly. Don't twist yourself into knots.

## When to escalate

This kit is for solo + small teams. If you're handling:

- Customer PII at scale
- Financial transactions (you're regulated)
- Health data (HIPAA)
- Government or defense contracts

...then "pragmatic personal hygiene" is no longer the bar. You need a real security program, real auditors, and likely a real SOC. Use this kit as a starting point, then build up.

## Final note

The goal isn't to be unhackable. The goal is to make yourself unappealing relative to easier targets. This campaign succeeds because most devs run zero of these layers; running even three puts you in the top quartile of solo devs on this threat surface.
