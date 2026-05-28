#!/usr/bin/env bash
# audit_deps.sh — local pip-audit driver across all requirements*.txt
#
# Walks the repo for requirements files (excluding venvs, node_modules) and
# runs pip-audit on each. Exits non-zero if any has a finding.
#
# Usage: ./scripts/audit_deps.sh

set -u

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT" || exit 3

# Find Python — prefer 3.11 (3.12+ ships without _tkinter on some platforms)
PY=""
for candidate in .venv311/bin/python .venv/bin/python venv/bin/python python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PY="$candidate"
        break
    fi
    if [[ -x "$REPO_ROOT/$candidate" ]]; then
        PY="$REPO_ROOT/$candidate"
        break
    fi
done

if [[ -z "$PY" ]]; then
    echo "audit_deps: no python found" >&2
    exit 3
fi

# Ensure pip-audit is installed
if ! "$PY" -m pip_audit --version >/dev/null 2>&1; then
    echo "audit_deps: pip-audit not installed; installing..." >&2
    "$PY" -m pip install --quiet pip-audit || {
        echo "audit_deps: failed to install pip-audit" >&2
        exit 3
    }
fi

# Find all requirements files
MANIFESTS=()
while IFS= read -r f; do
    MANIFESTS+=("$f")
done < <(find . -name "requirements*.txt" \
    -not -path "*/node_modules/*" \
    -not -path "*/.venv*/*" \
    -not -path "*/venv/*" \
    -not -path "*/.tox/*" \
    -not -path "*/site-packages/*" \
    2>/dev/null | sort)

if [[ ${#MANIFESTS[@]} -eq 0 ]]; then
    echo "audit_deps: no requirements files found"
    exit 0
fi

echo "audit_deps: found ${#MANIFESTS[@]} requirements file(s)"

FAILED=0
for req in "${MANIFESTS[@]}"; do
    echo ""
    echo "=== Auditing $req ==="
    if ! "$PY" -m pip_audit -r "$req" --strict --progress-spinner=off; then
        FAILED=1
        echo "  ↑ findings in $req"
    fi
done

echo ""
if [[ $FAILED -eq 1 ]]; then
    echo "audit_deps: FAIL — see findings above"
    echo "Remediation: see docs/security/HARDENING.md (if present)"
    exit 1
fi

echo "audit_deps: PASS"
exit 0
