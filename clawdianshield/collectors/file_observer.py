"""
collectors/file_observer.py

Host-side file integrity observer. Watches a host directory that is bind-mounted
into clawdian_victim (default mapping: ./victim_state -> /tmp/clawdianshield)
and emits NormalizedEvent JSONL whenever files inside it are created, modified,
moved, or deleted.

Uses watchdog's PollingObserver. Inotify pass-through from the WSL2 VM to a
Windows-host bind mount is unreliable, and polling works uniformly across
Linux, macOS, and Windows host filesystems.

Usage:
    python -m collectors.file_observer \\
        --watch ./victim_state \\
        --output evidence/file_events.jsonl \\
        --run-id exec-20260426-040000-abc123 \\
        --scenario-id fim_burst_001 \\
        --host workstation-1
"""
from __future__ import annotations

import argparse
import hashlib
import signal
import threading
from pathlib import Path
from typing import Optional

from watchdog.events import (
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers.polling import PollingObserver

from shared.models import NormalizedEvent
from utils.jsonl import write as jsonl_write

# ---------------------------------------------------------------------------
# Severity mapping per filesystem event kind.
# ---------------------------------------------------------------------------
_SEVERITY: dict[str, str] = {
    "created": "medium",
    "modified": "high",
    "moved": "high",
    "deleted": "high",
}

# Map watchdog event kinds to canonical NormalizedEvent.event_type values.
_EVENT_TYPE: dict[str, str] = {
    "created": "file_create",
    "modified": "file_modify",
    "moved": "file_rename",
    "deleted": "file_delete",
}


def _hash_file(path: str) -> Optional[str]:
    """Compute sha256 of a file. Returns None if unreadable (race with delete)."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except (FileNotFoundError, PermissionError, IsADirectoryError):
        return None


class _FimHandler(FileSystemEventHandler):
    def __init__(
        self,
        run_id: str,
        scenario_id: str,
        host: str,
        output: Path,
    ) -> None:
        self.run_id = run_id
        self.scenario_id = scenario_id
        self.host = host
        self.output = output

    def _emit(
        self,
        event_type: str,
        details: dict,
        severity: str,
    ) -> None:
        evt = NormalizedEvent(
            run_id=self.run_id,
            scenario_id=self.scenario_id,
            host=self.host,
            event_type=event_type,
            severity=severity,
            details=details,
            collector="file_observer",
        )
        jsonl_write(str(self.output), evt.model_dump())

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        kind = event.event_type
        canonical = _EVENT_TYPE.get(kind)
        if canonical is None:
            return
        details: dict = {"path": event.src_path}
        if kind == "moved":
            details["dest_path"] = event.dest_path
        if kind in ("created", "modified"):
            digest = _hash_file(event.src_path)
            if digest is not None:
                details["sha256"] = digest
        self._emit(canonical, details, _SEVERITY[kind])


def watch(
    watch_dir: Path,
    output: Path,
    run_id: str,
    scenario_id: str,
    host: str,
    poll_interval: float = 0.5,
    stop_event: Optional[threading.Event] = None,
) -> None:
    """
    Run the file observer until stop_event is set (orchestrated mode) or
    until SIGINT/SIGTERM is received (standalone CLI mode).
    """
    watch_dir.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    handler = _FimHandler(run_id, scenario_id, host, output)
    observer = PollingObserver(timeout=poll_interval)
    observer.schedule(handler, str(watch_dir), recursive=True)
    observer.start()
    print(
        f"[file_observer] watching {watch_dir} -> {output} "
        f"(run_id={run_id}, scenario_id={scenario_id}, host={host})",
        flush=True,
    )

    standalone = stop_event is None
    if standalone:
        stop_event = threading.Event()

        def _signal_stop(_signum, _frame):
            print("[file_observer] stop signal received", flush=True)
            stop_event.set()

        signal.signal(signal.SIGINT, _signal_stop)
        signal.signal(signal.SIGTERM, _signal_stop)

    try:
        stop_event.wait()
    finally:
        observer.stop()
        observer.join(timeout=2.0)
        print("[file_observer] stopped", flush=True)


def main() -> None:
    p = argparse.ArgumentParser(description="ClawdianShield host-side file observer")
    p.add_argument("--watch", required=True, help="Host directory to observe")
    p.add_argument("--output", required=True, help="JSONL output path")
    p.add_argument("--run-id", required=True)
    p.add_argument("--scenario-id", required=True)
    p.add_argument("--host", default="workstation-1")
    p.add_argument("--poll-interval", type=float, default=0.5)
    args = p.parse_args()
    watch(
        Path(args.watch),
        Path(args.output),
        args.run_id,
        args.scenario_id,
        args.host,
        args.poll_interval,
    )


if __name__ == "__main__":
    main()
