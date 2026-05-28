#!/usr/bin/env bash
# Shai-Hulud / TeamPCP supply chain audit — bash port for macOS/Linux.
# Mirrors shai-hulud-audit.ps1: three modes, JSON output, exit codes, OSV cache.
#
# Usage:
#   ./shai-hulud-audit.sh                     # quick scan of cwd / git root
#   ./shai-hulud-audit.sh --mode deep         # full machine scan
#   ./shai-hulud-audit.sh --json              # JSON for agents
#   ./shai-hulud-audit.sh --mode status       # last scan summary
#
# Exit codes: 0=clean, 1=warnings, 2=alerts, 3=script error
#
# Requires: bash 4+, curl, jq (for JSON parsing), python3 (for site-packages lookup)

set -uo pipefail

# --- defaults ---
MODE="quick"
PROJECT_PATH=""
DAYS_BACK=30
DEV_ROOTS=(
    "$HOME/Documents"
    "$HOME/Desktop"
    "$HOME/projects"
    "$HOME/code"
    "$HOME/work"
    "$HOME/src"
)
OUTPUT_DIR=""
GITHUB_USER=""
GITHUB_TOKEN=""
JSON_OUTPUT=false
QUIET=false
SKIP_OSV=false
NO_CACHE=false
CACHE_TTL_MIN=15
FAIL_ON_LEVEL=2
TIMEOUT_SEC=30

# --- arg parsing ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode) MODE="$2"; shift 2 ;;
        --project-path) PROJECT_PATH="$2"; shift 2 ;;
        --days-back) DAYS_BACK="$2"; shift 2 ;;
        --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
        --github-user) GITHUB_USER="$2"; shift 2 ;;
        --github-token) GITHUB_TOKEN="$2"; shift 2 ;;
        --json) JSON_OUTPUT=true; shift ;;
        --quiet) QUIET=true; shift ;;
        --skip-osv) SKIP_OSV=true; shift ;;
        --no-cache) NO_CACHE=true; shift ;;
        --cache-ttl-min) CACHE_TTL_MIN="$2"; shift 2 ;;
        --fail-on-level) FAIL_ON_LEVEL="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,15p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; exit 3 ;;
    esac
done

case "$MODE" in
    quick|project|deep|status) ;;
    *) echo "Invalid mode: $MODE (use quick|project|deep|status)" >&2; exit 3 ;;
esac

# --- setup ---
TS=$(date +%Y%m%d_%H%M%S)
AUDIT_ROOT="$HOME/shai-hulud-audit"
CACHE_DIR="$AUDIT_ROOT/cache"
LAST_RUN_FILE="$AUDIT_ROOT/last_run.json"

if [[ -z "$OUTPUT_DIR" ]]; then
    OUTPUT_DIR="$AUDIT_ROOT/audit_${TS}_${MODE}"
fi

mkdir -p "$OUTPUT_DIR" "$CACHE_DIR"

REPORT_FILE="$OUTPUT_DIR/report.txt"
IOC_FILE="$OUTPUT_DIR/ioc_hits.txt"
JSON_FILE="$OUTPUT_DIR/result.json"
PKG_TMP=$(mktemp)
OSV_TMP=$(mktemp)
trap 'rm -f "$PKG_TMP" "$OSV_TMP"' EXIT

SCRIPT_START=$(date +%s)
CUTOFF_EPOCH=$(( $(date +%s) - DAYS_BACK*86400 ))

echo "Shai-Hulud Audit | Mode: $MODE | $(date) | Days back: $DAYS_BACK" > "$REPORT_FILE"

ALERT_COUNT=0
WARN_COUNT=0
ALERTS_JSON="[]"
WARNINGS_JSON="[]"

# --- helpers ---
say() {
    local level="$1"; shift
    local msg="$*"
    echo "[$level] $msg" >> "$REPORT_FILE"
    [[ "$JSON_OUTPUT" == "true" || "$QUIET" == "true" ]] && return
    case "$level" in
        ALERT) printf '\033[31m[%s] %s\033[0m\n' "$level" "$msg" >&2 ;;
        WARN)  printf '\033[33m[%s] %s\033[0m\n' "$level" "$msg" >&2 ;;
        OK)    printf '\033[32m[%s] %s\033[0m\n' "$level" "$msg" >&2 ;;
        *)     printf '[%s] %s\n' "$level" "$msg" >&2 ;;
    esac
}

section() {
    [[ "$JSON_OUTPUT" == "true" || "$QUIET" == "true" ]] && { echo "" >> "$REPORT_FILE"; echo "  $*" >> "$REPORT_FILE"; return; }
    local sep="================================================================"
    printf '\n\033[36m%s\n  %s\n%s\033[0m\n' "$sep" "$*" "$sep" >&2
    echo -e "\n$sep\n  $*\n$sep" >> "$REPORT_FILE"
}

# Add finding to JSON arrays (using jq for proper escaping)
add_finding() {
    local level="$1" section_name="$2" type_name="$3" message="$4"
    local details="${5:-{\}}"
    local entry
    entry=$(jq -n --arg s "$section_name" --arg t "$type_name" --arg l "$level" \
        --arg m "$message" --argjson d "$details" --arg ts "$(date -Iseconds)" \
        '{section:$s, type:$t, level:$l, message:$m, details:$d, timestamp:$ts}')
    if [[ "$level" == "ALERT" ]]; then
        ALERTS_JSON=$(echo "$ALERTS_JSON" | jq --argjson e "$entry" '. + [$e]')
        ALERT_COUNT=$((ALERT_COUNT + 1))
    elif [[ "$level" == "WARN" ]]; then
        WARNINGS_JSON=$(echo "$WARNINGS_JSON" | jq --argjson e "$entry" '. + [$e]')
        WARN_COUNT=$((WARN_COUNT + 1))
    fi
}

write_ioc() {
    local type_name="$1" detail="$2" details_json="${3:-{\}}"
    echo "$type_name | $detail" >> "$IOC_FILE"
    say ALERT "$type_name | $detail"
    add_finding "ALERT" "IOC" "$type_name" "$detail" "$details_json"
}

# --- dependency checks ---
have() { command -v "$1" >/dev/null 2>&1; }

if ! have curl; then echo "curl required" >&2; exit 3; fi
if ! have jq; then
    echo "jq required (brew install jq / apt install jq)" >&2; exit 3
fi

# --- status mode short-circuit ---
if [[ "$MODE" == "status" ]]; then
    if [[ -f "$LAST_RUN_FILE" ]]; then
        if [[ "$JSON_OUTPUT" == "true" ]]; then
            cat "$LAST_RUN_FILE"
        else
            jq -r '"Last scan: \(.timestamp)\nMode     : \(.mode)\nDuration : \(.duration_seconds)s\nAlerts   : \(.summary.alert_count)\nWarnings : \(.summary.warn_count)\nExit code: \(.summary.exit_code)"' "$LAST_RUN_FILE"
        fi
    else
        if [[ "$JSON_OUTPUT" == "true" ]]; then
            echo '{"error":"no prior scan found"}'
        else
            echo "No prior scan found." >&2
        fi
    fi
    exit 0
fi

# --- scope resolution ---
find_git_root() {
    local p="$1"
    while [[ -n "$p" && "$p" != "/" ]]; do
        if [[ -d "$p/.git" ]]; then echo "$p"; return; fi
        p=$(dirname "$p")
    done
}

SCAN_SCOPE=()
case "$MODE" in
    quick)
        gr=$(find_git_root "$(pwd)")
        SCAN_SCOPE=("${gr:-$(pwd)}")
        ;;
    project)
        if [[ -z "$PROJECT_PATH" || ! -d "$PROJECT_PATH" ]]; then
            say ALERT "Mode 'project' requires valid --project-path"
            exit 3
        fi
        SCAN_SCOPE=("$(cd "$PROJECT_PATH" && pwd)")
        ;;
    deep)
        for r in "${DEV_ROOTS[@]}"; do
            [[ -d "$r" ]] && SCAN_SCOPE+=("$r")
        done
        ;;
esac

section "SCAN CONFIG"
say INFO "Mode: $MODE | Scope: ${SCAN_SCOPE[*]} | DaysBack: $DAYS_BACK"

# --- IOC lists ---
KNOWN_BAD_NPM=(
    "@antv/g2" "@antv/g6" "@antv/x6" "@antv/l7" "@antv/s2" "@antv/f2" "@antv/g"
    "@antv/g2plot" "@antv/graphin" "@antv/data-set" "@antv/scale"
    "echarts-for-react" "timeago.js" "size-sensor" "canvas-nest.js"
    "@tanstack/react-query" "@tanstack/vue-query" "@tanstack/query-core"
    "@tanstack/react-table" "@tanstack/table-core" "@tanstack/react-virtual"
    "@tanstack/virtual-core" "@tanstack/react-router" "@tanstack/router-core"
    "@tanstack/react-form" "@tanstack/form-core" "@tanstack/store"
    "@bitwarden/cli" "@mistralai/mistralai" "@squawk/squawk"
)
KNOWN_BAD_PYPI=("durabletask" "fast-agent-mcp")
C2_DOMAINS=("t.m-kosche.com" "audit.checkmarx.cx" "checkmarx.cx" "npm.componentjs.com" "registry.npmjs.cx" "duluh-iahs.xyz" "team-pcp.com")
C2_IPS=("94.154.172.43")
# .claude/ and .vscode/ persistence indicators (TeamPCP, May 2026)
PERSISTENCE_FILES=(".claude/execution.js" ".claude/setup.mjs" ".vscode/setup.mjs")

is_known_bad_npm() {
    for b in "${KNOWN_BAD_NPM[@]}"; do [[ "$1" == "$b" ]] && return 0; done
    return 1
}
is_known_bad_pypi() {
    for b in "${KNOWN_BAD_PYPI[@]}"; do [[ "$1" == "$b" ]] && return 0; done
    return 1
}

# --- OSV cache helpers ---
osv_cache_key() {
    local raw="$3|$1|$2"
    if have sha256sum; then echo -n "$raw" | sha256sum | cut -d' ' -f1
    else echo -n "$raw" | shasum -a 256 | cut -d' ' -f1; fi
}

osv_cache_get() {
    [[ "$NO_CACHE" == "true" ]] && return 1
    local f="$CACHE_DIR/$1.json"
    [[ ! -f "$f" ]] && return 1
    local age_min
    age_min=$(( ( $(date +%s) - $(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f") ) / 60 ))
    [[ $age_min -gt $CACHE_TTL_MIN ]] && return 1
    cat "$f"
}

osv_cache_set() {
    [[ "$NO_CACHE" == "true" ]] && return
    echo "$2" > "$CACHE_DIR/$1.json"
}

# --- npm inventory ---
section "NPM PACKAGES"
NPM_COUNT=0
for scope in "${SCAN_SCOPE[@]}"; do
    while IFS= read -r -d '' nm; do
        # Skip nested node_modules
        [[ "$nm" == *node_modules/*node_modules/* ]] && continue

        for entry in "$nm"/*; do
            [[ -d "$entry" ]] || continue
            entry_name=$(basename "$entry")

            # Handle @scope/ directories
            if [[ "$entry_name" == @* ]]; then
                for sub in "$entry"/*; do
                    [[ -d "$sub" ]] || continue
                    sub_name=$(basename "$sub")
                    full_name="$entry_name/$sub_name"
                    mtime=$(stat -c %Y "$sub" 2>/dev/null || stat -f %m "$sub" 2>/dev/null || echo 0)
                    [[ $mtime -lt $CUTOFF_EPOCH ]] && continue

                    version="0.0.0"; has_install="false"
                    if [[ -f "$sub/package.json" ]]; then
                        version=$(jq -r '.version // "0.0.0"' "$sub/package.json" 2>/dev/null)
                        scripts=$(jq -r '.scripts // {} | keys[]?' "$sub/package.json" 2>/dev/null)
                        if echo "$scripts" | grep -qE '^(pre|post)?install$'; then has_install="true"; fi
                    fi

                    is_bad="false"
                    if is_known_bad_npm "$full_name"; then
                        is_bad="true"
                        write_ioc "NPM_KNOWN_BAD" "$full_name@$version in $(dirname "$nm")" \
                            "$(jq -n --arg n "$full_name" --arg v "$version" '{name:$n,version:$v}')"
                    fi

                    echo "npm|$full_name|$version|$mtime|$has_install|$is_bad|$(dirname "$nm")" >> "$PKG_TMP"
                    NPM_COUNT=$((NPM_COUNT + 1))
                done
                continue
            fi

            mtime=$(stat -c %Y "$entry" 2>/dev/null || stat -f %m "$entry" 2>/dev/null || echo 0)
            [[ $mtime -lt $CUTOFF_EPOCH ]] && continue

            version="0.0.0"; has_install="false"
            if [[ -f "$entry/package.json" ]]; then
                version=$(jq -r '.version // "0.0.0"' "$entry/package.json" 2>/dev/null)
                scripts=$(jq -r '.scripts // {} | keys[]?' "$entry/package.json" 2>/dev/null)
                if echo "$scripts" | grep -qE '^(pre|post)?install$'; then has_install="true"; fi
            fi

            is_bad="false"
            if is_known_bad_npm "$entry_name"; then
                is_bad="true"
                write_ioc "NPM_KNOWN_BAD" "$entry_name@$version in $(dirname "$nm")" \
                    "$(jq -n --arg n "$entry_name" --arg v "$version" '{name:$n,version:$v}')"
            fi

            echo "npm|$entry_name|$version|$mtime|$has_install|$is_bad|$(dirname "$nm")" >> "$PKG_TMP"
            NPM_COUNT=$((NPM_COUNT + 1))
        done
    done < <(find "$scope" -maxdepth 6 -name node_modules -type d -print0 2>/dev/null)
done
say INFO "npm packages in window: $NPM_COUNT"

# --- PyPI inventory ---
section "PYPI PACKAGES"
SITE_PACKAGES=()

if [[ "$MODE" == "deep" ]] && have python3; then
    while IFS= read -r p; do
        [[ -d "$p" ]] && SITE_PACKAGES+=("$p")
    done < <(python3 -c "import site, json; print('\n'.join(site.getsitepackages()))" 2>/dev/null)
fi

for scope in "${SCAN_SCOPE[@]}"; do
    while IFS= read -r -d '' sp; do
        SITE_PACKAGES+=("$sp")
    done < <(find "$scope" -maxdepth 6 -name "site-packages" -type d -print0 2>/dev/null)
done

PYPI_COUNT=0
# Dedup site-packages
declare -A seen
for sp in "${SITE_PACKAGES[@]}"; do
    [[ -n "${seen[$sp]:-}" ]] && continue
    seen[$sp]=1

    for distinfo in "$sp"/*.dist-info; do
        [[ -d "$distinfo" ]] || continue
        mtime=$(stat -c %Y "$distinfo" 2>/dev/null || stat -f %m "$distinfo" 2>/dev/null || echo 0)
        [[ $mtime -lt $CUTOFF_EPOCH ]] && continue

        name=""; ver=""
        if [[ -f "$distinfo/METADATA" ]]; then
            name=$(grep -m1 "^Name:" "$distinfo/METADATA" 2>/dev/null | sed 's/^Name: *//' | tr '[:upper:]' '[:lower:]' | tr -d '\r')
            ver=$(grep -m1 "^Version:" "$distinfo/METADATA" 2>/dev/null | sed 's/^Version: *//' | tr -d '\r')
        fi
        if [[ -z "$name" || -z "$ver" ]]; then
            base=$(basename "$distinfo" .dist-info)
            ver="${base##*-}"
            name="${base%-*}"
            name=$(echo "$name" | tr '[:upper:]' '[:lower:]')
        fi

        is_bad="false"
        if is_known_bad_pypi "$name"; then
            is_bad="true"
            write_ioc "PYPI_KNOWN_BAD" "$name==$ver in $sp" \
                "$(jq -n --arg n "$name" --arg v "$ver" '{name:$n,version:$v}')"
        fi

        echo "PyPI|$name|$ver|$mtime|false|$is_bad|$sp" >> "$PKG_TMP"
        PYPI_COUNT=$((PYPI_COUNT + 1))
    done
done
say INFO "PyPI packages in window: $PYPI_COUNT"

# Surface install-script packages
while IFS='|' read -r eco name ver mtime hasinst isbad loc; do
    if [[ "$hasinst" == "true" && "$isbad" != "true" ]]; then
        say WARN "Install script: $name@$ver in $loc"
        add_finding "WARN" "install_scripts" "has_install_script" "$name@$ver" \
            "$(jq -n --arg n "$name" --arg v "$ver" --arg l "$loc" '{name:$n,version:$v,path:$l}')"
    fi
done < "$PKG_TMP"

# --- OSV live query ---
if [[ "$SKIP_OSV" != "true" && -s "$PKG_TMP" ]]; then
    section "OSV.DEV LIVE QUERY"

    # Build dedup list of {ecosystem,name,version}
    declare -A seen_pkg
    QUERY_JSON='{"queries":[]}'
    QUERY_PKGS=()
    while IFS='|' read -r eco name ver mtime hasinst isbad loc; do
        key="$eco|$name|$ver"
        [[ -n "${seen_pkg[$key]:-}" ]] && continue
        seen_pkg[$key]=1
        QUERY_PKGS+=("$eco|$name|$ver|$loc")
    done < "$PKG_TMP"

    say INFO "Querying OSV for ${#QUERY_PKGS[@]} unique packages..."

    # Check cache, build query for misses
    CACHE_HITS=0; CACHE_MISSES=()
    for pkg in "${QUERY_PKGS[@]}"; do
        IFS='|' read -r eco name ver loc <<< "$pkg"
        key=$(osv_cache_key "$name" "$ver" "$eco")
        cached=$(osv_cache_get "$key")
        if [[ -n "$cached" ]]; then
            CACHE_HITS=$((CACHE_HITS + 1))
            # Process cached findings
            vulns_count=$(echo "$cached" | jq -r '.vulns // [] | length')
            if [[ "$vulns_count" -gt 0 ]]; then
                while IFS= read -r vid; do
                    is_mal="false"
                    [[ "$vid" == MAL-* ]] && is_mal="true"
                    echo "$eco|$name|$ver|$vid|$is_mal|$loc" >> "$OSV_TMP"
                done < <(echo "$cached" | jq -r '.vulns[].id')
            fi
        else
            CACHE_MISSES+=("$pkg|$key")
        fi
    done

    say INFO "OSV cache: $CACHE_HITS hits, ${#CACHE_MISSES[@]} need fetch"

    # Batch fetch misses
    if [[ ${#CACHE_MISSES[@]} -gt 0 ]]; then
        BATCH_SIZE=500
        for ((i=0; i<${#CACHE_MISSES[@]}; i+=BATCH_SIZE)); do
            batch=("${CACHE_MISSES[@]:i:BATCH_SIZE}")
            queries='[]'
            for pkg in "${batch[@]}"; do
                IFS='|' read -r eco name ver loc key <<< "$pkg"
                q=$(jq -n --arg n "$name" --arg e "$eco" --arg v "$ver" \
                    '{package:{name:$n,ecosystem:$e},version:$v}')
                queries=$(echo "$queries" | jq --argjson q "$q" '. + [$q]')
            done
            body=$(jq -n --argjson q "$queries" '{queries:$q}')

            attempt=0; success=false
            while [[ $attempt -lt 3 && "$success" == "false" ]]; do
                attempt=$((attempt + 1))
                resp=$(curl -sS -X POST --max-time "$TIMEOUT_SEC" \
                    -H "Content-Type: application/json" \
                    -d "$body" \
                    "https://api.osv.dev/v1/querybatch" 2>/dev/null)
                if [[ $? -eq 0 && -n "$resp" ]]; then
                    # Process response per-package
                    for j in "${!batch[@]}"; do
                        IFS='|' read -r eco name ver loc key <<< "${batch[$j]}"
                        pkg_result=$(echo "$resp" | jq ".results[$j]")
                        osv_cache_set "$key" "$pkg_result"
                        vulns_count=$(echo "$pkg_result" | jq -r '.vulns // [] | length')
                        if [[ "$vulns_count" -gt 0 ]]; then
                            while IFS= read -r vid; do
                                is_mal="false"
                                [[ "$vid" == MAL-* ]] && is_mal="true"
                                echo "$eco|$name|$ver|$vid|$is_mal|$loc" >> "$OSV_TMP"
                            done < <(echo "$pkg_result" | jq -r '.vulns[].id')
                        fi
                    done
                    success=true
                else
                    [[ $attempt -lt 3 ]] && sleep $((2 * attempt))
                fi
            done
            [[ "$success" == "false" ]] && say WARN "OSV batch failed after 3 attempts"
            sleep 0.2
        done
    fi

    # Tally OSV findings
    OSV_MAL=0; OSV_VUL=0
    if [[ -s "$OSV_TMP" ]]; then
        OSV_MAL=$(awk -F'|' '$5=="true"' "$OSV_TMP" | wc -l | tr -d ' ')
        OSV_VUL=$(awk -F'|' '$5=="false"' "$OSV_TMP" | wc -l | tr -d ' ')
    fi

    if [[ $OSV_MAL -gt 0 ]]; then
        say ALERT "MALICIOUS: $OSV_MAL hits"
        while IFS='|' read -r eco name ver vid is_mal loc; do
            [[ "$is_mal" == "true" ]] || continue
            write_ioc "OSV_MALICIOUS" "$eco/$name@$ver | $vid" \
                "$(jq -n --arg n "$name" --arg v "$ver" --arg e "$eco" --arg a "$vid" --arg l "$loc" \
                  '{name:$n,version:$v,ecosystem:$e,advisory:$a,location:$l}')"
        done < "$OSV_TMP"
    else
        say OK "No malicious (MAL-*) findings."
    fi

    if [[ $OSV_VUL -gt 0 ]]; then
        say WARN "Vulnerable packages: $OSV_VUL"
        # Show top 10 unique vulnerable packages
        awk -F'|' '$5=="false" {print $1"/"$2"@"$3}' "$OSV_TMP" | sort | uniq -c | sort -rn | head -10 | while read -r count pkg; do
            say WARN "  $pkg: $count advisories"
        done
    fi
fi

# --- C2 check (deep only, requires DNS introspection — limited on macOS) ---
if [[ "$MODE" == "deep" ]]; then
    section "C2 DOMAIN INDICATORS"
    C2_FOUND=false

    # /etc/hosts check
    if [[ -f /etc/hosts ]]; then
        for d in "${C2_DOMAINS[@]}"; do
            if grep -q "$d" /etc/hosts 2>/dev/null; then
                write_ioc "C2_HOSTS_FILE" "$d" "$(jq -n --arg d "$d" '{domain:$d,source:"hosts_file"}')"
                C2_FOUND=true
            fi
        done
    fi

    # macOS: scutil --dns is limited; Linux: check resolv cache if systemd-resolve
    if have systemd-resolve; then
        for d in "${C2_DOMAINS[@]}"; do
            if systemd-resolve --statistics 2>/dev/null | grep -q "$d"; then
                write_ioc "C2_DNS_CACHE" "$d" "$(jq -n --arg d "$d" '{domain:$d,source:"systemd_resolve"}')"
                C2_FOUND=true
            fi
        done
    fi

    [[ "$C2_FOUND" == "false" ]] && say OK "No C2 domain indicators."
fi

# --- Workflow tamper check ---
section "WORKFLOW TAMPER CHECK"
WF_COUNT=0
for scope in "${SCAN_SCOPE[@]}"; do
    while IFS= read -r -d '' wf; do
        wf_mtime=$(stat -c %Y "$wf" 2>/dev/null || stat -f %m "$wf" 2>/dev/null || echo 0)
        [[ $wf_mtime -lt $CUTOFF_EPOCH ]] && continue
        WF_COUNT=$((WF_COUNT + 1))

        reason=""
        if grep -qE 'curl\s+[^|]+\|(\s*[^|]+\|)*\s*(sudo\s+)?(sh|bash|zsh|python[0-9.]*)\b' "$wf" 2>/dev/null; then
            reason="pipe-to-shell"
        elif grep -qE 'wget\s+[^|]+-O-?\s*\|' "$wf" 2>/dev/null; then
            reason="wget pipe-to-shell"
        elif grep -qE 'base64\s+(-d|--decode)' "$wf" 2>/dev/null; then
            reason="base64 decode"
        elif grep -qE 'eval\s+(`|\$\()' "$wf" 2>/dev/null; then
            reason="eval execution"
        elif grep -qE 'ACTIONS_RUNTIME_TOKEN|ACTIONS_CACHE_URL' "$wf" 2>/dev/null; then
            reason="runner token exfil pattern"
        fi

        if [[ -n "$reason" ]]; then
            write_ioc "WORKFLOW_SUSPICIOUS" "$wf | $reason" \
                "$(jq -n --arg f "$wf" --arg r "$reason" '{file:$f,reason:$r}')"
        else
            say WARN "Modified workflow: $wf"
            add_finding "WARN" "workflows" "modified_workflow" "$wf" \
                "$(jq -n --arg f "$wf" '{file:$f}')"
        fi
    done < <(find "$scope" -path "*/.github/workflows/*" \( -name "*.yml" -o -name "*.yaml" \) -print0 2>/dev/null)
done
[[ $WF_COUNT -eq 0 ]] && say OK "No recently modified workflows."

# --- Claude Code / VSCode persistence files (TeamPCP, May 2026) ---
section "PERSISTENCE FILE CHECK"
PERSIST_COUNT=0
for scope in "${SCAN_SCOPE[@]}"; do
    for rel in "${PERSISTENCE_FILES[@]}"; do
        # rglob equivalent
        while IFS= read -r -d '' f; do
            write_ioc "PERSISTENCE_FILE" "$f (matches $rel)" \
                "$(jq -n --arg f "$f" --arg p "$rel" '{file:$f,pattern:$p}')"
            PERSIST_COUNT=$((PERSIST_COUNT + 1))
        done < <(find "$scope" -path "*/$rel" -print0 2>/dev/null)
    done
done
[[ $PERSIST_COUNT -eq 0 ]] && say OK "No persistence files."

# --- Git 2099-date commits ---
section "GIT 2099-DATE COMMITS"
GIT_ANOMS=0
if have git; then
    git_depth=2
    [[ "$MODE" == "deep" ]] && git_depth=5
    for scope in "${SCAN_SCOPE[@]}"; do
        while IFS= read -r -d '' gd; do
            repo=$(dirname "$gd")
            while IFS= read -r line; do
                if [[ "$line" =~ ^[0-9a-f]{40}\ 209[0-9] ]]; then
                    # Redact tokens from line just in case
                    safe_line=$(echo "$line" | sed -E 's|://[^/@[:space:]]+@|://<REDACTED>@|g')
                    write_ioc "GIT_SPOOFED_DATE" "$repo | $safe_line" \
                        "$(jq -n --arg r "$repo" --arg e "$safe_line" '{repo:$r,entry:$e}')"
                    GIT_ANOMS=$((GIT_ANOMS + 1))
                fi
            done < <(git -C "$repo" log --format="%H %ai %s" --all 2>/dev/null)
        done < <(find "$scope" -maxdepth "$git_depth" -name ".git" -type d -print0 2>/dev/null)
    done
fi
[[ $GIT_ANOMS -eq 0 ]] && say OK "No spoofed-date commits."

# --- Deep mode extras: env vars, cred files ---
if [[ "$MODE" == "deep" ]]; then
    section "ENVIRONMENT VARS"
    SENS_COUNT=0
    SENS_VARS=()
    for varname in $(env | cut -d= -f1); do
        case "$varname" in
            OP_*|*PASS*|*SECRET*|*TOKEN*|*API_KEY*|AWS_*|GITHUB_*|GH_*|NPM_TOKEN*|ANTHROPIC*|*PRIVATE_KEY*|*CREDENTIAL*|BW_*)
                SENS_VARS+=("$varname"); SENS_COUNT=$((SENS_COUNT + 1)) ;;
        esac
    done
    if [[ $SENS_COUNT -gt 0 ]]; then
        say WARN "$SENS_COUNT sensitive env vars present"
        details=$(printf '%s\n' "${SENS_VARS[@]}" | jq -R . | jq -s '{vars:.}')
        add_finding "WARN" "env_vars" "sensitive_env" "$SENS_COUNT sensitive env vars" "$details"
    else
        say OK "No sensitive env vars."
    fi

    section "CREDENTIAL FILES"
    CRED_COUNT=0
    for loc in "$HOME" "$HOME/.ssh" "$HOME/.aws" "$HOME/.config"; do
        [[ -d "$loc" ]] || continue
        while IFS= read -r f; do
            CRED_COUNT=$((CRED_COUNT + 1))
            say WARN "  $f"
        done < <(find "$loc" -maxdepth 2 \( -name "*.env" -o -name "*.env.local" -o -name "*.env.production" -o -name ".npmrc" -o -name ".pypirc" -o -name ".netrc" -o -name "credentials" -o -name "*.pem" -o -name "id_rsa" -o -name "id_ed25519" \) 2>/dev/null)
    done
    [[ $CRED_COUNT -eq 0 ]] && say OK "No credential files in scanned locations."
fi

# --- GitHub exfil check ---
if [[ -n "$GITHUB_USER" || -n "$GITHUB_TOKEN" ]]; then
    section "GITHUB EXFIL REPO CHECK"
    if [[ -n "$GITHUB_TOKEN" ]]; then
        gh_url="https://api.github.com/user/repos?per_page=100&type=all"
        gh_auth="Authorization: Bearer $GITHUB_TOKEN"
    else
        gh_url="https://api.github.com/users/$GITHUB_USER/repos?per_page=100"
        gh_auth=""
    fi

    GH_HITS=0
    if [[ -n "$gh_auth" ]]; then
        resp=$(curl -sS -H "$gh_auth" -H "User-Agent: ShaiHulud-Audit/3.0" -H "Accept: application/vnd.github+json" --max-time 20 "$gh_url" 2>/dev/null)
    else
        resp=$(curl -sS -H "User-Agent: ShaiHulud-Audit/3.0" -H "Accept: application/vnd.github+json" --max-time 20 "$gh_url" 2>/dev/null)
    fi

    if [[ -n "$resp" ]]; then
        sigs=("niagA oG eW ereH :duluH-iahS" "Shai-Hulud" "duluH-iahS" "TeamPCP" "A Gift From TeamPCP" "LongLiveTheResistanceAgainstMachines")
        while IFS= read -r line; do
            full=$(echo "$line" | jq -r '.full_name // ""')
            desc=$(echo "$line" | jq -r '.description // ""')
            url=$(echo "$line" | jq -r '.html_url // ""')
            blob="$full | $desc"
            for s in "${sigs[@]}"; do
                if [[ "$blob" == *"$s"* ]]; then
                    write_ioc "GITHUB_EXFIL_REPO" "$full | $desc | $url" \
                        "$(jq -n --arg r "$full" --arg u "$url" --arg d "$desc" '{repo:$r,url:$u,description:$d}')"
                    GH_HITS=$((GH_HITS + 1))
                    break
                fi
            done
        done < <(echo "$resp" | jq -c '.[]?' 2>/dev/null)
    fi
    [[ $GH_HITS -eq 0 ]] && say OK "No exfil-indicator repos."
fi

# --- Optional pip-audit ---
if [[ "$MODE" == "deep" || "$MODE" == "project" ]]; then
    if have pip-audit; then
        section "PIP-AUDIT"
        if pip-audit-out=$(pip-audit --format=json 2>/dev/null); then
            vuln_count=$(echo "$pip-audit-out" | jq -r '[.dependencies[] | select(.vulns | length > 0)] | length')
            if [[ "$vuln_count" -gt 0 ]]; then
                say WARN "pip-audit: $vuln_count vulnerable package(s)"
            else
                say OK "pip-audit: clean"
            fi
        fi
    fi
fi

# --- Summary + output ---
section "SUMMARY"

ELAPSED=$(( $(date +%s) - SCRIPT_START ))

EXIT_CODE=0
if [[ $ALERT_COUNT -gt 0 ]]; then EXIT_CODE=2
elif [[ $WARN_COUNT -gt 0 && $FAIL_ON_LEVEL -le 1 ]]; then EXIT_CODE=1
fi

TOTAL_PKG=$(wc -l < "$PKG_TMP" 2>/dev/null | tr -d ' ')
TOTAL_PKG=${TOTAL_PKG:-0}
NPM_PKG=$(awk -F'|' '$1=="npm"' "$PKG_TMP" 2>/dev/null | wc -l | tr -d ' ')
PYPI_PKG=$(awk -F'|' '$1=="PyPI"' "$PKG_TMP" 2>/dev/null | wc -l | tr -d ' ')
INSTALL_SCR=$(awk -F'|' '$5=="true"' "$PKG_TMP" 2>/dev/null | wc -l | tr -d ' ')
KNOWN_BAD=$(awk -F'|' '$6=="true"' "$PKG_TMP" 2>/dev/null | wc -l | tr -d ' ')
OSV_MAL_FINAL=${OSV_MAL:-0}
OSV_VUL_FINAL=${OSV_VUL:-0}

# Build next_actions
if [[ $ALERT_COUNT -gt 0 ]]; then
    NEXT_ACTIONS='["CRITICAL: do not commit. Treat machine as potentially compromised.","Rotate all credentials accessible from this machine."]'
elif [[ $WARN_COUNT -gt 0 ]]; then
    NEXT_ACTIONS='["Warnings present — review before commit."]'
else
    NEXT_ACTIONS='["Clean. Safe to proceed."]'
fi

RESULT=$(jq -n \
    --arg ver "3.0" --arg mode "$MODE" \
    --arg ts "$(date -Iseconds)" --argjson elapsed "$ELAPSED" \
    --arg outdir "$OUTPUT_DIR" --arg report "$REPORT_FILE" \
    --argjson scope "$(printf '%s\n' "${SCAN_SCOPE[@]}" | jq -R . | jq -s .)" \
    --argjson total "$TOTAL_PKG" --argjson npm "$NPM_PKG" --argjson pypi "$PYPI_PKG" \
    --argjson mal "$OSV_MAL_FINAL" --argjson vul "$OSV_VUL_FINAL" \
    --argjson inst "$INSTALL_SCR" --argjson kbad "$KNOWN_BAD" \
    --argjson alerts "$ALERT_COUNT" --argjson warns "$WARN_COUNT" --argjson exit "$EXIT_CODE" \
    --argjson alerts_arr "$ALERTS_JSON" --argjson warns_arr "$WARNINGS_JSON" \
    --argjson next "$NEXT_ACTIONS" \
    '{
        version:$ver, mode:$mode, scope:$scope, timestamp:$ts,
        duration_seconds:$elapsed, output_dir:$outdir, report_path:$report,
        summary: {
            packages_scanned:$total, npm_packages:$npm, pypi_packages:$pypi,
            osv_malicious:$mal, osv_vulnerable:$vul,
            install_scripts:$inst, known_bad_offline:$kbad,
            alert_count:$alerts, warn_count:$warns, exit_code:$exit
        },
        alerts: $alerts_arr,
        warnings: $warns_arr,
        next_actions: $next
    }')

echo "$RESULT" > "$JSON_FILE"
echo "$RESULT" > "$LAST_RUN_FILE"

say INFO "Duration: ${ELAPSED}s | Packages: $TOTAL_PKG | Alerts: $ALERT_COUNT | Warns: $WARN_COUNT | Exit: $EXIT_CODE"

if [[ "$JSON_OUTPUT" == "true" ]]; then
    echo "$RESULT"
elif [[ "$QUIET" != "true" ]]; then
    echo "" >&2
    echo "Report: $OUTPUT_DIR" >&2
    if [[ $ALERT_COUNT -gt 0 ]]; then
        printf '\033[31m\n!! CRITICAL — do not commit.\033[0m\n' >&2
        echo "$NEXT_ACTIONS" | jq -r '.[]' | while read -r a; do printf '\033[31m  - %s\033[0m\n' "$a" >&2; done
    elif [[ $WARN_COUNT -gt 0 ]]; then
        printf '\033[33m\nWarnings — review:\033[0m\n' >&2
        echo "$NEXT_ACTIONS" | jq -r '.[]' | while read -r a; do printf '\033[33m  - %s\033[0m\n' "$a" >&2; done
    else
        printf '\033[32m\nClean. Safe to proceed.\033[0m\n' >&2
    fi
fi

exit $EXIT_CODE
