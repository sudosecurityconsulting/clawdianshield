"""
collectors/log_observer.py

Host-side log tailer. Watches a file that is bind-mounted from inside
clawdian_victim (default mapping: ./victim_logs/auth.log -> /var/log/auth.log)
and emits NormalizedEvent JSONL whenever new lines are appended.

Pattern recognition is deliberately narrow: pam_unix authentication failures
and session-opened lines are classified into auth_failure / auth_success.
Anything else falls through as auth_unknown so it's still in the evidence
stream and visible to scoring.

Usage:
    python -m collectors.log_observer \\
        --watch ./victim_logs/auth.log \\
        --output evidence/auth_events.jsonl \\
        --run-id exec-20260426-040000-abc123 \\
        --scenario-id auth_abuse_001 \\
        --host workstation-1
"""
from __future__ import annotations

import argparse
import re
import signal
import threading
import time
from pathlib import Path
from typing import Optional

from shared.models import NormalizedEvent
from utils.jsonl import write as jsonl_write


_AUTH_FAILURE_RE = re.compile(r"pam_unix\([^)]+\):\s+authentication failure")
_AUTH_SUCCESS_RE = re.compile(r"session opened for user (?P<user>\S+)")


def _classify(line: str) -> tuple[str, str, dict]:
    """Return (event_type, severity, details) for a log line."""
    if _AUTH_FAILURE_RE.search(line):
        return "auth_failure", "high", {"raw": line.rstrip()}
    m = _AUTH_SUCCESS_RE.search(line)
    if m:
        return "auth_success", "medium", {"account": m.group("user"), "raw": line.rstrip()}
    return "auth_unknown", "info", {"raw": line.rstrip()}


def _install_signal_stop() -> threading.Event:
    """Install SIGINT/SIGTERM handlers backed by a fresh stop event."""
    stop = threading.Event()

    def _handler(_signum, _frame):
        print("[log_observer] stop signal received", flush=True)
        stop.set()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)
    return stop


def _emit_line(
    line: str,
    output: Path,
    run_id: str,
    scenario_id: str,
    host: str,
) -> int:
    """Classify and emit one log line. Returns its UTF-8 byte length."""
    event_type, severity, details = _classify(line)
    evt = NormalizedEvent(
        run_id=run_id,
        scenario_id=scenario_id,
        host=host,
        event_type=event_type,
        severity=severity,
        details=details,
        collector="log_observer",
    )
    jsonl_write(str(output), evt.model_dump())
    return len(line.encode("utf-8"))


def _drain_new_lines(
    watch_path: Path,
    last_size: int,
    output: Path,
    run_id: str,
    scenario_id: str,
    host: str,
) -> int:
    """Read complete new lines past last_size, emit each, return new last_size."""
    with open(watch_path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(last_size)
        for line in f:
            if not line.endswith("\n"):
                break  # partial trailing line — wait for more
            last_size += _emit_line(line, output, run_id, scenario_id, host)
    return last_size


def watch(
    watch_path: Path,
    output: Path,
    run_id: str,
    scenario_id: str,
    host: str,
    poll_interval: float = 0.25,
    from_start: bool = False,
    stop_event: Optional[threading.Event] = None,
) -> None:
    """
    Tail watch_path, classifying new lines and emitting NormalizedEvent JSONL.
    Runs until stop_event is set (orchestrated mode) or SIGINT/SIGTERM received
    (standalone CLI mode).
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    watch_path.parent.mkdir(parents=True, exist_ok=True)
    if not watch_path.exists():
        watch_path.touch()
    print(
        f"[log_observer] tailing {watch_path} -> {output} "
        f"(run_id={run_id}, scenario_id={scenario_id}, host={host})",
        flush=True,
    )

    if stop_event is None:
        stop_event = _install_signal_stop()

    last_size = 0 if from_start else watch_path.stat().st_size
    last_inode = watch_path.stat().st_ino

    while not stop_event.is_set():
        try:
            stat = watch_path.stat()
        except FileNotFoundError:
            time.sleep(poll_interval)
            continue

        # Rotation: inode changed or size shrank — restart from offset 0.
        if stat.st_ino != last_inode or stat.st_size < last_size:
            last_inode = stat.st_ino
            last_size = 0

        if stat.st_size > last_size:
            last_size = _drain_new_lines(
                watch_path, last_size, output, run_id, scenario_id, host,
            )
        time.sleep(poll_interval)

    print("[log_observer] stopped", flush=True)


def main() -> None:
    p = argparse.ArgumentParser(description="ClawdianShield host-side log observer")
    p.add_argument("--watch", required=True, help="Log file to tail")
    p.add_argument("--output", required=True, help="JSONL output path")
    p.add_argument("--run-id", required=True)
    p.add_argument("--scenario-id", required=True)
    p.add_argument("--host", default="workstation-1")
    p.add_argument("--poll-interval", type=float, default=0.25)
    p.add_argument(
        "--from-start",
        action="store_true",
        help="Read existing file contents instead of seeking to end",
    )
    args = p.parse_args()
    watch(
        Path(args.watch),
        Path(args.output),
        args.run_id,
        args.scenario_id,
        args.host,
        args.poll_interval,
        args.from_start,
    )


if __name__ == "__main__":
    main()
