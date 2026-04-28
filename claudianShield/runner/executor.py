#!/usr/bin/env python3
"""
runner/executor.py

Deterministic subprocess execution engine for ClawdianShield scenarios.

Translates a scenario JSON behavior_profile into ordered docker exec commands
against a target container (default: clawdian_victim). Each behavior maps to
an ordered list of sh -c shell steps that produce the system artifacts — file
ops, auth log entries, process events — that the collectors are instrumented
to detect.

Writes a structured execution log to reports/<run_id>_exec_log.json tracking
every step run versus every telemetry class the scenario expected.

Usage:
    python runner/executor.py scenarios/fim_burst_tamper.json
    python runner/executor.py scenarios/fim_burst_tamper.json --container my_victim
    python runner/executor.py scenarios/fim_burst_tamper.json --dry-run
    python runner/executor.py scenarios/fim_burst_tamper.json --reports /custom/path

Exit codes:
    0  all steps succeeded (or dry-run)
    1  safety constraint violation or bad input
    2  one or more steps returned non-zero
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Execution constants
# ---------------------------------------------------------------------------

# Fixed deterministic order mirrors realistic attack-chain sequence.
EXECUTION_ORDER: list[str] = [
    "auth_anomalies",
    "remote_execution_artifacts",
    "file_tamper",
    "staging",
    "persistence_path_changes",
    "anti_forensics",
    "cleanup",
]

# Repeated auth failure log line — appended directly to /var/log/auth.log,
# which is bind-mounted to the host so log_observer can tail it. We bypass
# logger/syslog entirely to keep the victim container stateless.
_AUTH_LOG_PATH = "/var/log/auth.log"
_AUTH_FAILURE_CMD = (
    f"echo \"$(date -u '+%Y-%m-%dT%H:%M:%SZ') victim sudo: "
    f"pam_unix(sudo:auth): authentication failure; logname= uid=1000 euid=0 "
    f"tty=/dev/pts/0 ruser=svc-lab-user rhost=\" >> {_AUTH_LOG_PATH}"
)
_AUTH_SUCCESS_CMD = (
    f"echo \"$(date -u '+%Y-%m-%dT%H:%M:%SZ') victim sudo: "
    f"session opened for user svc-lab-user by svc-runner(uid=0)\" "
    f">> {_AUTH_LOG_PATH}"
)

# Maps behavior_profile key → ordered list of (step_id, sh -c command) tuples.
# Commands run inside the target container via: docker exec <container> sh -c "<cmd>"
# All paths are scoped to /tmp/clawdianshield to avoid touching real host state.
BEHAVIOR_STEPS: dict[str, list[tuple[str, str]]] = {
    "file_tamper": [
        (
            "file_create_baseline",
            "mkdir -p /tmp/clawdianshield && echo 'mode=baseline' > /tmp/clawdianshield/sensitive.conf",
        ),
        (
            "file_modify",
            "echo 'mode=modified' > /tmp/clawdianshield/sensitive.conf",
        ),
        (
            "file_rename",
            "mv /tmp/clawdianshield/sensitive.conf /tmp/clawdianshield/sensitive.conf.bak",
        ),
        (
            "file_create_replacement",
            "echo 'mode=replaced' > /tmp/clawdianshield/sensitive.conf",
        ),
    ],
    "auth_anomalies": [
        ("auth_failure_1", _AUTH_FAILURE_CMD),
        ("auth_failure_2", _AUTH_FAILURE_CMD),
        ("auth_failure_3", _AUTH_FAILURE_CMD),
        ("auth_failure_4", _AUTH_FAILURE_CMD),
        ("auth_failure_5", _AUTH_FAILURE_CMD),
        ("auth_success", _AUTH_SUCCESS_CMD),
    ],
    "remote_execution_artifacts": [
        (
            "artifact_drop",
            "mkdir -p /tmp/clawdianshield && "
            "printf '#!/bin/sh\\nid\\nhostname\\n' > /tmp/clawdianshield/exec_artifact.sh",
        ),
        (
            "artifact_exec",
            "chmod +x /tmp/clawdianshield/exec_artifact.sh "
            "&& /tmp/clawdianshield/exec_artifact.sh",
        ),
    ],
    "staging": [
        (
            "collect_enum",
            "find /tmp/clawdianshield -type f > /tmp/clawdianshield/inventory.txt",
        ),
        (
            "archive_create",
            "cd /tmp && tar czf /tmp/clawdianshield/stage_archive.tar.gz "
            "clawdianshield/inventory.txt",
        ),
    ],
    "persistence_path_changes": [
        (
            "crontab_stub",
            "echo '* * * * * /bin/sh /tmp/clawdianshield/exec_artifact.sh' "
            "> /tmp/clawdianshield/cron_stub.txt",
        ),
        (
            "initd_stub",
            "echo '# stub persistence entry' > /tmp/clawdianshield/init.d_stub",
        ),
    ],
    "anti_forensics": [
        (
            "log_truncate",
            "truncate -s 0 /tmp/clawdianshield/sensitive.conf.bak",
        ),
        (
            "artifact_wipe",
            "rm -f /tmp/clawdianshield/exec_artifact.sh",
        ),
    ],
    "cleanup": [
        (
            "rm_stage_archive",
            "rm -f /tmp/clawdianshield/stage_archive.tar.gz",
        ),
        (
            "rm_working_contents",
            # Wipe contents only — /tmp/clawdianshield is bind-mounted from
            # the host (./victim_state) and removing the mount point itself
            # fails with "Resource busy". Leaving the directory present also
            # keeps subsequent runs from racing against re-create.
            "rm -rf /tmp/clawdianshield/* /tmp/clawdianshield/.[!.]* 2>/dev/null; true",
        ),
    ],
}

# Declares which telemetry event types each behavior is expected to produce.
# Cross-referenced against expected_telemetry in the scenario to compute coverage gaps.
BEHAVIOR_PRODUCES: dict[str, set[str]] = {
    "file_tamper":                {"file_events", "hash_deltas"},
    "auth_anomalies":             {"auth_events"},
    "remote_execution_artifacts": {"process_events", "file_events", "auth_events"},
    "staging":                    {"file_events", "hash_deltas"},
    "persistence_path_changes":   {"file_events", "hash_deltas", "process_events"},
    "anti_forensics":             {"file_events", "timeline_reconstruction"},
    "cleanup":                    {"file_events"},
}


# ---------------------------------------------------------------------------
# Safety validation
# ---------------------------------------------------------------------------

def _validate_safety(scenario: dict[str, Any]) -> None:
    """Abort with exit code 1 if any safety constraint is not satisfied."""
    sc = scenario.get("safety_constraints", {})
    mode = scenario.get("mode", "lab_only")

    # Support for real execution of exploits
    if mode == "real_exploit":
        if not sc.get("i_know_what_i_am_doing", False):
            print("[SAFETY] Real exploit mode requires 'i_know_what_i_am_doing: true' in safety_constraints.", file=sys.stderr)
            sys.exit(1)
        print("[SAFETY] WARNING: Proceeding with real exploit execution mode!", file=sys.stderr)
        return

    # Default strict lab limits
    violations: list[str] = []
    if not sc.get("lab_environment_only", False):
        violations.append("lab_environment_only must be true")
    if not sc.get("no_real_exploit_logic", False):
        violations.append("no_real_exploit_logic must be true")
    if not sc.get("no_real_credential_attack_logic", False):
        violations.append("no_real_credential_attack_logic must be true")
    if not sc.get("no_unapproved_network_spread", False):
        violations.append("no_unapproved_network_spread must be true")
    if violations:
        print("[SAFETY] Scenario rejected — constraint violations:", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Execution helpers
# ---------------------------------------------------------------------------

def _resolve_plan(scenario: dict[str, Any]) -> list[str]:
    """Return active behaviors in deterministic attack-chain order or custom order."""
    behavior_profile = scenario.get("behavior_profile", {})
    order = scenario.get("execution_order", EXECUTION_ORDER)
    
    # Allow custom behaviors not in the default execution order to just be appended
    # if they are active but not explicitly ordered
    planned = [b for b in order if behavior_profile.get(b)]
    for b, active in behavior_profile.items():
        if active and b not in planned:
            planned.append(b)
            
    return planned


def _run_step(
    container: str,
    behavior: str,
    step_id: str,
    command: str,
    dry_run: bool,
) -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    if dry_run:
        return {
            "behavior": behavior,
            "step_id": step_id,
            "command": command,
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "elapsed_s": 0.0,
            "timestamp": ts,
            "status": "dry_run",
        }

    argv = ["docker", "exec", container, "sh", "-c", command]
    t_start = datetime.now(timezone.utc)
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        elapsed = (datetime.now(timezone.utc) - t_start).total_seconds()
        return {
            "behavior": behavior,
            "step_id": step_id,
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "elapsed_s": round(elapsed, 3),
            "timestamp": ts,
            "status": "ok" if result.returncode == 0 else "failed",
        }
    except subprocess.TimeoutExpired:
        elapsed = (datetime.now(timezone.utc) - t_start).total_seconds()
        return {
            "behavior": behavior,
            "step_id": step_id,
            "command": command,
            "returncode": -1,
            "stdout": "",
            "stderr": "step timed out after 30s",
            "elapsed_s": round(elapsed, 3),
            "timestamp": ts,
            "status": "timeout",
        }


def _compute_coverage(
    behaviors_run: list[str],
    expected_telemetry: dict[str, bool],
    custom_produces: dict[str, list[str]] = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Returns (coverage_dict, coverage_gaps).

    coverage_dict maps each expected_telemetry key to whether it was expected
    and which executed behaviors would produce it.

    coverage_gaps lists expected telemetry types that no executed behavior covers.
    """
    if custom_produces is None:
        custom_produces = {}
        
    coverage: dict[str, Any] = {}
    gaps: list[str] = []
    for telemetry_type, expected in expected_telemetry.items():
        producers = []
        for b in behaviors_run:
            built_in_produces = BEHAVIOR_PRODUCES.get(b, set())
            custom_behavior_produces = set(custom_produces.get(b, []))
            if telemetry_type in built_in_produces or telemetry_type in custom_behavior_produces:
                producers.append(b)
                
        coverage[telemetry_type] = {
            "expected": expected,
            "produced_by": producers,
        }
        if expected and not producers:
            gaps.append(telemetry_type)
    return coverage, gaps


def _write_log(log: dict[str, Any], reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = reports_dir / f"{log['run_id']}_exec_log.json"
    out_path.write_text(json.dumps(log, indent=2), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="ClawdianShield deterministic scenario executor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("scenario", help="Path to scenario JSON file")
    parser.add_argument(
        "--container",
        default="clawdian_victim",
        help="Docker container name to target (default: clawdian_victim)",
    )
    parser.add_argument(
        "--reports",
        default="reports",
        help="Output directory for execution logs (default: reports/)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and plan without executing any docker commands",
    )
    args = parser.parse_args()

    scenario_path = Path(args.scenario)
    if not scenario_path.exists():
        print(f"[ERROR] Scenario file not found: {scenario_path}", file=sys.stderr)
        sys.exit(1)

    try:
        scenario: dict[str, Any] = json.loads(scenario_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[ERROR] Failed to parse scenario JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    _validate_safety(scenario)

    run_id = (
        f"exec-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        f"-{uuid.uuid4().hex[:6]}"
    )
    started_at = datetime.now(timezone.utc).isoformat()

    behavior_profile: dict[str, bool] = scenario.get("behavior_profile", {})
    expected_telemetry: dict[str, bool] = scenario.get("expected_telemetry", {})
    behaviors_planned = _resolve_plan(scenario)
    custom_behaviors = scenario.get("custom_behaviors", {})

    print(f"[{run_id}] Scenario : {scenario.get('name', scenario.get('scenario_id'))}")
    print(f"[{run_id}] Container: {args.container}")
    print(f"[{run_id}] Dry-run  : {args.dry_run}")
    print(f"[{run_id}] Plan     : {' -> '.join(behaviors_planned) or '(none)'}")

    steps: list[dict[str, Any]] = []
    step_failures: list[dict[str, Any]] = []

    for behavior in behaviors_planned:
        # If behavior is custom, load its steps, otherwise fall back to built-in BEHAVIOR_STEPS
        if behavior in custom_behaviors:
            steps_list = [(step.get("step_id", f"step_{i}"), step.get("command", "")) 
                          for i, step in enumerate(custom_behaviors[behavior])]
        else:
            steps_list = BEHAVIOR_STEPS.get(behavior, [])
            
        for step_id, command in steps_list:
            print(f"[{run_id}]   {behavior}/{step_id}", end="", flush=True)
            result = _run_step(args.container, behavior, step_id, command, args.dry_run)
            steps.append(result)
            tag = f"  [{result['status'].upper()}]"
            print(tag)
            if result["status"] not in ("ok", "dry_run"):
                step_failures.append({
                    "step_id": step_id,
                    "behavior": behavior,
                    "returncode": result["returncode"],
                    "stderr": result["stderr"],
                })

    completed_at = datetime.now(timezone.utc).isoformat()
    custom_produces = scenario.get("custom_behavior_produces", {})
    coverage, gaps = _compute_coverage(behaviors_planned, expected_telemetry, custom_produces)

    if args.dry_run:
        overall_status = "dry_run"
    elif step_failures:
        overall_status = "completed_with_failures"
    else:
        overall_status = "completed"

    log: dict[str, Any] = {
        "run_id": run_id,
        "scenario_id": scenario.get("scenario_id"),
        "scenario_name": scenario.get("name"),
        "container": args.container,
        "dry_run": args.dry_run,
        "started_at": started_at,
        "completed_at": completed_at,
        "status": overall_status,
        "behaviors_planned": behaviors_planned,
        "steps": steps,
        "expected_telemetry": expected_telemetry,
        "telemetry_coverage": coverage,
        "coverage_gaps": gaps,
        "step_failures": step_failures,
    }

    reports_dir = Path(args.reports)
    log_path = _write_log(log, reports_dir)

    print(f"[{run_id}] Status        : {overall_status}")
    print(f"[{run_id}] Steps run     : {len(steps)}")
    print(f"[{run_id}] Failures      : {len(step_failures)}")
    print(f"[{run_id}] Coverage gaps : {gaps if gaps else 'none'}")
    print(f"[{run_id}] Log           : {log_path}")

    if step_failures:
        sys.exit(2)


if __name__ == "__main__":
    main()
