#!/usr/bin/env python3
"""Tests for the ARC-D B2 adjudication charter."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "validate_arc_d_harvest_charter.py"


def _module():
    spec = importlib.util.spec_from_file_location("harvest_charter_validator", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_charter_validates_without_opening_response_carriers():
    module = _module()
    assert module.validate() == []
    source = SCRIPT.read_text(encoding="utf-8")
    assert "raw_response.utf8.b64" not in source
    assert "base64" not in source


def test_charter_authorizes_b2_but_never_harvest():
    module = _module()
    charter = module._json(module.CHARTER)
    assert charter["scope"]["rung"] == "B2_SOURCE_CASE_REVIEW"
    assert charter["rubric"]["no_harvest_at_b2"] is True
    assert (
        "treating a B2 disposition or charter adoption as HARVEST or TRANSFER_VALIDATED"
        in charter["scope"]["forbids"]
    )
    assert charter["rubric_author"]["response_text_seen_before_freeze"] is False
    assert charter["rubric_author"]["may_grade_under_this_charter"] is False


def test_prospective_b4_gate_is_adopted_but_unsatisfied():
    module = _module()
    gate = module._json(module.CHARTER)["prospective_harvest_gate"]
    assert gate["state_after_activation"] == "adopted_not_satisfied"
    assert gate["design"]["replicates_per_arm"] == 3
    assert (
        gate["decision_rule"]["arm_a_0_of_3_and_arm_b_3_of_3"]
        == "TRANSFER_VALIDATED_AND_ONE_HARVEST"
    )
    assert gate["decision_rule"]["any_other_window"] == "TRANSFER_AMBIGUOUS"


def test_two_blind_lineages_and_fail_closed_disagreement():
    module = _module()
    charter = module._json(module.CHARTER)
    assert {row["provider_lineage"] for row in charter["grading_instruments"]} == {
        "openai",
        "anthropic",
    }
    assert all(
        row["context"] == "fresh_projectless_packet_only"
        for row in charter["grading_instruments"]
    )
    assert charter["disagreement"]["automatic_averaging"] is False
    assert charter["disagreement"]["default"] == "B2_REFERENCE_AMBIGUOUS"


def test_grade_and_comparison_receipts_are_strictly_schematized():
    module = _module()
    charter = module._json(module.CHARTER)
    for path in charter["receipt_schemas"].values():
        schema = module._json(module.ROOT / path)
        assert schema["additionalProperties"] is False
        assert schema["required"]
    grade = module._json(module.ROOT / charter["receipt_schemas"]["grade"])
    assert grade["properties"]["exposure"]["properties"]["repository_context_seen"]["const"] is False
    assert len(grade["allOf"]) == 3
    comparison = module._json(module.ROOT / charter["receipt_schemas"]["comparison"])
    assert comparison["properties"]["binding_state"]["const"] == "PROPOSED_UNTIL_MERGED"
    assert comparison["allOf"]


def _run_standalone() -> int:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok  {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return int(failed > 0)


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
