#!/usr/bin/env python3
"""
fim.py - File Integrity Monitor (Passive)
ClawdianShield Phase 1: Real-time Telemetry

Polls os.stat() on a target honey-token file to detect access/modification.
Zero external dependencies. Local-only, no network calls.

Usage:
    python fim.py --target victim/developer-workstation/.env \
                  --output output/evidence/fim_alerts.log
"""

import argparse
import os
import sys
import time
import json
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Defaults (relative to ClawdianShield project root)
# ---------------------------------------------------------------------------
DEFAULT_TARGET = "victim/developer-workstation/.env"
DEFAULT_OUTPUT = "output/evidence/fim_alerts.log"
DEFAULT_POLL_INTERVAL = 1  # seconds


def get_file_state(filepath):
    """Snapshot stat metadata for comparison."""
    try:
        st = os.stat(filepath)
        return {
            "mtime": st.st_mtime,
            "atime": st.st_atime,
            "size": st.st_size,
            "inode": st.st_ino,
            "mode": oct(st.st_mode),
        }
    except FileNotFoundError:
        return None


def build_alert(event_type, target, prev_state, curr_state):
    """Structured alert dict for JSON-line logging."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "alert": "TAMPER_ALERT",
        "event": event_type,
        "target": target,
        "prev": prev_state,
        "curr": curr_state,
    }


def write_alert(alert, output_path):
    """Append a single JSON-line alert to the output log."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "a") as f:
        f.write(json.dumps(alert) + "\n")


def classify_changes(prev, curr):
    """Compare two stat snapshots, yield event type strings."""
    if prev is None and curr is not None:
        yield "FILE_CREATED"
        return
    if prev is not None and curr is None:
        yield "FILE_DELETED"
        return
    if prev["mtime"] != curr["mtime"]:
        yield "MODIFIED"
    if prev["atime"] != curr["atime"]:
        yield "ACCESSED"
    if prev["size"] != curr["size"]:
        yield "SIZE_CHANGED"
    if prev["mode"] != curr["mode"]:
        yield "PERMISSIONS_CHANGED"
    if prev["inode"] != curr["inode"]:
        yield "INODE_CHANGED"


def monitor(target, output, interval):
    """Main polling loop. Runs until SIGINT."""
    prev_state = get_file_state(target)
    status = "present" if prev_state else "absent"
    print(f"[FIM] Monitoring: {target}")
    print(f"[FIM] Output:     {output}")
    print(f"[FIM] Poll interval: {interval}s")
    print(f"[FIM] Initial state: {status}")
    print("[FIM] Press Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(interval)
            curr_state = get_file_state(target)

            events = list(classify_changes(prev_state, curr_state))
            if events:
                for event in events:
                    alert = build_alert(event, target, prev_state, curr_state)
                    write_alert(alert, output)
                    ts = alert["timestamp"]
                    print(f"[TAMPER ALERT] {ts} | {event} | {target}")

                prev_state = curr_state

    except KeyboardInterrupt:
        print("\n[FIM] Monitor stopped.")
        sys.exit(0)


def parse_args():
    parser = argparse.ArgumentParser(
        description="ClawdianShield FIM - Passive File Integrity Monitor"
    )
    parser.add_argument(
        "--target",
        default=DEFAULT_TARGET,
        help=f"File to monitor (default: {DEFAULT_TARGET})",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Alert log destination (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_POLL_INTERVAL,
        help=f"Poll interval in seconds (default: {DEFAULT_POLL_INTERVAL})",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if not os.path.exists(args.target):
        print(f"[FIM] WARNING: Target not found at startup: {args.target}")
        print("[FIM] Will alert on creation if the file appears.\n")

    monitor(args.target, args.output, args.interval)
