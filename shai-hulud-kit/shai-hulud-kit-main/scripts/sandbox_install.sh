#!/usr/bin/env bash
# sandbox_install.sh — vet a dep in a disposable venv before promoting it.
#
# Creates .sandbox-venv/, installs with --only-binary :all: to block sdist
# setup.py execution, uses --require-hashes when a hashed lockfile exists,
# and runs pip-audit against the result.
#
# Usage: ./scripts/sandbox_install.sh <package>==<version>
#        ./scripts/sandbox_install.sh -r <requirements-file>

set -u

if [[ $# -eq 0 ]]; then
    echo "Usage: $0 <package>==<version>   or   $0 -r <requirements-file>" >&2
    exit 3
fi

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
SANDBOX_DIR="$REPO_ROOT/.sandbox-venv"

# Pre-flight: warn about credentials in env (we can't unset them for the user)
SENSITIVE_VARS=()
for v in $(env | cut -d= -f1); do
    case "$v" in
        AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|GITHUB_TOKEN|GH_TOKEN|NPM_TOKEN|ANTHROPIC_API_KEY|GCP_*|GOOGLE_APPLICATION_CREDENTIALS)
            SENSITIVE_VARS+=("$v") ;;
    esac
done

if [[ ${#SENSITIVE_VARS[@]} -gt 0 ]]; then
    echo "⚠️  sandbox_install: sensitive env vars present in shell:" >&2
    for v in "${SENSITIVE_VARS[@]}"; do echo "    $v" >&2; done
    echo "   These will be visible to install scripts. Consider unsetting them" >&2
    echo "   in a fresh shell before continuing. Continuing in 3 seconds..." >&2
    sleep 3
fi

# Find Python
PY=""
for candidate in python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PY=$(command -v "$candidate")
        break
    fi
done
if [[ -z "$PY" ]]; then
    echo "sandbox_install: no python found" >&2
    exit 3
fi

# Clean up any prior sandbox
if [[ -d "$SANDBOX_DIR" ]]; then
    echo "sandbox_install: removing prior $SANDBOX_DIR"
    rm -rf "$SANDBOX_DIR"
fi

echo "sandbox_install: creating $SANDBOX_DIR..."
"$PY" -m venv "$SANDBOX_DIR" || {
    echo "sandbox_install: venv creation failed" >&2
    exit 3
}

SANDBOX_PY="$SANDBOX_DIR/bin/python"
SANDBOX_PIP="$SANDBOX_DIR/bin/pip"

# Upgrade pip in sandbox
"$SANDBOX_PIP" install --quiet --upgrade pip pip-audit

# Detect platform for --require-hashes gating
OS_TYPE="$(uname -s 2>/dev/null || echo unknown)"
IS_WINDOWS=false
case "$OS_TYPE" in
    MINGW*|MSYS*|CYGWIN*) IS_WINDOWS=true ;;
esac

# Determine install strategy
if [[ "$1" == "-r" ]]; then
    REQ_FILE="$2"
    if [[ ! -f "$REQ_FILE" ]]; then
        echo "sandbox_install: requirements file not found: $REQ_FILE" >&2
        exit 3
    fi

    # If this is the hashed file and platform-compatible, use --require-hashes
    HASHED_FILE="$REPO_ROOT/requirements-hashed.txt"
    if [[ "$REQ_FILE" == *requirements-hashed.txt && -f "$HASHED_FILE" ]]; then
        # Platform gate: hashed file may pin Windows-only packages
        if [[ "$IS_WINDOWS" == "true" ]] || ! grep -qE '^tensorflow-intel==' "$HASHED_FILE" 2>/dev/null; then
            echo "sandbox_install: installing $REQ_FILE with --require-hashes --only-binary :all:..."
            "$SANDBOX_PIP" install --only-binary :all: --require-hashes -r "$REQ_FILE" || {
                echo "sandbox_install: --require-hashes install failed; aborting (do NOT promote)" >&2
                exit 1
            }
        else
            echo "sandbox_install: hashed file has Windows-only packages, falling back to non-hashed..."
            "$SANDBOX_PIP" install --only-binary :all: -r "$REPO_ROOT/requirements.txt" || {
                echo "sandbox_install: --only-binary install failed; aborting" >&2
                exit 1
            }
        fi
    else
        echo "sandbox_install: installing $REQ_FILE with --only-binary :all:..."
        "$SANDBOX_PIP" install --only-binary :all: -r "$REQ_FILE" || {
            echo "sandbox_install: --only-binary install failed; aborting" >&2
            exit 1
        }
    fi
else
    # Single package
    PKG="$1"
    echo "sandbox_install: installing $PKG with --only-binary :all:..."
    "$SANDBOX_PIP" install --only-binary :all: "$PKG" || {
        echo "sandbox_install: --only-binary install failed; aborting (do NOT promote)" >&2
        exit 1
    }
fi

# Audit the result
echo ""
echo "sandbox_install: running pip-audit against sandbox..."
"$SANDBOX_PY" -m pip_audit --strict --progress-spinner=off
AUDIT_CODE=$?

# Show what got installed
echo ""
echo "sandbox_install: installed packages:"
"$SANDBOX_PIP" list --format=columns

echo ""
if [[ $AUDIT_CODE -eq 0 ]]; then
    echo "sandbox_install: ✓ clean. Safe to promote to real environment."
    echo "  To clean up: rm -rf $SANDBOX_DIR"
    exit 0
else
    echo "sandbox_install: ✗ findings. Do NOT promote to real environment."
    echo "  Sandbox left at: $SANDBOX_DIR"
    exit 1
fi
