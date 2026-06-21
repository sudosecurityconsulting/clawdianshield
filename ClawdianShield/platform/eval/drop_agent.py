"""
platform/eval/drop_agent.py

Tier-2 agent deployment: copy a binary into a running victim container and
start it without rebuilding the image or modifying docker-compose.yml.

Tier constraints (inherent from the victim container setup):
  - network_mode: none  → agents that phone home to a manager won't work
  - cap_drop: ALL       → agents needing raw sockets / kernel capabilities won't work
  - Suitable for: self-contained, file-writing EDR/SIEM stubs and custom agents

The agent is expected to:
  1. Run as a foreground or background process inside the container
  2. Write detections as JSONL to /var/log/agent_alerts.jsonl
     (bind-mounted to victim_logs/agent_alerts.jsonl on the host)

Usage:
    python -m platform.eval.drop_agent \\
        --binary ./my_agent \\
        --start-cmd "/opt/agent/my_agent --out /var/log/agent_alerts.jsonl" \\
        --container clawdian_victim

    python -m platform.eval.drop_agent --stop --container clawdian_victim
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

AGENT_DEST_DIR = "/opt/clawdian_agent"
ALERT_OUTPUT_PATH = "/var/log/agent_alerts.jsonl"


def _docker(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        check=check,
    )


def drop(
    binary_path: str | Path,
    start_cmd: str,
    container: str = "clawdian_victim",
) -> None:
    """
    Copy binary into the container and start it in the background.

    The binary lands at AGENT_DEST_DIR inside the container. The caller
    supplies the full start_cmd (can reference AGENT_DEST_DIR).
    """
    binary_path = Path(binary_path)
    if not binary_path.exists():
        print(f"[drop_agent] ERROR: binary not found: {binary_path}", file=sys.stderr)
        sys.exit(1)

    # Ensure destination directory exists
    _docker(["exec", container, "mkdir", "-p", AGENT_DEST_DIR])
    print(f"[drop_agent] Copying {binary_path.name} → {container}:{AGENT_DEST_DIR}/")

    _docker(["cp", str(binary_path), f"{container}:{AGENT_DEST_DIR}/{binary_path.name}"])
    _docker(["exec", container, "chmod", "+x", f"{AGENT_DEST_DIR}/{binary_path.name}"])

    # Start in background with docker exec -d so the deploy call returns
    print(f"[drop_agent] Starting agent: {start_cmd}")
    _docker(["exec", "-d", container, "sh", "-c", start_cmd])
    print(f"[drop_agent] Agent running. Detections → {container}:{ALERT_OUTPUT_PATH}")
    print(f"[drop_agent] Host path: victim_logs/agent_alerts.jsonl")


def stop(container: str = "clawdian_victim") -> None:
    """Kill any process writing to the agent alerts file."""
    print(f"[drop_agent] Stopping agent processes in {container}")
    result = _docker(
        ["exec", container, "sh", "-c",
         f"pkill -f agent_alerts.jsonl 2>/dev/null || true"],
        check=False,
    )
    if result.returncode == 0:
        print("[drop_agent] Agent stopped.")
    else:
        print("[drop_agent] No agent process found (may have already exited).")


def clear_alerts(container: str = "clawdian_victim") -> None:
    """Truncate the alert output file so a fresh benchmark run starts clean."""
    _docker(["exec", container, "sh", "-c",
             f"truncate -s 0 {ALERT_OUTPUT_PATH} 2>/dev/null || true"],
            check=False)
    print(f"[drop_agent] Cleared {ALERT_OUTPUT_PATH}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--container", default="clawdian_victim")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--binary", help="Path to agent binary on the host")
    mode.add_argument("--stop", action="store_true", help="Stop the running agent")
    mode.add_argument("--clear", action="store_true", help="Truncate the alert output file")
    p.add_argument(
        "--start-cmd",
        default=None,
        help=(
            "Command to start the agent inside the container. "
            f"Default: {{AGENT_DEST_DIR}}/{{binary}} --out {ALERT_OUTPUT_PATH}"
        ),
    )
    args = p.parse_args()

    if args.stop:
        stop(args.container)
    elif args.clear:
        clear_alerts(args.container)
    else:
        binary = Path(args.binary)
        cmd = args.start_cmd or (
            f"{AGENT_DEST_DIR}/{binary.name} --out {ALERT_OUTPUT_PATH}"
        )
        drop(binary, cmd, args.container)


if __name__ == "__main__":
    main()
