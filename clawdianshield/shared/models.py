"""
shared/models.py

Schema of record for ClawdianShield telemetry. Every event emitted by the
host-side observers (file_observer, log_observer, process_events emitter)
and every record consumed by correlation/scoring conforms to NormalizedEvent.

Pydantic v2 is used for validation at the observer boundary so malformed
events fail fast rather than poisoning the evidence stream.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class NormalizedEvent(BaseModel):
    """
    Canonical telemetry event. Observers produce these; correlation reads them.

    Fields:
      run_id        — execution batch identifier (e.g. exec-20260426-040000-abc123)
      scenario_id   — scenario JSON's scenario_id, or "ambient" for collector-only runs
      host          — logical host name (e.g. "workstation-1"), not container id
      event_type    — taxonomy: file_create | file_modify | file_delete | file_rename
                       | file_hash_delta | auth_failure | auth_success
                       | process_start | process_exit | capability_audit
                       | http_metadata_fetch | persistence_path_write
      timestamp     — ISO 8601 UTC, observer's wall-clock at observation
      severity      — info | low | medium | high | critical
      details       — event-type-specific payload (path, hashes, command, account, etc.)
      collector     — emitter name (file_observer | log_observer | executor) for provenance
    """

    run_id: str
    scenario_id: str
    host: str
    event_type: str
    timestamp: str = Field(default_factory=_utc_now_iso)
    severity: str = "info"
    details: dict[str, Any] = Field(default_factory=dict)
    collector: str = "unknown"

    def to_jsonl(self) -> str:
        return self.model_dump_json()


class RunContext(BaseModel):
    """
    Per-run context passed between observers when they run in-process.
    Standalone observer processes write JSONL keyed by run_id and read this
    context from the executor's report when stitching events post-run.
    """

    run_id: str
    scenario_id: str
    host: str
    started_at: str = Field(default_factory=_utc_now_iso)
    events: list[NormalizedEvent] = Field(default_factory=list)
