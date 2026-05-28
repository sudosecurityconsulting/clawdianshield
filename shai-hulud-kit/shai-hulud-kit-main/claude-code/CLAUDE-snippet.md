<!--
  Append this block to your project's CLAUDE.md. It tells Claude Code (when
  working in this project) how to use the supply chain audit tools.
-->

## Supply chain audit

This project has Shai-Hulud / TeamPCP supply chain audit tools installed. Use them before committing.

### Before committing

Run **both** checks. They cover different layers:

1. **Machine-level audit** (catches compromised packages anywhere on disk, system IOCs):
   ```bash
   /pooptin quick
   ```
   Or directly:
   ```bash
   ~/.shai-hulud/shai-hulud-audit.sh --mode quick   # macOS/Linux
   ~/.shai-hulud/shai-hulud-audit.ps1 -Mode quick   # Windows
   ```

2. **Project-level audit** (catches PEP 508 dep parsing, `.pth` exec, workflow tamper):
   ```bash
   python scripts/detect_compromise.py
   ```
   Or, if `audit_deps.sh` is present:
   ```bash
   ./scripts/audit_deps.sh
   ```

Both have exit codes: `0` clean, `1` warnings, `2` alerts. Don't commit on alert.

### When adding a dependency

Use the sandbox install to vet a new version before adding it to the real environment:

```bash
./scripts/sandbox_install.sh <package>==<version>   # macOS/Linux
.\scripts\sandbox_install.bat <package>==<version>  # Windows
```

This installs into a disposable venv with `--only-binary :all:` (blocks `setup.py` execution from sdists) and runs `pip-audit` against it.

### Updating the hash-pinned lockfile

After any dep change, regenerate:

```bash
pip install pip-tools
pip-compile --generate-hashes --output-file=requirements-hashed.txt requirements.txt
```

### When an audit fails

See `docs/security/IOC_DETECTION_CHECKLIST.md` for the incident response runbook (what to check, credential rotation order, etc.).

### CI integration

The supply chain audit workflow lives at `.github/workflows/supply-chain-audit.yml`. It runs on every push/PR and nightly at 07:00 UTC.

### Tests

Property tests for `detect_compromise.py` are at `tests/test_detect_compromise.py`. Run with:

```bash
python -m unittest tests/test_detect_compromise.py -v
```

If you modify `detect_compromise.py`, run the tests before committing.
