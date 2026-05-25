#!/usr/bin/env python3
"""
engine/atomic_converter.py

Convert Red Canary Atomic Red Team test YAML into ClawdianShield scenario JSON.

The atomics corpus is an ATT&CK-labeled TTP library; this borrows the corpus and
schema, NOT the PowerShell runner. Each atomic test becomes a scenario whose
single custom behavior carries the test's shell command and — crucially — the
test's MITRE technique id as author-time ground truth, so detection/coverage.py
can grade the observer/scorer loop against it.

Scope (v1, deliberately bounded):
  - Only `sh` / `bash` executors are made executable. Everything else is still
    *surfaced* (Kevin's "whole corpus, gated" decision) but emitted with
    behavior_profile off + an `execution.gate_reason`, so it appears in the
    builder yet cannot run.
  - Gated: non-linux platforms, non-shell executors, elevation_required,
    or any `dependencies` block.
  - `#{arg}` input arguments are substituted with their declared `default`.

Usage:
    python -m engine.atomic_converter --file path/to/T1070.004.yaml --stdout
    python -m engine.atomic_converter --atomics-dir path/to/atomics --out engine/scenarios/atomic
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterator

import yaml

_SHELL_EXECUTORS = {"sh", "bash"}
_ARG_RE = re.compile(r"#\{([^}]+)\}")

# Lab-strict constraints so executable atomics pass executor._validate_safety.
# Gated atomics never run (behavior_profile off), so this is moot for them.
_LAB_SAFETY = {
    "lab_environment_only": True,
    "no_real_exploit_logic": True,
    "no_real_credential_attack_logic": True,
    "no_unapproved_network_spread": True,
}

# Heuristic: shell tokens that imply the command touches the filesystem.
_FILE_OP_TOKENS = (
    ">", ">>", "mkdir", "touch", "rm ", "mv ", "cp ", "tee", "ln ",
    "install ", "dd ", "truncate", "chmod", "chown", "sed -i",
)


def _slug(text: str) -> str:
    """Lowercase, alnum-only slug suitable for an id / filename."""
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return s or "test"


def _substitute_args(command: str, input_arguments: dict[str, Any]) -> str:
    """Replace #{name} with the argument's declared default; leave unknowns."""
    def repl(m: re.Match) -> str:
        name = m.group(1)
        spec = input_arguments.get(name) if input_arguments else None
        if isinstance(spec, dict) and "default" in spec:
            return str(spec["default"])
        return m.group(0)

    return _ARG_RE.sub(repl, command or "")


def _infer_produces(command: str) -> list[str]:
    """Telemetry classes the docker-exec'd command is expected to produce."""
    produces = ["process_events"]  # every step is a process execution
    if any(tok in command for tok in _FILE_OP_TOKENS):
        produces.append("file_events")
    return produces


def _gate(test: dict[str, Any]) -> tuple[bool, str | None]:
    """Return (executable, gate_reason). gate_reason is None when executable."""
    platforms = test.get("supported_platforms") or []
    executor = test.get("executor") or {}
    name = executor.get("name")
    if "linux" not in platforms:
        return False, f"platform: no linux support ({platforms or 'none'})"
    if name not in _SHELL_EXECUTORS:
        return False, f"executor: '{name}' is not a shell"
    if executor.get("elevation_required"):
        return False, "requires elevation"
    if test.get("dependencies"):
        return False, "has prerequisite dependencies"
    return True, None


def convert_test(technique_id: str, technique_name: str, test: dict[str, Any]) -> dict[str, Any]:
    """Convert one atomic_test into a ClawdianShield scenario dict."""
    executor = test.get("executor") or {}
    raw_command = executor.get("command", "")
    command = _substitute_args(raw_command, test.get("input_arguments") or {})
    executable, gate_reason = _gate(test)

    test_name = test.get("name", "atomic test")
    behavior = _slug(test_name)
    scenario_id = f"atomic_{_slug(technique_id)}_{behavior}"
    produces = _infer_produces(command)

    return {
        "scenario_id": scenario_id,
        "name": f"{technique_id} – {test_name}",
        "class_name": "atomic",
        "mode": "lab_only",
        "source": {
            "framework": "atomic-red-team",
            "attack_technique": technique_id,
            "technique_name": technique_name,
            "test_name": test_name,
            "auto_generated_guid": test.get("auto_generated_guid"),
            "executor": executor.get("name"),
            "supported_platforms": test.get("supported_platforms") or [],
        },
        # Gated atomics are surfaced but inert: behavior_profile off.
        "behavior_profile": {behavior: bool(executable)},
        "custom_behaviors": {
            behavior: [{"step_id": "atomic_command", "command": command}]
        },
        "custom_behavior_techniques": {behavior: technique_id},
        "custom_behavior_produces": {behavior: produces},
        "expected_telemetry": {t: True for t in produces},
        "execution": {"executable": executable, "gate_reason": gate_reason},
        "safety_constraints": dict(_LAB_SAFETY),
    }


def convert_technique(atomic: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a parsed atomic technique file into one scenario per test."""
    technique_id = atomic.get("attack_technique", "T0000")
    technique_name = atomic.get("display_name", "")
    return [
        convert_test(technique_id, technique_name, test)
        for test in atomic.get("atomic_tests", [])
    ]


def convert_atomic_file(path: str | Path) -> list[dict[str, Any]]:
    """Load an atomic YAML file and convert every test it defines."""
    atomic = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(atomic, dict):
        return []
    return convert_technique(atomic)


def _iter_atomic_files(atomics_dir: Path) -> Iterator[Path]:
    """Yield T*.yaml technique files under an atomics/ tree."""
    yield from sorted(atomics_dir.rglob("T*.yaml"))
    yield from sorted(atomics_dir.rglob("T*.yml"))


def _write_scenarios(scenarios: list[dict[str, Any]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for sc in scenarios:
        (out_dir / f"{sc['scenario_id']}.json").write_text(
            json.dumps(sc, indent=2), encoding="utf-8"
        )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="Single atomic technique YAML")
    src.add_argument("--atomics-dir", help="Root of a cloned atomic-red-team atomics/ tree")
    p.add_argument("--out", default="engine/scenarios/atomic", help="Output dir for scenario JSON")
    p.add_argument("--stdout", action="store_true", help="Print scenarios as JSON instead of writing")
    p.add_argument("--executable-only", action="store_true", help="Skip gated (non-runnable) atomics")
    args = p.parse_args()

    scenarios: list[dict[str, Any]] = []
    if args.file:
        scenarios = convert_atomic_file(args.file)
    else:
        for f in _iter_atomic_files(Path(args.atomics_dir)):
            try:
                scenarios.extend(convert_atomic_file(f))
            except (yaml.YAMLError, OSError) as exc:
                print(f"[WARN] skipped {f}: {exc}", file=sys.stderr)

    if args.executable_only:
        scenarios = [s for s in scenarios if s["execution"]["executable"]]

    executable = sum(1 for s in scenarios if s["execution"]["executable"])
    gated = len(scenarios) - executable

    if args.stdout:
        print(json.dumps(scenarios, indent=2))
    else:
        _write_scenarios(scenarios, Path(args.out))
        print(f"Wrote {len(scenarios)} scenarios to {args.out} ({executable} executable, {gated} gated)")


if __name__ == "__main__":
    main()
