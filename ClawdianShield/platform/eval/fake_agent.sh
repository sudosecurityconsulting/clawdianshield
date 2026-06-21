#!/bin/sh
# platform/eval/fake_agent.sh
#
# Test fixture: simulates an EDR/SIEM agent writing detection alerts to
# /var/log/agent_alerts.jsonl inside the victim container.
#
# Drop this into clawdian_victim and start it before running a scenario.
# It fires a mix of TP alerts (matching common atomic technique IDs) and
# one FP to exercise the full benchmark scoring path.
#
# Usage (from the host):
#   docker cp platform/eval/fake_agent.sh clawdian_victim:/opt/clawdian_agent/fake_agent.sh
#   docker exec clawdian_victim chmod +x /opt/clawdian_agent/fake_agent.sh
#   docker exec -d clawdian_victim /opt/clawdian_agent/fake_agent.sh
#
# Or via drop_agent.py:
#   python -m platform.eval.drop_agent \
#       --binary platform/eval/fake_agent.sh \
#       --start-cmd "/opt/clawdian_agent/fake_agent.sh" \
#       --container clawdian_victim

OUT=/var/log/agent_alerts.jsonl

emit() {
    TECHNIQUE="$1"
    RULE="$2"
    SEV="${3:-medium}"
    TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    printf '{"timestamp":"%s","technique_id":"%s","rule_name":"%s","severity":"%s","raw":{}}\n' \
        "$TS" "$TECHNIQUE" "$RULE" "$SEV" >> "$OUT"
}

# Give the scenario a moment to start its first step before firing
sleep 3

# True positives — fire for techniques the atomic scenarios commonly exercise
emit "T1070"     "Indicator Removal Detected"      "high"
sleep 2
emit "T1070.004" "File Deletion Observed"           "high"
sleep 1
emit "T1059.004" "Unix Shell Command Execution"     "medium"
sleep 2
emit "T1105"     "Ingress Tool Transfer"            "medium"
sleep 1
emit "T1053"     "Scheduled Task / Cron Detected"   "high"
sleep 2
emit "T1078"     "Valid Account Usage Anomaly"      "high"
sleep 1
emit "T1110"     "Brute Force Auth Attempt"         "critical"
sleep 3

# False positive — fires for a technique not in the current run
emit "T1566.001" "Phishing Attachment Opened"       "high"

echo "[fake_agent] done — alerts written to $OUT"
