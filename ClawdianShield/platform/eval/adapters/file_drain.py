"""
platform/eval/adapters/file_drain.py

File-based alert ingest for the AUT benchmark.

Reads a JSONL file written by the agent under test and returns all
AgentAlert records present at call time. The file is the bind-mounted
/var/log/agent_alerts.jsonl path from inside the victim container, which
appears on the host at victim_logs/agent_alerts.jsonl.

This is the zero-infrastructure adapter: no webhooks, no API keys, no
network config. The agent writes a file; we read it. Works for any agent
that can be told where to log detections.
"""
from __future__ import annotations

from pathlib import Path

from platform.eval.models import AgentAlert


def drain(alerts_path: str | Path) -> list[AgentAlert]:
    """
    Read all AgentAlert records from a JSONL file.

    Malformed lines are silently skipped — the benchmark logs the count so
    the analyst knows if the agent is writing garbage.
    """
    path = Path(alerts_path)
    if not path.exists():
        return []

    alerts: list[AgentAlert] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        alert = AgentAlert.try_parse(line)
        if alert is not None:
            alerts.append(alert)
    return alerts


def drain_since(alerts_path: str | Path, since_iso: str) -> list[AgentAlert]:
    """Return only alerts with timestamp >= since_iso (ISO 8601 strings, lexsort-safe)."""
    return [a for a in drain(alerts_path) if a.timestamp >= since_iso]
