"""
tests/test_coverage.py — chain-coverage scoring (actor receipts vs evidence).
"""
from core.evaluation.gap_analyzer import chain_coverage

_BASE = {
    "run_id": "run-1",
    "scenario_id": "sc-1",
    "started_at": "2026-04-27T10:00:00+00:00",
    "completed_at": "2026-04-27T10:00:10+00:00",
    "custom_behavior_produces": {
        "b_file": ["file_events"],
        "b_two": ["file_events", "auth_events"],
        "b_blind": ["timeline_reconstruction"],
    },
}


def _step(behavior, ts, status="ok", step_id="s1"):
    return {"behavior": behavior, "step_id": step_id, "status": status,
            "timestamp": ts, "technique_id": "T1", "command": "x"}


def _evt(event_type, ts, run_id="run-1", scenario_id="sc-1", details=None):
    return {"run_id": run_id, "scenario_id": scenario_id, "host": "h",
            "event_type": event_type, "timestamp": ts, "details": details or {}}


# 1. Expected event observed within the window -> detected, 100%.
def test_detected_within_window():
    log = {**_BASE, "steps": [_step("b_file", "2026-04-27T10:00:01+00:00")]}
    events = [_evt("file_create", "2026-04-27T10:00:02+00:00")]
    out = chain_coverage(log, events, window_s=5.0)
    assert out["join_mode"] == "run_id"
    assert out["detected"] == 1 and out["chain_coverage_pct"] == 100.0
    assert out["per_step"][0]["result"] == "detected"
    assert out["per_step"][0]["latency_s"] == 1.0


# 2. Expected event exists for the run but outside the window -> missed, 0%.
def test_missed_outside_window():
    log = {**_BASE, "steps": [_step("b_file", "2026-04-27T10:00:01+00:00")]}
    events = [_evt("file_create", "2026-04-27T10:00:30+00:00")]
    out = chain_coverage(log, events, window_s=5.0)
    assert out["missed"] == 1 and out["chain_coverage_pct"] == 0.0
    assert out["per_step"][0]["result"] == "missed"


# 3. Some-but-not-all expected classes seen -> partial, 50%.
def test_partial_coverage():
    log = {**_BASE, "steps": [_step("b_two", "2026-04-27T10:00:01+00:00")]}
    events = [_evt("file_create", "2026-04-27T10:00:02+00:00")]  # no auth event
    out = chain_coverage(log, events, window_s=5.0)
    assert out["partial"] == 1 and out["chain_coverage_pct"] == 50.0


# 4. No evidence at all -> fails soft with status no_evidence.
def test_no_evidence_fails_soft():
    log = {**_BASE, "steps": [_step("b_file", "2026-04-27T10:00:01+00:00")]}
    out = chain_coverage(log, [], window_s=5.0)
    assert out["status"] == "no_evidence" and out["join_mode"] == "none"
    assert out["scored_steps"] == 0


# 5. run_id miss but scenario_id within window -> scenario_window fallback.
def test_scenario_window_fallback():
    log = {**_BASE, "steps": [_step("b_file", "2026-04-27T10:00:01+00:00")]}
    events = [_evt("file_create", "2026-04-27T10:00:02+00:00", run_id="other")]
    out = chain_coverage(log, events, window_s=5.0)
    assert out["join_mode"] == "scenario_window"
    assert out["detected"] == 1


# 6. A behavior whose only expected telemetry has no sensor -> unobservable, unscored.
def test_unobservable_excluded():
    log = {**_BASE, "steps": [
        _step("b_blind", "2026-04-27T10:00:01+00:00", step_id="s1"),
        _step("b_file", "2026-04-27T10:00:02+00:00", step_id="s2"),
    ]}
    events = [_evt("file_create", "2026-04-27T10:00:03+00:00")]
    out = chain_coverage(log, events, window_s=5.0)
    results = {r["step_id"]: r["result"] for r in out["per_step"]}
    assert results["s1"] == "unobservable"
    assert results["s2"] == "detected"
    assert out["scored_steps"] == 1  # the unobservable step is not scored


# 7. dry-run / failed steps are not graded as detection gaps.
def test_nonok_steps_skipped():
    log = {**_BASE, "steps": [
        _step("b_file", "2026-04-27T10:00:01+00:00", status="failed", step_id="s1"),
        _step("b_file", "2026-04-27T10:00:02+00:00", status="dry_run", step_id="s2"),
        _step("b_file", "2026-04-27T10:00:03+00:00", status="ok", step_id="s3"),
    ]}
    events = [_evt("file_create", "2026-04-27T10:00:04+00:00")]
    out = chain_coverage(log, events, window_s=5.0)
    assert out["scored_steps"] == 1
    assert out["per_step"][0]["step_id"] == "s3"


# 8. hash_deltas requires a digest on the file event.
def test_hash_delta_requires_digest():
    log = {**_BASE,
           "custom_behavior_produces": {"b_hash": ["hash_deltas"]},
           "steps": [_step("b_hash", "2026-04-27T10:00:01+00:00")]}
    no_digest = [_evt("file_create", "2026-04-27T10:00:02+00:00")]
    with_digest = [_evt("file_create", "2026-04-27T10:00:02+00:00", details={"sha256": "abc"})]
    assert chain_coverage(log, no_digest)["missed"] == 1
    assert chain_coverage(log, with_digest)["detected"] == 1
