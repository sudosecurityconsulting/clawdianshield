"""
dashboard/seed_demo.py

Generates believable evidence + an exec_log report so the SOC dashboard
can be demonstrated without the full Docker observer stack running.

Writes:
  evidence/file_events.jsonl
  evidence/auth_events.jsonl
  reports/<run_id>_exec_log.json

This emits realistic NormalizedEvent JSONL and a real executor exec_log
shape so /api/stats, /api/runs, and the live stream all populate.

Usage:
    python -m dashboard.seed_demo
    python -m dashboard.seed_demo --reset   # wipe evidence/ + reports/ first
    python -m dashboard.seed_demo --burst 200
"""
from __future__ import annotations

import argparse
import json
import random
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


HOSTS = ["workstation-1", "server-1"]

FILE_TARGETS = [
    "/tmp/clawdianshield/sensitive.conf",
    "/tmp/clawdianshield/sensitive.conf.bak",
    "/tmp/clawdianshield/exec_artifact.sh",
    "/tmp/clawdianshield/inventory.txt",
    "/tmp/clawdianshield/stage_archive.tar.gz",
    "/tmp/clawdianshield/cron_stub.txt",
    "/tmp/clawdianshield/init.d_stub",
]

ACCOUNTS = ["svc-lab-user", "root", "analyst-3", "svc-runner"]


def _ts(t: datetime) -> str:
    return t.replace(microsecond=0).astimezone(timezone.utc).isoformat()


def _emit(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def seed(evidence_dir: Path, reports_dir: Path, burst: int, reset: bool) -> None:
    if reset:
        for p in evidence_dir.glob("*.jsonl"):
            p.unlink()
        for p in reports_dir.glob("*_exec_log.json"):
            p.unlink()

    run_id = (
        f"exec-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        f"-{uuid.uuid4().hex[:6]}"
    )
    scenario_id = "full_storyline_001"
    started = datetime.now(timezone.utc) - timedelta(minutes=4)
    completed = datetime.now(timezone.utc)

    file_events = evidence_dir / "file_events.jsonl"
    auth_events = evidence_dir / "auth_events.jsonl"

    # ---- auth burst (T1110) ----
    t = started
    for i in range(5):
        _emit(auth_events, {
            "run_id": run_id,
            "scenario_id": scenario_id,
            "host": "workstation-1",
            "event_type": "auth_failure",
            "timestamp": _ts(t),
            "severity": "high",
            "details": {
                "raw": (
                    f"{_ts(t)} victim sudo: pam_unix(sudo:auth): authentication "
                    f"failure; logname= uid=1000 euid=0 tty=/dev/pts/0 "
                    f"ruser=svc-lab-user rhost="
                ),
            },
            "collector": "log_observer",
        })
        t += timedelta(seconds=2 + random.random())
    _emit(auth_events, {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "host": "workstation-1",
        "event_type": "auth_success",
        "timestamp": _ts(t),
        "severity": "medium",
        "details": {
            "account": "svc-lab-user",
            "raw": f"{_ts(t)} victim sudo: session opened for user svc-lab-user by svc-runner(uid=0)",
        },
        "collector": "log_observer",
    })
    t += timedelta(seconds=4)

    # ---- file tamper burst ----
    sequence = [
        ("file_create", "/tmp/clawdianshield/sensitive.conf", "medium"),
        ("file_modify", "/tmp/clawdianshield/sensitive.conf", "high"),
        ("file_rename", "/tmp/clawdianshield/sensitive.conf", "high"),
        ("file_create", "/tmp/clawdianshield/sensitive.conf", "medium"),
        ("file_create", "/tmp/clawdianshield/exec_artifact.sh", "medium"),
        ("file_modify", "/tmp/clawdianshield/exec_artifact.sh", "high"),
        ("file_create", "/tmp/clawdianshield/inventory.txt", "medium"),
        ("file_create", "/tmp/clawdianshield/stage_archive.tar.gz", "medium"),
        ("file_create", "/tmp/clawdianshield/cron_stub.txt", "medium"),
        ("file_create", "/tmp/clawdianshield/init.d_stub", "medium"),
        ("file_modify", "/tmp/clawdianshield/sensitive.conf.bak", "high"),
        ("file_delete", "/tmp/clawdianshield/exec_artifact.sh", "high"),
    ]
    for etype, path, sev in sequence:
        details = {"path": path}
        if etype in ("file_create", "file_modify"):
            details["sha256"] = uuid.uuid4().hex + uuid.uuid4().hex[:32]
        if etype == "file_rename":
            details["dest_path"] = path + ".bak"
        _emit(file_events, {
            "run_id": run_id,
            "scenario_id": scenario_id,
            "host": "workstation-1",
            "event_type": etype,
            "timestamp": _ts(t),
            "severity": sev,
            "details": details,
            "collector": "file_observer",
        })
        t += timedelta(seconds=random.uniform(0.6, 2.4))

    # ---- ambient burst (random extra events to give the dashboard volume) ----
    severities = [
        ("info", 0.45), ("low", 0.2), ("medium", 0.2), ("high", 0.1), ("critical", 0.05),
    ]
    for _ in range(burst):
        kind = random.choice([
            ("file_modify", "high"),
            ("file_create", "medium"),
            ("file_delete", "high"),
            ("auth_failure", "high"),
            ("auth_success", "medium"),
            ("auth_unknown", "info"),
        ])
        host = random.choice(HOSTS)
        path = random.choice(FILE_TARGETS)
        is_auth = kind[0].startswith("auth_")
        record = {
            "run_id": run_id,
            "scenario_id": scenario_id,
            "host": host,
            "event_type": kind[0],
            "timestamp": _ts(t),
            "severity": kind[1] if random.random() < 0.85 else _weighted(severities),
            "details": (
                {"account": random.choice(ACCOUNTS), "raw": "ambient log"}
                if is_auth
                else {"path": path, "sha256": uuid.uuid4().hex + uuid.uuid4().hex[:32]}
            ),
            "collector": "log_observer" if is_auth else "file_observer",
        }
        out = auth_events if is_auth else file_events
        _emit(out, record)
        t += timedelta(seconds=random.uniform(0.05, 0.5))

    # ---- exec log shaped exactly like runner.executor writes ----
    behaviors = [
        "auth_anomalies",
        "remote_execution_artifacts",
        "file_tamper",
        "staging",
        "persistence_path_changes",
        "anti_forensics",
        "cleanup",
    ]
    steps = []
    for b in behaviors:
        for i in range(random.choice([2, 3, 4])):
            steps.append({
                "behavior": b,
                "step_id": f"{b}_step_{i+1}",
                "command": f"<demo synthetic command for {b}>",
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "elapsed_s": round(random.uniform(0.05, 0.6), 3),
                "timestamp": _ts(started + timedelta(seconds=len(steps) * 1.2)),
                "status": "ok",
            })
    expected = {
        "file_events": True, "process_events": True, "auth_events": True,
        "host_to_host_correlation": True, "timeline_reconstruction": True, "hash_deltas": True,
    }
    coverage = {
        "file_events": {"expected": True, "produced_by": ["file_tamper", "staging"]},
        "process_events": {"expected": True, "produced_by": ["remote_execution_artifacts"]},
        "auth_events": {"expected": True, "produced_by": ["auth_anomalies"]},
        "host_to_host_correlation": {"expected": True, "produced_by": []},
        "timeline_reconstruction": {"expected": True, "produced_by": ["anti_forensics"]},
        "hash_deltas": {"expected": True, "produced_by": ["file_tamper", "staging"]},
    }
    log = {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "scenario_name": "Full Synthetic Intrusion Storyline",
        "container": "clawdian_victim",
        "dry_run": False,
        "started_at": _ts(started),
        "completed_at": _ts(completed),
        "status": "completed",
        "behaviors_planned": behaviors,
        "steps": steps,
        "expected_telemetry": expected,
        "telemetry_coverage": coverage,
        "coverage_gaps": ["host_to_host_correlation"],
        "step_failures": [],
    }
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"{run_id}_exec_log.json").write_text(
        json.dumps(log, indent=2), encoding="utf-8"
    )
    print(f"[seed_demo] run_id={run_id}")
    print(f"[seed_demo] events written to {evidence_dir}")
    print(f"[seed_demo] report written to {reports_dir / (run_id + '_exec_log.json')}")


def _weighted(pairs):
    r = random.random()
    acc = 0.0
    for v, w in pairs:
        acc += w
        if r <= acc:
            return v
    return pairs[-1][0]


def main() -> None:
    p = argparse.ArgumentParser(description="Seed demo evidence for the SOC dashboard")
    p.add_argument("--evidence-dir", default="evidence")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--burst", type=int, default=120, help="Ambient noise event count")
    p.add_argument("--reset", action="store_true", help="Wipe evidence and reports first")
    args = p.parse_args()
    seed(Path(args.evidence_dir), Path(args.reports_dir), args.burst, args.reset)


if __name__ == "__main__":
    main()
