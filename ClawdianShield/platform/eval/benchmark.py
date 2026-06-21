"""
platform/eval/benchmark.py

Agent-Under-Test (AUT) detection benchmark.

Loads an exec_log.json (ground truth: which ATT&CK techniques ran and when)
and an agent alerts file (victim_logs/agent_alerts.jsonl) then computes:

  True Positive  — step has technique_id, agent fired a matching alert
                   within window_s seconds after the step timestamp
  False Negative — step has technique_id, no matching alert in window
  False Positive — alert fired for a technique not in the executed step set

Technique matching is prefix-tolerant: an agent alert for "T1070" counts as
a hit for "T1070.004" (parent-level detection). An alert for "T1070.004"
also matches a step labeled "T1070" for the same reason.

Steps where technique_id is None (pre-atomic hand-authored scenarios) are
marked "unscored" and excluded from the denominator — same policy as
gap_analyzer.chain_coverage() for non-ok steps.

Usage:
    python -m platform.eval.benchmark reports/<run_id>_exec_log.json \\
        [--alerts victim_logs/agent_alerts.jsonl] \\
        [--agent-name "my-agent"] \\
        [--window 30] \\
        [--reports reports/]

Output: reports/<run_id>_benchmark.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from platform.eval.adapters.file_drain import drain_since
from platform.eval.models import AgentAlert, BenchmarkResult, StepVerdict
from core.models.event_schema import _utc_now_iso

DEFAULT_WINDOW_S = 30.0
DEFAULT_ALERTS_PATH = "victim_logs/agent_alerts.jsonl"


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _techniques_match(step_tid: str, alert_tid: str) -> bool:
    """True when one is a prefix of the other (parent ↔ sub-technique)."""
    a, b = step_tid.upper(), alert_tid.upper()
    return a == b or a.startswith(b) or b.startswith(a)


def _find_matching_alert(
    step_tid: str,
    step_ts: datetime | None,
    alerts: list[AgentAlert],
    window_s: float,
) -> tuple[AgentAlert | None, float | None]:
    """
    Return the first alert that matches step_tid within window_s.
    Also returns the latency in seconds (alert.timestamp - step_ts).
    If step_ts is None, window is unconstrained (match any time).
    """
    best: AgentAlert | None = None
    best_latency: float | None = None

    for alert in alerts:
        if not _techniques_match(step_tid, alert.technique_id):
            continue
        if step_ts is None:
            return alert, None
        alert_ts = _parse_ts(alert.timestamp)
        if alert_ts is None:
            continue
        delta = (alert_ts - step_ts).total_seconds()
        # Accept alerts that arrived within the window (allow slight negative
        # offset in case of clock skew, bounded to -2s)
        if -2.0 <= delta <= window_s:
            if best is None or delta < best_latency:  # type: ignore[operator]
                best = alert
                best_latency = max(delta, 0.0)

    return best, best_latency


def run_benchmark(
    exec_log: dict[str, Any],
    alerts: list[AgentAlert],
    agent_name: str,
    alerts_file: str,
    window_s: float = DEFAULT_WINDOW_S,
) -> BenchmarkResult:
    run_id = exec_log.get("run_id", "unknown")
    scenario_id = exec_log.get("scenario_id", "unknown")
    scenario_name = exec_log.get("scenario_name", "")
    started_at = exec_log.get("started_at")

    result = BenchmarkResult(
        run_id=run_id,
        scenario_id=scenario_id,
        scenario_name=scenario_name,
        agent_name=agent_name,
        alerts_file=alerts_file,
        window_s=window_s,
    )

    # Only score alerts that arrived after the run started (ignore stale alerts
    # from previous runs that happen to still be in the file).
    scoped_alerts = [
        a for a in alerts
        if started_at is None or a.timestamp >= started_at
    ]

    matched_alert_indices: set[int] = set()
    latencies: list[float] = []
    per_step: list[StepVerdict] = []

    for step in exec_log.get("steps", []):
        if step.get("status") != "ok":
            continue

        technique_id: str | None = step.get("technique_id")
        step_ts = _parse_ts(step.get("timestamp"))

        verdict = StepVerdict(
            step_id=step.get("step_id", "unknown"),
            behavior=step.get("behavior", "unknown"),
            technique_id=technique_id,
            step_timestamp=step.get("timestamp"),
        )

        if technique_id is None:
            verdict.result = "unscored"
            per_step.append(verdict)
            continue

        result.technique_steps += 1
        match, latency = _find_matching_alert(technique_id, step_ts, scoped_alerts, window_s)

        if match is not None:
            idx = scoped_alerts.index(match)
            matched_alert_indices.add(idx)
            verdict.result = "detected"
            verdict.latency_s = latency
            verdict.matched_alert = match.model_dump()
            result.true_positives += 1
            if latency is not None:
                latencies.append(latency)
        else:
            verdict.result = "missed"
            result.false_negatives += 1

        per_step.append(verdict)

    # False positives: alerts that didn't match any executed step
    fp_alerts = [
        scoped_alerts[i].model_dump()
        for i in range(len(scoped_alerts))
        if i not in matched_alert_indices
    ]
    result.false_positives = len(fp_alerts)
    result.false_positive_alerts = fp_alerts
    result.per_step = per_step

    if result.technique_steps > 0:
        result.detection_rate_pct = round(
            result.true_positives / result.technique_steps * 100, 2
        )
    result.avg_latency_s = round(sum(latencies) / len(latencies), 3) if latencies else None

    return result


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("exec_log", help="Path to reports/<run_id>_exec_log.json")
    p.add_argument(
        "--alerts",
        default=DEFAULT_ALERTS_PATH,
        help=f"Agent alerts JSONL file (default: {DEFAULT_ALERTS_PATH})",
    )
    p.add_argument("--agent-name", default="agent-under-test")
    p.add_argument(
        "--window",
        type=float,
        default=DEFAULT_WINDOW_S,
        help=f"Detection window in seconds after each step (default: {DEFAULT_WINDOW_S})",
    )
    p.add_argument("--reports", default="reports", help="Output directory for benchmark JSON")
    args = p.parse_args()

    exec_log_path = Path(args.exec_log)
    if not exec_log_path.exists():
        print(f"ERROR: exec_log not found: {exec_log_path}", file=sys.stderr)
        sys.exit(1)

    exec_log = json.loads(exec_log_path.read_text(encoding="utf-8"))
    started_at = exec_log.get("started_at")

    alerts_path = Path(args.alerts)
    alerts = drain_since(alerts_path, started_at) if started_at else []

    if not alerts:
        print(
            f"[benchmark] WARNING: no alerts found in {alerts_path} "
            f"(started_at={started_at}). Is the agent running?",
            file=sys.stderr,
        )

    result = run_benchmark(
        exec_log=exec_log,
        alerts=alerts,
        agent_name=args.agent_name,
        alerts_file=str(alerts_path),
        window_s=args.window,
    )

    out_dir = Path(args.reports)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{result.run_id}_benchmark.json"
    out_path.write_text(
        json.dumps(result.model_dump(), indent=2), encoding="utf-8"
    )

    print(f"[{result.run_id}] Agent       : {result.agent_name}")
    print(f"[{result.run_id}] Steps scored: {result.technique_steps}")
    print(f"[{result.run_id}] Detected    : {result.true_positives} (TP)")
    print(f"[{result.run_id}] Missed      : {result.false_negatives} (FN)")
    print(f"[{result.run_id}] False alarms: {result.false_positives} (FP)")
    print(f"[{result.run_id}] Detection   : {result.detection_rate_pct}%")
    if result.avg_latency_s is not None:
        print(f"[{result.run_id}] Avg latency : {result.avg_latency_s}s")
    print(f"[{result.run_id}] Report      : {out_path}")


if __name__ == "__main__":
    main()
