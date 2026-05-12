#!/usr/bin/env bash
# run_all_scenarios.sh
# Runs every scenario in scenarios/ against clawdian_victim.
# Victim container must already be running.
# Usage: bash scripts/run_all_scenarios.sh [--dry-run]

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCENARIOS_DIR="$REPO_ROOT/scenarios"
RUNNER="$REPO_ROOT/runner/executor.py"
VENV="$HOME/clawdian-venv"
DRY_RUN="${1:-}"

source "$VENV/bin/activate"

PASS=0
FAIL=0
SKIP=0

echo "╔══════════════════════════════════════════════════════╗"
echo "║  ClawdianShield — Full Scenario Suite                ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

for scenario in "$SCENARIOS_DIR"/*.json; do
    name=$(python3 -c "import json,sys; d=json.load(open('$scenario')); print(d.get('name','unknown'))")
    sid=$(python3 -c "import json,sys; d=json.load(open('$scenario')); print(d.get('scenario_id','unknown'))")

    echo "──────────────────────────────────────────────────────"
    echo "  SCENARIO : $name"
    echo "  ID       : $sid"
    echo "  FILE     : $(basename $scenario)"
    echo ""

    if [[ "$DRY_RUN" == "--dry-run" ]]; then
        python3 "$RUNNER" "$scenario" --dry-run && STATUS="DRY-RUN OK" || STATUS="DRY-RUN FAIL"
    else
        python3 "$RUNNER" "$scenario" --container clawdian_victim && STATUS="PASS" || STATUS="FAIL"
    fi

    echo "  RESULT   : $STATUS"
    echo ""

    case "$STATUS" in
        PASS|"DRY-RUN OK") PASS=$((PASS+1)) ;;
        FAIL|"DRY-RUN FAIL") FAIL=$((FAIL+1)) ;;
        *) SKIP=$((SKIP+1)) ;;
    esac
done

echo "══════════════════════════════════════════════════════"
echo "  SUITE COMPLETE"
echo "  PASSED : $PASS"
echo "  FAILED : $FAIL"
echo "  SKIPPED: $SKIP"
echo "══════════════════════════════════════════════════════"
