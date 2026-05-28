# IOC Detection Checklist

What to check if you suspect compromise. Run these in order — earlier checks are cheaper and catch the common cases.

## Trigger conditions

Use this checklist if **any** of the following are true:

- `/pooptin` exited with code 2 (alerts)
- `detect_compromise.py` flagged a compromised package, `.pth` file, or workflow
- You installed a package from a known-compromised version (verify on OSV.dev)
- You see one of these signs on your machine:
  - Unusual GitHub repos under your account
  - Unexpected git commits with 2099 dates
  - DNS resolutions to `t.m-kosche.com`, `duluh-iahs.xyz`, or other C2 domains
  - 1Password CLI prompting unexpectedly
  - Antivirus/EDR alert on a `node_modules` or `site-packages` directory

## §1 Stop the bleeding (within 5 minutes)

1. **Disconnect the machine from the network.** Pull WiFi or Ethernet. Don't shut down — you'll lose forensic state.
2. **Note the timestamp.** Useful for log correlation later.
3. **Take a photo of any suspicious notification with your phone.** AV alerts, EDR popups, browser warnings.

## §2 Surface-level checks (5-15 minutes)

### Run the deep audit

```bash
~/.shai-hulud/shai-hulud-audit.sh --mode deep --github-user <your-username>
```

Output goes to `~/shai-hulud-audit/audit_<timestamp>_deep/`. Review:

- `report.txt` — full log
- `ioc_hits.txt` — alerts only
- `result.json` — machine-readable

### Check GitHub for exfiltrated repos

If you didn't pass `--github-user` above, manually:

1. Go to `https://github.com/<your-username>?tab=repositories`
2. Look for repos with descriptions containing:
   - `niagA oG eW ereH :duluH-iahS` (reversed marker)
   - "Shai-Hulud"
   - "TeamPCP"
   - "A Gift From TeamPCP"
3. **If found:** DO NOT delete (forensic value). Mark private, screenshot, file an issue with GitHub Security.

### Check git logs for spoofed dates

```bash
cd <every-repo>
git log --all --format="%H %ai %s" | grep " 209"
```

A 2099-dated commit is TeamPCP signature. Don't delete it — you'll need the SHA for the cleanup.

### Check installed packages against OSV

```bash
pip-audit
npm audit --production    # if you have npm
```

### Check for Claude Code / VSCode persistence (TeamPCP signature)

TeamPCP specifically targets these paths. Their presence in any project is a confirmed-compromise indicator:

```bash
# In every repo and at $HOME
find . ~ -path '*/\.claude/execution.js' -o -path '*/\.claude/setup.mjs' \
        -o -path '*/\.vscode/setup.mjs' 2>/dev/null
```

Also check `.claude/settings.json` files for a `SessionStart_hook` property pointing to anything in `.claude/`:

```bash
find . ~ -name 'settings.json' -path '*/\.claude/*' \
  -exec grep -l 'SessionStart_hook' {} \;
```

If any of these are present:

1. **Do not run Claude Code on this machine again until cleaned.**
2. Note the path and the file's mtime.
3. Read the file contents to a safe location (don't execute).
4. Proceed to §3 (credential rotation) — the Claude Code session has already had the payload run on your behalf at least once.

## §3 Credential rotation (next 30 minutes)

Order matters: rotate the things that grant access to *more things* first.

1. **Master account passwords** that everything else derives from:
   - 1Password / Bitwarden master password
   - Google / Microsoft / Apple ID (used for SSO)
2. **Tokens with broad access:**
   - GitHub personal access tokens (`https://github.com/settings/tokens`) — **revoke all, regenerate as needed**
   - npm tokens (`npm token list` then `npm token revoke <id>`)
   - PyPI API tokens (`https://pypi.org/manage/account/`)
   - AWS root + IAM access keys
   - Cloud provider service account keys
3. **Application-specific:**
   - SSH keys (`~/.ssh/id_*`) — generate new, distribute to GitHub/servers
   - Anthropic API key (`https://console.anthropic.com/`)
   - OpenAI API key
   - Any other API keys in `.env` files

For each rotated credential, **also check usage logs** for the past 30 days. If you see activity from unexpected IPs or at unusual times, file an incident with the provider.

## §4 1Password specific

If you used 1Password CLI (`op`) on this machine:

1. **Treat the master password as compromised.** Rotate.
2. Sign out everywhere: `https://my.1password.com/account/devices` → remove all devices.
3. Re-enroll devices fresh.
4. Review vault item history for unexpected access:
   - `https://my.1password.com/audit-log` (Business/Teams)
   - For Personal: each item's history tab

## §5 Browser hygiene

1. **Clear cookies and active sessions** for high-value services (GitHub, Google, AWS, npm, PyPI).
2. **Sign out everywhere** via account settings on each service.
3. **Check OAuth-authorized apps** on each service for unexpected apps:
   - `https://github.com/settings/applications`
   - `https://myaccount.google.com/permissions`
4. **Disable browser extensions you don't need.** Malicious extensions are a separate vector but worth checking while you're already auditing.

## §6 Cleanup (within 24 hours)

Once credentials are rotated and you've documented everything:

1. **Re-image the machine.** A full disk wipe + OS reinstall is the safest path. Yes, this is annoying. Yes, you should still do it.
2. **Restore from a backup older than the compromise.** If you can date the compromise, restore from before. If you can't, treat all backups as suspect and rebuild from scratch.
3. **Reinstall tools from official sources only.** Don't restore application caches.
4. **Set up the kit fresh** on the new machine. Don't carry over any data from the compromised machine until you've audited it.

## §7 If you can't re-image

If re-imaging isn't feasible (work-issued machine, locked OS), at minimum:

1. **Delete and reinstall all virtual environments.** `rm -rf .venv` everywhere.
2. **Delete and reinstall all `node_modules`.** `rm -rf node_modules` everywhere; `npm ci` from scratch.
3. **Audit `~/.config/`, `~/.local/`, `~/AppData/`** for unexpected files. Date-modified-newer-than-onset is a good filter.
4. **Run a full antivirus scan.** Windows Defender (Microsoft Defender), Malwarebytes, or ClamAV.
5. **Monitor outbound network for the next 30 days.** Little Snitch (macOS) or netstat-based scripting (Linux/Windows). Block any new outbound connections by default.

## §8 Documentation

For each step, record:

- Timestamp
- What you found
- What you rotated
- Screenshots of any alerts

This is for your future self if a related compromise surfaces in another tool. Also useful if you need to file a report with employer / GitHub / Anthropic.

## §9 Reach out

If the compromise involves more than personal data:

- **Anthropic API key:** notify support@anthropic.com (mention this campaign by name)
- **GitHub:** `https://github.com/contact/security`
- **npm package compromise:** `[email protected]`
- **PyPI package compromise:** `[email protected]`

The maintainers want to know — your report helps others.

## §10 Don't blame yourself

This campaign has compromised employees at OpenAI, Grafana, Mistral AI, and many others. It is sophisticated, fast, and pre-emptively targets ecosystems most devs assume are safe. Hardening helps; perfection isn't the bar.
