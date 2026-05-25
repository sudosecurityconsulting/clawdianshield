"""
tests/test_atomic_converter.py — Atomic Red Team YAML -> scenario JSON.
"""
from pathlib import Path

from core.runner.atomic_converter import convert_atomic_file

FIXTURES = Path(__file__).parent / "fixtures"


def _by_behavior(scenario: dict) -> str:
    """Return the single behavior key of a converted scenario."""
    return next(iter(scenario["custom_behaviors"]))


# 1. A trivial linux sh atomic converts to one executable scenario, technique-labeled.
def test_trivial_sh_executable():
    scenarios = convert_atomic_file(FIXTURES / "atomic_sh_trivial.yaml")
    assert len(scenarios) == 1
    sc = scenarios[0]
    behavior = _by_behavior(sc)
    assert sc["execution"]["executable"] is True
    assert sc["execution"]["gate_reason"] is None
    assert sc["behavior_profile"][behavior] is True
    assert sc["custom_behavior_techniques"][behavior] == "T1059.004"
    # writes a file -> both classes inferred
    assert set(sc["custom_behavior_produces"][behavior]) == {"process_events", "file_events"}


# 2. Input-argument defaults are substituted; no #{...} placeholders remain.
def test_input_argument_substitution():
    scenarios = convert_atomic_file(FIXTURES / "atomic_with_args.yaml")
    sc = scenarios[0]
    behavior = _by_behavior(sc)
    command = sc["custom_behaviors"][behavior][0]["command"]
    assert "/tmp/ClawdianShield/victim.txt" in command
    assert "#{" not in command
    assert sc["execution"]["executable"] is True


# 3. Non-linux / elevation / dependency atomics are surfaced but gated + inert.
def test_gated_atomics_surfaced_but_inert():
    scenarios = convert_atomic_file(FIXTURES / "atomic_gated.yaml")
    assert len(scenarios) == 3
    reasons = []
    for sc in scenarios:
        behavior = _by_behavior(sc)
        assert sc["execution"]["executable"] is False
        assert sc["behavior_profile"][behavior] is False  # cannot run
        assert sc["execution"]["gate_reason"]
        reasons.append(sc["execution"]["gate_reason"])
    joined = " ".join(reasons)
    assert "no linux support" in joined
    assert "elevation" in joined
    assert "dependencies" in joined


# 4. scenario_id is deterministic and filesystem-safe.
def test_scenario_id_shape():
    sc = convert_atomic_file(FIXTURES / "atomic_sh_trivial.yaml")[0]
    assert sc["scenario_id"].startswith("atomic_t1059_004_")
    assert sc["class_name"] == "atomic"
    assert sc["source"]["framework"] == "atomic-red-team"
