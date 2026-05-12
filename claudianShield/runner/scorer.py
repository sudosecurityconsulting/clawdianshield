import json
import sys
import glob
import os
from datetime import datetime

# Unified Kill Chain (UKC) Mapping
# Maps our ClawdianShield behaviors to the 18 phases of the Unified Kill Chain
UKC_MAPPING = {
    "auth_anomalies": "Credential Access",
    "remote_execution_artifacts": "Execution",
    "file_tamper": "Impact",
    "staging": "Collection",
    "persistence_path_changes": "Persistence",
    "anti_forensics": "Defense Evasion",
    "cleanup": "Defense Evasion",
    "exploit_execution": "Exploitation",
    "hello_world_custom": "Execution"
}

def calculate_score(exec_log_path: str) -> dict:
    """
    Parses an exec_log.json file and computes an explicit, non-blackbox score.
    Maps executed behaviors to Unified Kill Chain phases.
    """
    with open(exec_log_path, 'r') as f:
        log_data = json.load(f)

    # 1. Metric: Execution Success
    total_steps = len(log_data.get("steps", []))
    step_failures = len(log_data.get("step_failures", []))
    
    execution_success_pct = 100.0
    if total_steps > 0:
        execution_success_pct = ((total_steps - step_failures) / total_steps) * 100.0

    # 2. Metric: Telemetry Visibility
    expected_telemetry = log_data.get("expected_telemetry", {})
    coverage_gaps = log_data.get("coverage_gaps", [])
    
    total_expected = len(expected_telemetry)
    gaps_count = len(coverage_gaps)
    
    telemetry_visibility_pct = 100.0
    if total_expected > 0:
        telemetry_visibility_pct = ((total_expected - gaps_count) / total_expected) * 100.0

    # 3. Metric: Safety Compliance
    # If the run was completed and didn't abort due to safety constraints
    # (Assuming if we got a log, it passed validation, but we check if status is 'aborted')
    safety_compliance_pct = 100.0 if log_data.get("status") in ("completed", "dry_run") else 0.0

    # Overall Score (Average of the 3 metrics)
    overall_score = (execution_success_pct + telemetry_visibility_pct + safety_compliance_pct) / 3.0

    # Map behaviors to UKC
    behaviors_planned = log_data.get("behaviors_planned", [])
    ukc_phases_hit = list(set([UKC_MAPPING.get(b, "Unknown Phase") for b in behaviors_planned]))

    score_report = {
        "run_id": log_data.get("run_id"),
        "scenario_name": log_data.get("scenario_name"),
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "overall_score": round(overall_score, 2),
        "metrics": {
            "execution_success": {
                "score": round(execution_success_pct, 2),
                "details": f"{total_steps - step_failures} out of {total_steps} steps succeeded."
            },
            "telemetry_visibility": {
                "score": round(telemetry_visibility_pct, 2),
                "details": f"Captured {total_expected - gaps_count} out of {total_expected} expected telemetry types."
            },
            "safety_compliance": {
                "score": round(safety_compliance_pct, 2),
                "details": f"Status: {log_data.get('status')}"
            }
        },
        "unified_kill_chain_mapping": {
            "behaviors_executed": behaviors_planned,
            "ukc_phases_represented": ukc_phases_hit
        }
    }

    return score_report

def main():
    if len(sys.argv) > 1:
        # Score a specific file
        target_file = sys.argv[1]
        if not os.path.exists(target_file):
            print(f"Error: File {target_file} not found.")
            sys.exit(1)
        score = calculate_score(target_file)
        out_file = target_file.replace("_exec_log.json", "_score.json")
        with open(out_file, 'w') as f:
            json.dump(score, f, indent=2)
        print(f"[{score['run_id']}] Scored: {score['overall_score']}/100 -> {out_file}")
    else:
        # Score all logs in reports/
        log_files = glob.glob("reports/*_exec_log.json")
        print(f"Found {len(log_files)} execution logs to score.")
        for log_file in log_files:
            score = calculate_score(log_file)
            out_file = log_file.replace("_exec_log.json", "_score.json")
            with open(out_file, 'w') as f:
                json.dump(score, f, indent=2)
            print(f"[{score['run_id']}] Scored: {score['overall_score']}/100 -> {out_file}")

if __name__ == "__main__":
    main()
