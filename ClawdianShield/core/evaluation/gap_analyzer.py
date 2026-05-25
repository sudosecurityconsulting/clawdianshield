"""
detection/coverage.py

Chain-coverage scoring — the actor -> observer -> detection validation loop.

Joins the actor's ATTiRe execution receipts (exec_log["steps"], each carrying a
timestamp, behavior, and optional ATT&CK technique_id) against the telemetry the
observers actually captured (NormalizedEvent JSONL in evidence/). For each
cleanly-executed step it asks: within a short window after the step ran, did the
sensors observe every class of event that step was expected to produce?

  - detected     : every expected (observable) telemetry class was seen
  - partial      : some but not all were seen
  - missed       : none were seen
  - unobservable : the step's only expected telemetry has no sensor (blind spot)

    chain_coverage_pct = (detected + 0.5 * partial) / scored_steps * 100

Additive and fails soft: with no evidence for the run it returns status
"no_evidence" rather than raising, so scorer.calculate_score() keeps working for
the 14 hand-authored scenarios that predate evidence correlation.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

try:
    # Built-in behavior -> telemetry-class contract lives with the actor plane.
    from core.runner.executor import BEHAVIOR_PRODUCES
except Exception:  # pragma: no cover - engine import optional at scoring time
    BEHAVIOR_PRODUCES: dict[str, set[str]] = {}

# Bridge: executor/scenario telemetry *classes* -> the concrete
# NormalizedEvent.event_type values the observers actually emit. A class mapped
# to an empty set is not observable by the current sensor suite (honest blind
# spot) and is excluded from the scored denominator.
TELEMETRY_CLASS_TO_EVENT_TYPES: dict[str, set[str]] = {
    "file_events": {"file_create", "file_modify", "file_delete", "file_rename"},
    "auth_events": {"auth_failure", "auth_success"},
    "process_events": {"process_start", "process_exit"},
    "persistence_path_changes": {"persistence_path_write", "file_create", "file_modify"},
    "hash_deltas": {"file_hash_delta", "file_create", "file_modify"},
    # No sensor reconstructs a timeline as a discrete event yet:
    "timeline_reconstruction": set(),
}

# hash_deltas is only truly satisfied by a file event that carries a digest.
_HASH_CLASS = "hash_deltas"


def _parse(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def behavior_expected_classes(behavior: str, exec_log: dict[str, Any]) -> set[str]:
    """Telemetry classes a behavior is expected to produce: built-in ∪ custom."""
    builtin = set(BEHAVIOR_PRODUCES.get(behavior, set()))
    custom = set((exec_log.get("custom_behavior_produces") or {}).get(behavior, []))
    return builtin | custom


def _event_matches_class(event: dict[str, Any], cls: str) -> bool:
    etype = event.get("event_type")
    if etype not in TELEMETRY_CLASS_TO_EVENT_TYPES.get(cls, set()):
        return False
    if cls == _HASH_CLASS:
        # Require an actual digest on the event to count as a hash delta.
        details = event.get("details") or {}
        return etype == "file_hash_delta" or bool(details.get("sha256"))
    return True


def _select_run_events(
    exec_log: dict[str, Any],
    events: list[dict[str, Any]],
    window_s: float,
) -> tuple[list[dict[str, Any]], str]:
    """Pick the evidence belonging to this run. Returns (events, join_mode)."""
    run_id = exec_log.get("run_id")
    run_events = [e for e in events if e.get("run_id") == run_id]
    if run_events:
        return run_events, "run_id"

    # Fallback: same scenario_id within the run's wall-clock window. Covers
    # evidence captured before run_id matching was wired end to end.
    sid = exec_log.get("scenario_id")
    start = _parse(exec_log.get("started_at", ""))
    end = _parse(exec_log.get("completed_at", ""))
    if sid and start and end:
        hi = end + timedelta(seconds=window_s)
        sel = [
            e
            for e in events
            if e.get("scenario_id") == sid
            and (ets := _parse(e.get("timestamp", ""))) is not None
            and start <= ets <= hi
        ]
        if sel:
            return sel, "scenario_window"
    return [], "none"


def _grade_step(
    step: dict[str, Any],
    run_events: list[dict[str, Any]],
    exec_log: dict[str, Any],
    window_s: float,
) -> dict[str, Any]:
    """Classify one receipt as detected / partial / missed / unobservable."""
    behavior = step.get("behavior", "unknown")
    step_ts = _parse(step.get("timestamp", ""))
    expected = behavior_expected_classes(behavior, exec_log)
    observable = {c for c in expected if TELEMETRY_CLASS_TO_EVENT_TYPES.get(c)}

    record: dict[str, Any] = {
        "step_id": step.get("step_id"),
        "behavior": behavior,
        "technique_id": step.get("technique_id"),
        "expected_classes": sorted(expected),
    }
    if not observable:
        record["result"] = "unobservable"
        return record

    hi = step_ts + timedelta(seconds=window_s) if step_ts else None
    matched: set[str] = set()
    first_hit: datetime | None = None
    for cls in observable:
        for e in run_events:
            if not _event_matches_class(e, cls):
                continue
            ets = _parse(e.get("timestamp", ""))
            if step_ts and hi and ets is not None and not (step_ts <= ets <= hi):
                continue
            matched.add(cls)
            if ets and (first_hit is None or ets < first_hit):
                first_hit = ets
            break

    if matched == observable:
        record["result"] = "detected"
    elif matched:
        record["result"] = "partial"
    else:
        record["result"] = "missed"

    record["matched_classes"] = sorted(matched)
    record["observable_classes"] = sorted(observable)
    if first_hit and step_ts:
        record["latency_s"] = round((first_hit - step_ts).total_seconds(), 3)
    return record


def chain_coverage(
    exec_log: dict[str, Any],
    events: list[dict[str, Any]],
    window_s: float = 5.0,
) -> dict[str, Any]:
    """
    Grade observed evidence against the actor's receipts. See module docstring.
    `events` is a list of NormalizedEvent dicts (e.g. from utils.jsonl.read).
    """
    steps = exec_log.get("steps", [])
    run_events, join_mode = _select_run_events(exec_log, events, window_s)

    base = {
        "join_mode": join_mode,
        "window_s": window_s,
        "run_id": exec_log.get("run_id"),
        "total_steps": len(steps),
    }
    if join_mode == "none":
        return {
            **base,
            "status": "no_evidence",
            "scored_steps": 0,
            "detected": 0,
            "partial": 0,
            "missed": 0,
            "chain_coverage_pct": 0.0,
            "per_step": [],
        }

    per_step: list[dict[str, Any]] = []
    counts = {"detected": 0, "partial": 0, "missed": 0}
    for step in steps:
        if step.get("status") != "ok":
            # Only grade detection on steps that actually executed cleanly;
            # dry-run / failed / timed-out steps aren't detection gaps.
            continue
        record = _grade_step(step, run_events, exec_log, window_s)
        if record["result"] in counts:
            counts[record["result"]] += 1
        per_step.append(record)

    scored = sum(counts.values())
    pct = (
        round((counts["detected"] + 0.5 * counts["partial"]) / scored * 100, 2)
        if scored
        else 0.0
    )
    return {
        **base,
        "status": "scored" if scored else "no_scorable_steps",
        "scored_steps": scored,
        **counts,
        "chain_coverage_pct": pct,
        "per_step": per_step,
    }
