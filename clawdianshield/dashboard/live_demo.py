"""
dashboard/live_demo.py

Continuously appends synthetic NormalizedEvent JSONL into evidence/ so the
SOC dashboard's WebSocket-backed live stream carries traffic during a demo
without needing the full Docker observer stack.

Run alongside `python -m dashboard.server`:
    python -m dashboard.live_demo
    python -m dashboard.live_demo --eps 4 --evidence-dir evidence
"""
from __future__ import annotations

import argparse
import json
import random
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


HOSTS = ["workstation-1", "server-1"]
FILE_TARGETS = [
    "/tmp/clawdianshield/sensitive.conf",
    "/tmp/clawdianshield/exec_artifact.sh",
    "/tmp/clawdianshield/inventory.txt",
    "/tmp/clawdianshield/stage_archive.tar.gz",
    "/tmp/clawdianshield/cron_stub.txt",
]
ACCOUNTS = ["svc-lab-user", "root", "analyst-3"]


def _ts() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _gen_event(run_id: str) -> tuple[str, dict]:
    is_auth = random.random() < 0.35
    if is_auth:
        if random.random() < 0.6:
            return "auth_events.jsonl", {
                "run_id": run_id,
                "scenario_id": "live_demo",
                "host": random.choice(HOSTS),
                "event_type": "auth_failure",
                "timestamp": _ts(),
                "severity": "high",
                "details": {"raw": "pam_unix(sudo:auth): authentication failure"},
                "collector": "log_observer",
            }
        return "auth_events.jsonl", {
            "run_id": run_id,
            "scenario_id": "live_demo",
            "host": random.choice(HOSTS),
            "event_type": "auth_success",
            "timestamp": _ts(),
            "severity": "medium",
            "details": {"account": random.choice(ACCOUNTS), "raw": "session opened"},
            "collector": "log_observer",
        }
    etype, sev = random.choice([
        ("file_modify", "high"),
        ("file_create", "medium"),
        ("file_delete", "high"),
        ("file_rename", "high"),
    ])
    details = {"path": random.choice(FILE_TARGETS)}
    if etype in ("file_create", "file_modify"):
        details["sha256"] = uuid.uuid4().hex + uuid.uuid4().hex[:32]
    return "file_events.jsonl", {
        "run_id": run_id,
        "scenario_id": "live_demo",
        "host": random.choice(HOSTS),
        "event_type": etype,
        "timestamp": _ts(),
        "severity": sev,
        "details": details,
        "collector": "file_observer",
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Live demo event generator")
    p.add_argument("--evidence-dir", default="evidence")
    p.add_argument("--eps", type=float, default=2.0, help="Events per second target")
    args = p.parse_args()

    evidence_dir = Path(args.evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"live-{uuid.uuid4().hex[:8]}"
    interval = 1.0 / max(args.eps, 0.1)
    print(f"[live_demo] run_id={run_id} writing to {evidence_dir} at ~{args.eps} eps")
    try:
        while True:
            fname, evt = _gen_event(run_id)
            with open(evidence_dir / fname, "a", encoding="utf-8") as f:
                f.write(json.dumps(evt) + "\n")
            time.sleep(interval * random.uniform(0.6, 1.4))
    except KeyboardInterrupt:
        print("\n[live_demo] stopped")


if __name__ == "__main__":
    main()
