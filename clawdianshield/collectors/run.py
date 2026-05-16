"""
collectors/run.py

Convenience launcher: start the file observer and log observer concurrently
in a single process. Both write JSONL to evidence/ tagged with the same
run_id, scenario_id, and host, so the post-run scoring pass can correlate
them as one campaign.

Usage:
    python -m collectors.run \\
        --run-id exec-20260426-040000-abc123 \\
        --scenario-id fim_burst_001 \\
        --host workstation-1 \\
        --victim-state ./victim_state \\
        --victim-logs ./victim_logs \\
        --evidence ./evidence

Stop with Ctrl-C. Both observers shut down cleanly.
"""
from __future__ import annotations

import argparse
import signal
import threading
from pathlib import Path

from collectors import file_observer, log_observer


def main() -> None:
    p = argparse.ArgumentParser(
        description="ClawdianShield host-side observer launcher (file + log)",
    )
    p.add_argument("--run-id", required=True)
    p.add_argument("--scenario-id", required=True)
    p.add_argument("--host", default="workstation-1")
    p.add_argument(
        "--victim-state",
        default="./victim_state",
        help="Host dir bind-mounted to /tmp/clawdianshield in victim",
    )
    p.add_argument(
        "--victim-logs",
        default="./victim_logs",
        help="Host dir bind-mounted to /var/log in victim",
    )
    p.add_argument(
        "--evidence",
        default="./evidence",
        help="Output directory for JSONL evidence streams",
    )
    p.add_argument(
        "--auth-log-name",
        default="auth.log",
        help="Auth log filename inside --victim-logs (default: auth.log)",
    )
    args = p.parse_args()

    evidence = Path(args.evidence)
    evidence.mkdir(parents=True, exist_ok=True)

    # Single shared stop event drives coordinated shutdown of both observers.
    # Signal handlers must be installed from the main thread (Python rule),
    # so we own them here and pass the event into the worker threads.
    stop = threading.Event()

    file_thread = threading.Thread(
        target=file_observer.watch,
        kwargs={
            "watch_dir": Path(args.victim_state),
            "output": evidence / "file_events.jsonl",
            "run_id": args.run_id,
            "scenario_id": args.scenario_id,
            "host": args.host,
            "stop_event": stop,
        },
        daemon=True,
        name="file_observer",
    )
    log_thread = threading.Thread(
        target=log_observer.watch,
        kwargs={
            "watch_path": Path(args.victim_logs) / args.auth_log_name,
            "output": evidence / "auth_events.jsonl",
            "run_id": args.run_id,
            "scenario_id": args.scenario_id,
            "host": args.host,
            "stop_event": stop,
        },
        daemon=True,
        name="log_observer",
    )

    file_thread.start()
    log_thread.start()

    print(
        f"[run] observers running. evidence -> {evidence}/. "
        f"Press Ctrl-C to stop.",
        flush=True,
    )

    def _stop(_signum, _frame):
        print("[run] stop signal received", flush=True)
        stop.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    stop.wait()
    # Give threads a moment to flush before exit.
    file_thread.join(timeout=3.0)
    log_thread.join(timeout=3.0)
    print("[run] shutdown complete", flush=True)


if __name__ == "__main__":
    main()
