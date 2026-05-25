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


class ExecutionReceipt(BaseModel):
    """
    Ground-truth record of one executed step — the actor's "flight recorder."

    ATTiRe-shaped (Red Canary's Attack Technique Intelligence Reporting Engine):
    a chronological, technique-labeled receipt of what the actor actually ran,
    independent of what the observers saw. The detection plane grades observed
    evidence against these receipts (see detection/coverage.py).

    Mirrors the dict shape the executor writes into exec_log["steps"], plus the
    ATT&CK technique_id label. technique_id is None for the 14 hand-authored
    scenarios that predate atomic-derived labeling — coverage scoring tolerates
    that and falls back to the behavior's expected telemetry classes.
    """

    behavior: str
    step_id: str
    command: str
    technique_id: str | None = None
    returncode: int | None = None
    status: str = "unknown"  # ok | failed | timeout | dry_run | unknown
    timestamp: str = Field(default_factory=_utc_now_iso)
    elapsed_s: float = 0.0

    @classmethod
    def from_step(cls, step: dict[str, Any]) -> "ExecutionReceipt":
        """Build a receipt from an executor exec_log step dict, ignoring extras."""
        return cls(
            behavior=step.get("behavior", "unknown"),
            step_id=step.get("step_id", "unknown"),
            command=step.get("command", ""),
            technique_id=step.get("technique_id"),
            returncode=step.get("returncode"),
            status=step.get("status", "unknown"),
            timestamp=step.get("timestamp", _utc_now_iso()),
            elapsed_s=step.get("elapsed_s", 0.0),
        )


class RunContext(BaseModel):
    """
    Per-run context passed between observers when they run in-process.
    Standalone observer processes write JSONL keyed by run_id and read this
    context from the executor's report when stitching events post-run.

    receipts holds the actor's ATTiRe execution receipts (ground truth) for the
    run; events holds the observed telemetry. Coverage scoring joins the two.
    """

    run_id: str
    scenario_id: str
    host: str
    started_at: str = Field(default_factory=_utc_now_iso)
    events: list[NormalizedEvent] = Field(default_factory=list)
    receipts: list[ExecutionReceipt] = Field(default_factory=list)
