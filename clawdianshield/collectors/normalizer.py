"""
collectors/normalizer.py

Boundary helper: convert a raw dict (from a syslog parser, watchdog event,
or replayed JSONL line) into a validated NormalizedEvent.

Defaults are conservative — missing fields don't raise, but downstream
consumers can still pydantic-validate the result.
"""
from __future__ import annotations

from datetime import datetime, timezone

from shared.models import NormalizedEvent


def normalize(raw: dict) -> NormalizedEvent:
    return NormalizedEvent(
        run_id=raw.get("run_id", "unknown"),
        scenario_id=raw.get("scenario_id", "unknown"),
        host=raw.get("host", "unknown"),
        event_type=raw.get("event_type", "unknown"),
        timestamp=raw.get("timestamp", datetime.now(timezone.utc).isoformat()),
        severity=raw.get("severity", "info"),
        details=raw.get("details", {}),
        collector=raw.get("collector", "unknown"),
    )
