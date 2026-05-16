"""
tests/test_correlation.py — Unit tests for correlate_auth_and_file.
"""
import pytest
from collectors.correlation import correlate_auth_and_file
from shared.models import NormalizedEvent


def _evt(event_type: str, host: str, timestamp: str) -> NormalizedEvent:
    return NormalizedEvent(
        run_id="run-test",
        scenario_id="test",
        host=host,
        event_type=event_type,
        timestamp=timestamp,
    )


# 1. Empty event list returns []
def test_empty_returns_empty():
    assert correlate_auth_and_file([]) == []


# 2. Auth + file on the same host within window returns one pair
def test_same_host_within_window():
    auth = _evt("auth_failure", "host-a", "2026-04-27T10:00:00+00:00")
    fev = _evt("file_create", "host-a", "2026-04-27T10:00:03+00:00")
    result = correlate_auth_and_file([auth, fev], window_seconds=5.0)
    assert len(result) == 1
    assert result[0] == (auth, fev)


# 3. Auth + file on different hosts returns []
def test_different_hosts_returns_empty():
    auth = _evt("auth_failure", "host-a", "2026-04-27T10:00:00+00:00")
    fev = _evt("file_create", "host-b", "2026-04-27T10:00:02+00:00")
    assert correlate_auth_and_file([auth, fev]) == []


# 4. Auth + file separated by more than window_seconds returns []
def test_outside_window_returns_empty():
    auth = _evt("auth_success", "host-a", "2026-04-27T10:00:00+00:00")
    fev = _evt("file_modify", "host-a", "2026-04-27T10:00:10+00:00")
    assert correlate_auth_and_file([auth, fev], window_seconds=5.0) == []


# 5. One auth event followed by multiple file events within window returns
#    multiple pairs, all keyed to that auth event
def test_one_auth_multiple_file_events():
    auth = _evt("auth_failure", "host-a", "2026-04-27T10:00:00+00:00")
    f1 = _evt("file_create", "host-a", "2026-04-27T10:00:01+00:00")
    f2 = _evt("file_delete", "host-a", "2026-04-27T10:00:03+00:00")
    f3 = _evt("file_rename", "host-a", "2026-04-27T10:00:04+00:00")
    result = correlate_auth_and_file([auth, f1, f2, f3], window_seconds=5.0)
    assert len(result) == 3
    assert all(pair[0] == auth for pair in result)
    # sorted by file_event.timestamp ascending
    assert [p[1] for p in result] == [f1, f2, f3]


# 6. File event that precedes the auth event is not paired
def test_file_before_auth_not_paired():
    fev = _evt("file_create", "host-a", "2026-04-27T10:00:00+00:00")
    auth = _evt("auth_failure", "host-a", "2026-04-27T10:00:03+00:00")
    assert correlate_auth_and_file([fev, auth]) == []
