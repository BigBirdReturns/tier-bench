#!/usr/bin/env python3
"""Zero-model-call tests for MENACE donor piles, seams, and witness cover."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tier_runner.menace_edge_common import EdgeError  # noqa: E402
from tier_runner.menace_seam_plan import (  # noqa: E402
    compile_plan,
    compile_report,
    render_markdown,
    validate_bundle,
    verify_plan,
    verify_report,
)

DONORS = ROOT / "experiments" / "menace_edge" / "donor_piles.json"
SEAMS = ROOT / "experiments" / "menace_edge" / "seam_catalog.json"
COVERAGE = ROOT / "experiments" / "menace_edge" / "coverage_matrix.json"


def inputs() -> tuple[dict, dict, dict]:
    return (
        json.loads(DONORS.read_text(encoding="utf-8")),
        json.loads(SEAMS.read_text(encoding="utf-8")),
        json.loads(COVERAGE.read_text(encoding="utf-8")),
    )


def selected_ids(plan: dict) -> list[str]:
    return [item["id"] for item in plan["selected_witnesses"]]


def test_bundle_and_public_boundary() -> None:
    donors, seams, coverage = validate_bundle(*inputs())
    assert donors["campaign_id"] == "menace-edge-01"
    assert len(donors["piles"]) == 6
    assert sum(len(item["donors"]) for item in donors["piles"]) == 18
    assert len(seams["seams"]) == 18
    assert len(seams["negative_witnesses"]) == 18
    assert len(coverage["witnesses"]) == 8
    assert donors["public_boundary"]["private_source_bytes_allowed"] is False
    for pile in donors["piles"]:
        for donor in pile["donors"]:
            assert donor["contains_private_source_bytes"] is False
            if donor["source_visibility"] in {"private", "mixed"}:
                assert donor["allowed_public_use"] != "exact"


def test_exact_minimal_witness_set() -> None:
    plan = compile_plan(*inputs())
    assert plan["objective"]["total_cost_units"] == 31
    assert plan["objective"]["witness_count"] == 5
    assert selected_ids(plan) == [
        "witness.cooperative-handoff",
        "witness.multi-role-handoff",
        "witness.partitioned-controller",
        "witness.physical-availability",
        "witness.stack-recovery",
    ]
    assert plan["alternative_optima"] == []
    assert plan["coverage"]["uncovered_seams"] == []
    assert plan["coverage"]["uncovered_negative_witnesses"] == []
    assert all(item["support_satisfied"] for item in plan["coverage"]["seam_support"])
    assert plan["production_claim"] is False
    assert plan["promotion_authorized"] is False


def test_all_three_evidence_classes_are_required() -> None:
    donors, seams, coverage = inputs()
    coverage["witnesses"] = [
        item for item in coverage["witnesses"] if item["id"] != "witness.cooperative-handoff"
    ]
    try:
        compile_plan(donors, seams, coverage)
    except EdgeError as exc:
        assert "required evidence classes" in str(exc) or "no admissible witness set" in str(exc)
    else:
        raise AssertionError("removing the synthetic-control witness must fail")


def test_track_handoff_is_not_replaceable_by_generic_sync() -> None:
    donors, seams, coverage = inputs()
    witness = next(
        item for item in coverage["witnesses"] if item["id"] == "witness.cooperative-handoff"
    )
    witness["covers_seams"].remove("seam.track-handoff")
    witness["covers_negative_witnesses"].remove("neg.track-discontinuity")
    try:
        compile_plan(donors, seams, coverage)
    except EdgeError as exc:
        assert "no admissible witness set" in str(exc)
    else:
        raise AssertionError("track handoff requires a dedicated witness")


def test_shift_handoff_is_not_replaceable_by_a_log() -> None:
    donors, seams, coverage = inputs()
    witness = next(
        item for item in coverage["witnesses"] if item["id"] == "witness.multi-role-handoff"
    )
    witness["covers_seams"].remove("seam.shift-handoff")
    witness["covers_negative_witnesses"].remove("neg.decision-context-loss")
    try:
        compile_plan(donors, seams, coverage)
    except EdgeError as exc:
        assert "no admissible witness set" in str(exc)
    else:
        raise AssertionError("shift handoff requires a dedicated decision-context witness")


def test_unknown_pile_fails_closed() -> None:
    donors, seams, coverage = inputs()
    coverage["witnesses"][0]["donor_piles"].append("pile.fabricated")
    try:
        validate_bundle(donors, seams, coverage)
    except EdgeError as exc:
        assert "unknown piles" in str(exc)
    else:
        raise AssertionError("unknown donor pile must fail")


def test_private_donor_cannot_be_exact_public_source() -> None:
    donors, seams, coverage = inputs()
    private_donor = next(
        donor
        for pile in donors["piles"]
        for donor in pile["donors"]
        if donor["source_visibility"] == "private"
    )
    private_donor["allowed_public_use"] = "exact"
    try:
        validate_bundle(donors, seams, coverage)
    except EdgeError as exc:
        assert "sanitized shape" in str(exc)
    else:
        raise AssertionError("private donor source cannot be exposed exactly")


def test_proposed_witness_cannot_enter_admitted_cover() -> None:
    donors, seams, coverage = inputs()
    witness = next(
        item for item in coverage["witnesses"] if item["id"] == "witness.partitioned-controller"
    )
    witness["state"] = "proposed"
    try:
        compile_plan(donors, seams, coverage)
    except EdgeError as exc:
        assert "no admissible witness set" in str(exc)
    else:
        raise AssertionError("proposed evidence cannot satisfy the witness floor")


def test_plan_and_report_tamper_fail() -> None:
    donors, seams, coverage = inputs()
    plan = compile_plan(donors, seams, coverage)
    assert verify_plan(donors, seams, coverage, plan) == []
    bad_plan = copy.deepcopy(plan)
    bad_plan["objective"]["total_cost_units"] = 1
    assert verify_plan(donors, seams, coverage, bad_plan)

    report = compile_report(donors, seams, coverage)
    assert verify_report(donors, seams, coverage, report) == []
    bad_report = copy.deepcopy(report)
    bad_report["totals"]["seams"] = 1
    assert verify_report(donors, seams, coverage, bad_report)


def test_report_exposes_venn_support_and_gaps() -> None:
    report = compile_report(*inputs())
    assert report["uncovered_mandatory_seams"] == []
    assert report["under_supported_mandatory_seams"] == []
    assert report["totals"]["pair_and_triple_intersections"] > 0
    assert any(item["order"] == 3 for item in report["pile_intersections"])
    assert any(
        item["seam_id"] == "seam.state-compilation"
        and item["support_state"] == "multi_pile"
        for item in report["seam_support"]
    )
    assert report["production_claim"] is False
    assert report["promotion_authorized"] is False


def test_markdown_is_deterministic_and_score_free() -> None:
    report = compile_report(*inputs())
    first = render_markdown(report)
    second = render_markdown(copy.deepcopy(report))
    assert first == second
    assert "witness.partitioned-controller" in first
    assert "aggregate score" not in first.lower()
    assert "readiness score" not in first.lower()


def test_duplicate_donor_identity_fails() -> None:
    donors, seams, coverage = inputs()
    duplicate = copy.deepcopy(donors["piles"][0]["donors"][0])
    donors["piles"][1]["donors"].append(duplicate)
    try:
        validate_bundle(donors, seams, coverage)
    except EdgeError as exc:
        assert "duplicate donor id" in str(exc)
    else:
        raise AssertionError("donor identities must be globally unique")


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"MENACE SEAM TESTS PASS: {len(tests)}/{len(tests)}")


if __name__ == "__main__":
    main()
