"""
utils/jsonl.py — JSONL read/write helpers for evidence output.
"""
import json
from pathlib import Path


def write(path: str | Path, record: dict) -> None:
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def read(path: str | Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]
