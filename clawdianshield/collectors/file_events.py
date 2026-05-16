"""
collectors/file_events.py

Pure helpers for file integrity stat snapshots and hash-delta computation.
Used by file_observer.py to compute baseline -> current diffs and decide
whether a watchdog event represents a real content change.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict


def snapshot(paths: list[str]) -> Dict[str, str]:
    """Return {path: sha256_hex} for each path; 'missing' if unreadable."""
    result: Dict[str, str] = {}
    for p in paths:
        try:
            data = Path(p).read_bytes()
            result[p] = hashlib.sha256(data).hexdigest()
        except (FileNotFoundError, PermissionError, IsADirectoryError):
            result[p] = "missing"
    return result


def diff(before: Dict[str, str], after: Dict[str, str]) -> list[dict]:
    """Return list of change records {path, before, after} between snapshots."""
    changes = []
    all_keys = set(before) | set(after)
    for path in all_keys:
        b, a = before.get(path), after.get(path)
        if b != a:
            changes.append({"path": path, "before": b, "after": a})
    return changes
