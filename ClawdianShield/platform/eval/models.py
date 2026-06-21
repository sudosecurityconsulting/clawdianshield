"""
platform/eval/models.py

Schemas for the Agent-Under-Test (AUT) benchmarking plane.

An AgentAlert is what any SIEM/EDR writes to its detection output file.
The schema is intentionally minimal — the only required field for scoring
is technique_id. Everything else is surfaced in the dashboard as context.

A BenchmarkResult is the output of benchmark.py: per-step TP/FN/FP against
exec_log ground truth, plus aggregate detection rate and average latency.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from core.models.event_schema import _utc_now_iso


class AgentAlert(BaseModel):
    """
    One detection fired by the agent under test.

    Agents write these as JSONL to /var/log/agent_alerts.jsonl inside the
    victim container (bind-mounted to victim_logs/ on the host).

    Only technique_id is required for benchmark scoring. All other fields
    are optional context surfaced in the dashboard.
    """

    timestamp: str = Field(default_factory=_utc_now_iso)
    technique_id: str
    rule_name: str = ""
    severity: str = "medium"
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def try_parse(cls, line: str) -> "AgentAlert | None":
        """Parse one JSONL line. Returns None on any parse failure."""
        import json
        try:
            data = json.loads(line.strip())
            if not isinstance(data, dict) or "technique_id" not in data:
                return None
            return cls.model_validate(data)
        except Exception:
            return None


class StepVerdict(BaseModel):
    """Benchmark verdict for one execution step."""

    step_id: str
    behavior: str
    technique_id: str | None
    step_timestamp: str | None
    result: str  # "detected" | "missed" | "unscored" (technique_id is None)
    latency_s: float | None = None
    matched_alert: dict[str, Any] | None = None


class BenchmarkResult(BaseModel):
    """
    Full benchmark result for one scenario run against one agent.

    Written to reports/<run_id>_benchmark.json.
    """

    run_id: str
    scenario_id: str
    scenario_name: str = ""
    agent_name: str
    alerts_file: str
    scored_at: str = Field(default_factory=_utc_now_iso)
    window_s: float = 30.0

    # Scoreable steps = steps where technique_id is not None and status == "ok"
    technique_steps: int = 0
    true_positives: int = 0
    false_negatives: int = 0
    # Alerts that fired but didn't match any executed technique within the window
    false_positives: int = 0

    detection_rate_pct: float = 0.0
    avg_latency_s: float | None = None

    per_step: list[StepVerdict] = Field(default_factory=list)
    false_positive_alerts: list[dict[str, Any]] = Field(default_factory=list)
