#!/usr/bin/env python3
"""Provider-free laws for the HALO3 Cell Zero lab and model fingerprint floor."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tier_runner.halo3_cell_common import Halo3Error  # noqa: E402
from tier_runner.halo3_cell_plan import (  # noqa: E402
    compile_plan,
    compile_proof_matrix,
    observation_templates,
    render_proof_markdown,
    verify_plan,
    verify_proof_matrix,
)
from tier_runner.halo3_cell_schema import (  # noqa: E402
    validate_fingerprint_contract,
    validate_lab,
)

LAB_PATH = ROOT / "labs" / "halo3-cell-zero" / "lab.json"
FINGERPRINT_PATH = ROOT / "labs" / "halo3-cell-zero" / "model_fingerprint_contract.json"
MARKDOWN_PATH = ROOT / "labs" / "halo3-cell-zero" / "PROOF_MATRIX.md"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sources() -> tuple[dict, dict]:
    return load(LAB_PATH), load(FINGERPRINT_PATH)


def test_reference_contracts_validate() -> None:
    lab_raw, fingerprint_raw = sources()
    fingerprint = validate_fingerprint_contract(fingerprint_raw)
    lab = validate_lab(lab_raw, fingerprint)
    assert lab["id"] == "halo3-cell-zero"
    assert {item["id"] for item in lab["models"]} == {
        "fable",
        "kimi3",
        "deterministic-control",
    }
    assert len(lab["nodes"]) == 9
    assert len(lab["stages"]) == 12
    assert len(lab["claims"]) == 12
    assert len(fingerprint["dimensions"]) == 8
    assert len(fingerprint["families"]) == 9


def test_exact_plan_denominator() -> None:
    plan = compile_plan(*sources())
    assert plan["totals"] == {
        "models": 3,
        "fingerprint_dimensions": 8,
        "fingerprint_families": 9,
        "fingerprint_conditions": 2,
        "fingerprint_cells": 54,
        "nodes": 9,
        "stages": 12,
        "claims": 12,
        "faults": 8,
        "cells": 66,
    }
    assert len({item["cell_id"] for item in plan["fingerprint_cells"]}) == 54
    assert len({item["cell_id"] for item in plan["stage_cells"]}) == 12
    assert plan["production_claim"] is False
    assert plan["promotion_authorized"] is False


def test_generated_plan_and_committed_proof_markdown_are_exact() -> None:
    lab, fingerprint = sources()
    plan = compile_plan(lab, fingerprint)
    matrix = compile_proof_matrix(lab, fingerprint)
    assert verify_plan(lab, fingerprint, plan) == []
    assert verify_proof_matrix(lab, fingerprint, matrix) == []
    rendered = render_proof_markdown(matrix)
    assert rendered == MARKDOWN_PATH.read_text(encoding="utf-8")


def test_identity_modes_are_not_flattened() -> None:
    plan = compile_plan(*sources())
    assert plan["model_identity_modes"] == {
        "fable": "provider_observational",
        "kimi3": "exact_open_weight",
        "deterministic-control": "deterministic_control",
    }
    fable_cells = [item for item in plan["fingerprint_cells"] if item["model_id"] == "fable"]
    kimi_cells = [item for item in plan["fingerprint_cells"] if item["model_id"] == "kimi3"]
    assert all(item["identity_mode"] == "provider_observational" for item in fable_cells)
    assert all(item["identity_mode"] == "exact_open_weight" for item in kimi_cells)


def test_every_claim_has_negative_and_subtraction_controls() -> None:
    matrix = compile_proof_matrix(*sources())
    for claim in matrix["claims"]:
        assert claim["negative_control"]
        assert claim["subtraction_target"] in claim["minimal_witnesses"]
        assert claim["required_receipts"]
        assert claim["acceptance"]
        assert claim["state"] == "declared"
    assert matrix["totals"]["accepted"] == 0
    assert matrix["production_claim"] is False


def test_observation_templates_begin_entirely_unmeasured() -> None:
    plan = compile_plan(*sources())
    templates = observation_templates(plan)
    assert len(templates) == 66
    assert all(item["status"] == "unmeasured" for item in templates)
    assert all(item["metrics"] == {} for item in templates)
    assert all(item["outcomes"] == {} for item in templates)
    assert all(item["receipts"] == [] for item in templates)


def test_model_cannot_gain_acceptance_authority() -> None:
    lab, fingerprint = sources()
    lab["models"][0]["authority_ceiling"] = "acceptance"
    try:
        validate_lab(lab, fingerprint)
    except Halo3Error as exc:
        assert "candidate_only" in str(exc)
    else:
        raise AssertionError("model acceptance authority must fail")


def test_halo3_cannot_become_survival_required() -> None:
    lab, fingerprint = sources()
    node = next(item for item in lab["nodes"] if item["id"] == "halo3-4060")
    node["survival_required"] = True
    try:
        validate_lab(lab, fingerprint)
    except Halo3Error as exc:
        assert "removable" in str(exc)
    else:
        raise AssertionError("HALO3 must remain removable")


def test_fixture_cannot_be_promoted_to_physical_qualification() -> None:
    lab, fingerprint = sources()
    node = next(item for item in lab["nodes"] if item["id"] == "halo3-4060")
    node["physical_qualification"] = True
    node["state"] = "qualified"
    node["receipt_refs"] = ["fixture-pass"]
    try:
        validate_lab(lab, fingerprint)
    except Halo3Error as exc:
        assert "not yet physically qualified" in str(exc)
    else:
        raise AssertionError("reference topology must not self-promote")


def test_fable_and_kimi_identity_modes_cannot_be_swapped() -> None:
    lab, fingerprint = sources()
    fable = next(item for item in lab["models"] if item["id"] == "fable")
    kimi = next(item for item in lab["models"] if item["id"] == "kimi3")
    fable["identity_mode"], kimi["identity_mode"] = kimi["identity_mode"], fable["identity_mode"]
    try:
        validate_lab(lab, fingerprint)
    except Halo3Error as exc:
        assert "Fable identity" in str(exc) or "Kimi3 identity" in str(exc)
    else:
        raise AssertionError("identity evidence modes must remain distinct")


def test_aggregate_score_metric_is_refused() -> None:
    lab, fingerprint = sources()
    lab["required_metrics"].append("aggregate-score")
    try:
        validate_lab(lab, fingerprint)
    except Halo3Error as exc:
        assert "aggregate score" in str(exc)
    else:
        raise AssertionError("aggregate score must be refused")


def test_claim_without_subtraction_target_fails() -> None:
    lab, fingerprint = sources()
    claim = lab["claims"][0]
    claim["subtraction_target"] = "node:halo3-4060"
    try:
        validate_lab(lab, fingerprint)
    except Halo3Error as exc:
        assert "minimal_witnesses" in str(exc)
    else:
        raise AssertionError("subtraction target must belong to the witness set")


def test_unknown_witness_fails_closed() -> None:
    lab, fingerprint = sources()
    lab["claims"][0]["minimal_witnesses"].append("node:fabricated-node")
    try:
        validate_lab(lab, fingerprint)
    except Halo3Error as exc:
        assert "unknown node" in str(exc)
    else:
        raise AssertionError("unknown witness must fail")


def test_plan_and_matrix_tamper_are_detected() -> None:
    lab, fingerprint = sources()
    plan = compile_plan(lab, fingerprint)
    bad_plan = copy.deepcopy(plan)
    bad_plan["totals"]["cells"] = 1
    assert verify_plan(lab, fingerprint, bad_plan)

    matrix = compile_proof_matrix(lab, fingerprint)
    bad_matrix = copy.deepcopy(matrix)
    bad_matrix["claims"][0]["state"] = "accepted"
    assert verify_proof_matrix(lab, fingerprint, bad_matrix)


def test_markdown_is_score_free_and_names_control_question() -> None:
    markdown = render_proof_markdown(compile_proof_matrix(*sources()))
    assert "aggregate score" not in markdown.lower()
    assert "certify itself" in markdown
    assert "Control question" in markdown
    assert "fixture" in markdown.lower()


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"HALO3 CELL ZERO TESTS PASS: {len(tests)}/{len(tests)}")


if __name__ == "__main__":
    main()
