"""
Seed evidence + reports for every single-host scenario so the python
dashboard and Kibana both populate. Reads each scenarios/single-host/*.json,
generates a NormalizedEvent batch tagged with that scenario's real
scenario_id/name, and writes:

  evidence/file_events.jsonl   (appended)
  evidence/auth_events.jsonl   (appended)
  reports/<run_id>_exec_log.json  (one per scenario)

After seeding, ships the combined evidence to Elasticsearch via
platform.telemetry.forwarders.elastic_shipper.
"""
from __future__ import annotations

import json
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCENARIOS_DIR = ROOT / "scenarios" / "single-host"
EVIDENCE_DIR = ROOT / "evidence"
REPORTS_DIR = ROOT / "reports"

HOSTS_DEFAULT = ["workstation-1"]
ACCOUNTS = ["svc-lab-user", "root", "analyst-3", "svc-runner"]

FILE_TARGETS = [
    "/tmp/ClawdianShield/sensitive.conf",
    "/tmp/ClawdianShield/sensitive.conf.bak",
    "/tmp/ClawdianShield/exec_artifact.sh",
    "/tmp/ClawdianShield/inventory.txt",
    "/tmp/ClawdianShield/stage_archive.tar.gz",
    "/tmp/ClawdianShield/cron_stub.txt",
    "/tmp/ClawdianShield/init.d_stub",
    "/tmp/ClawdianShield/dependency.so",
    "/tmp/ClawdianShield/anti_forensics.log",
]

# Behaviour -> (event_types it generates, default severity)
BEHAVIOR_EMITTERS = {
    "auth_anomalies": [
        ("auth_failure", "high", "log_observer", "auth"),
        ("auth_success", "medium", "log_observer", "auth"),
    ],
    "file_tamper": [
        ("file_create", "medium", "file_observer", "file"),
        ("file_modify", "high", "file_observer", "file"),
        ("file_rename", "high", "file_observer", "file"),
    ],
    "staging": [
        ("file_create", "medium", "file_observer", "file"),
    ],
    "persistence_path_changes": [
        ("file_create", "high", "file_observer", "file"),
        ("file_modify", "high", "file_observer", "file"),
    ],
    "anti_forensics": [
        ("file_delete", "high", "file_observer", "file"),
        ("file_modify", "high", "file_observer", "file"),
    ],
    "cleanup": [
        ("file_delete", "medium", "file_observer", "file"),
    ],
    "remote_execution_artifacts": [
        ("file_create", "high", "file_observer", "file"),
        ("auth_success", "medium", "log_observer", "auth"),
    ],
    "dependency_swap": [
        ("file_modify", "high", "file_observer", "file"),
    ],
    "sensitive_config_drift": [
        ("file_modify", "high", "file_observer", "file"),
    ],
    "trusted_binary_blend": [
        ("file_modify", "high", "file_observer", "file"),
    ],
}


def _ts(t: datetime) -> str:
    return t.replace(microsecond=0).astimezone(timezone.utc).isoformat()


def _emit(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _event_for(behavior: str, scenario_id: str, run_id: str, host: str, t: datetime) -> tuple[str, dict]:
    emitters = BEHAVIOR_EMITTERS.get(behavior)
    if not emitters:
        emitters = BEHAVIOR_EMITTERS["file_tamper"]
    etype, sev, collector, channel = random.choice(emitters)

    if channel == "auth":
        details = {
            "account": random.choice(ACCOUNTS),
            "raw": f"{_ts(t)} victim sudo: pam_unix(sudo:auth) event for {behavior}",
        }
        return "auth_events.jsonl", {
            "run_id": run_id,
            "scenario_id": scenario_id,
            "host": host,
            "event_type": etype,
            "timestamp": _ts(t),
            "severity": sev,
            "details": details,
            "collector": collector,
        }
    else:
        path = random.choice(FILE_TARGETS)
        details = {"path": path}
        if etype in ("file_create", "file_modify"):
            details["sha256"] = uuid.uuid4().hex + uuid.uuid4().hex[:32]
        if etype == "file_rename":
            details["dest_path"] = path + ".bak"
        return "file_events.jsonl", {
            "run_id": run_id,
            "scenario_id": scenario_id,
            "host": host,
            "event_type": etype,
            "timestamp": _ts(t),
            "severity": sev,
            "details": details,
            "collector": collector,
        }


def seed_scenario(spec: dict) -> dict:
    scenario_id = spec["scenario_id"]
    name = spec.get("name", scenario_id)
    hosts = spec.get("hosts") or HOSTS_DEFAULT
    behaviors = [k for k, v in (spec.get("behavior_profile") or {}).items() if v]
    if not behaviors:
        behaviors = ["file_tamper"]

    run_id = (
        f"exec-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        f"-{uuid.uuid4().hex[:6]}"
    )
    started = datetime.now(timezone.utc) - timedelta(minutes=random.randint(3, 25))
    t = started
    burst = random.randint(30, 70)
    steps = []

    for i in range(burst):
        behavior = random.choice(behaviors)
        host = random.choice(hosts)
        fname, record = _event_for(behavior, scenario_id, run_id, host, t)
        _emit(EVIDENCE_DIR / fname, record)
        steps.append({
            "behavior": behavior,
            "step_id": f"{behavior}_step_{i+1}",
            "command": f"<synthetic command for {behavior}>",
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "elapsed_s": round(random.uniform(0.05, 0.6), 3),
            "timestamp": _ts(t),
            "status": "ok",
        })
        t += timedelta(seconds=random.uniform(0.3, 2.0))

    completed = t
    expected = spec.get("expected_telemetry") or {}
    coverage = {
        k: {"expected": bool(v), "produced_by": behaviors if v else []}
        for k, v in expected.items()
    }
    gaps = [k for k, v in expected.items() if v and not coverage[k]["produced_by"]]

    log = {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "scenario_name": name,
        "container": "clawdian_victim",
        "dry_run": False,
        "started_at": _ts(started),
        "completed_at": _ts(completed),
        "status": "completed",
        "behaviors_planned": behaviors,
        "steps": steps,
        "expected_telemetry": expected,
        "telemetry_coverage": coverage,
        "coverage_gaps": gaps,
        "step_failures": [],
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / f"{run_id}_exec_log.json").write_text(
        json.dumps(log, indent=2), encoding="utf-8"
    )
    return {"scenario_id": scenario_id, "run_id": run_id, "events": burst}


def main() -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    for p in EVIDENCE_DIR.glob("*.jsonl"):
        p.unlink()

    specs = []
    for f in sorted(SCENARIOS_DIR.glob("*.json")):
        try:
            spec = json.loads(f.read_text(encoding="utf-8"))
            spec.setdefault("scenario_id", f.stem)
            spec.setdefault("name", f.stem.replace("_", " ").title())
            specs.append(spec)
        except Exception as e:
            print(f"[warn] could not parse {f.name}: {e}")

    print(f"[seed] {len(specs)} scenarios discovered")
    summary = [seed_scenario(s) for s in specs]
    total = sum(s["events"] for s in summary)
    print(f"[seed] wrote {total} events across {len(summary)} scenarios")
    for s in summary:
        print(f"  - {s['scenario_id']:<32} run_id={s['run_id']}  events={s['events']}")

    print("[ship] forwarding evidence to Elasticsearch ...")
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "elastic_shipper",
        ROOT / "platform" / "telemetry" / "forwarders" / "elastic_shipper.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    result = mod.ship_evidence_to_elasticsearch(evidence_dir=EVIDENCE_DIR)
    print(f"[ship] sent={result.get('sent')} failed={result.get('failed')} errors={result.get('errors')}")


if __name__ == "__main__":
    main()
