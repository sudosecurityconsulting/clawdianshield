"""
tests/test_fim.py — Unit tests for FIM stat snapshot diffing.
"""
import pytest
from utils.jsonl import write, read
import tempfile, os, json


def test_write_and_read_jsonl():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        path = f.name
    try:
        write(path, {"event": "create", "path": "/tmp/test.txt"})
        write(path, {"event": "modify", "path": "/tmp/test.txt"})
        records = read(path)
        assert len(records) == 2
        assert records[0]["event"] == "create"
        assert records[1]["event"] == "modify"
    finally:
        os.unlink(path)


def test_stat_snapshot_diff():
    before = {"/etc/passwd": 1000, "/etc/hosts": 2000}
    after  = {"/etc/passwd": 1000, "/etc/hosts": 2001, "/etc/new": 3000}

    modified = [p for p in before if after.get(p) != before[p]]
    created  = [p for p in after if p not in before]

    assert modified == ["/etc/hosts"]
    assert created  == ["/etc/new"]
