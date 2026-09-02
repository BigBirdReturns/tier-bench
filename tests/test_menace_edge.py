#!/usr/bin/env python3
"""Zero-model-call laws for MENACE edge qualification."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tier_runner.menace_edge_analysis import analyze  # noqa: E402
from tier_runner.menace_edge_common import EdgeError, OBSERVATION_SCHEMA  # noqa: E402
from tier_runner.menace_edge_plan import (  # noqa: E402
    compile_plan,
    observation_templates,
    verify_plan,
)
from tier_runner.menace_edge_schema import validate_manifest  # noqa: E402

MANIFEST_PATH = ROOT / "experiments" / "menace_edge" / "menace_edge_01.json"


def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def measured_observation(cell: dict, plan_id: str, *, treatment: str) -> dict:
    candidate = treatment.startswith("axm-3090")
    metrics = {
        "wall_energy_mwh": 1500 if candidate else 1000,
        "gpu_energy_mwh": 800 if candidate else 0,
        "elapsed_ms": 2000 if candidate else 4000,
        "time_to_first_useful_ms": 1000 if candidate else 3000,
        "human_active_ms": 500 if candidate else 1200,
        "external_bytes_in": 1000,
        "external_bytes_avoided": 10000 if candidate else 0,
        "accepted_products": 2 if candidate else 1,
        "rejected_products": 0,
        "consequential_misses": 0,
        "role_seconds_served": 20 if candidate else 10,
        "average_wall_power_mw": 250000 if candidate else 50000,
        "model_calls": 1 if candidate else 0,
        "operator_interventions": 0 if candidate else 1,
        "recovery_ms": 1000,
    }
    return {
        "schema": OBSERVATION_SCHEMA,
        "status": "measured",
        "plan_id": plan_id,
        "cell_id": cell["cell_id"],
        "treatment_id": cell["treatment_id"],
        "workload_id": cell["workload_id"],
        "hardware_profile": cell["hardware_profile"],
        "connectivity_profile": cell["connectivity_profile"],
        "sequence": cell["sequence"],
        "direction": cell["direction"],
        "observed_at": "2026-08-05T00:00:00Z",
        "hardware_identity": "fixture-head|fixture-enclosure|fixture-gpu",
        "runtime_identity": "fixture-runtime@1",
        "model_identity": "fixture-model@1" if candidate else "none",
        "metrics": metrics,
        "outcomes": {
            "useful_product_produced": True,
            "human_accepted": True,
            "survival_floor_retained": True,
            "authority_widened": False,
            "history_preserved": True,
            "conflict_disclosed": True,
            "human_disposition_recorded": True,
            "gpu_required_for_basic_state": False,
            "wan_required_for_basic_state": False,
        },
        "receipts": [
            {"kind": "fixture", "sha256": "a" * 64, "ref": f"fixture:{cell['cell_id']}"}
        ],
    }


def full_rows(plan: dict, treatments: set[str]) -> list[dict]:
    return [
        measured_observation(cell, plan["plan_id"], treatment=cell["treatment_id"])
        for cell in plan["cells"]
        if cell["treatment_id"] in treatments
    ]


def test_reference_manifest_and_plan() -> None:
    raw = manifest()
    normalized = validate_manifest(raw)
    assert normalized["id"] == "menace-edge-01"
    plan = compile_plan(raw)
    assert plan["totals"]["connectivity_steps"] == 9
    assert plan["totals"]["workloads"] == 5
    assert plan["totals"]["treatments"] == 7
    assert plan["totals"]["cells"] == 315
    assert plan["route"][0]["profile_id"] == "C0"
    assert plan["route"][-1]["profile_id"] == "C0"
    assert plan["route"][4]["profile_id"] == "C4"
    assert verify_plan(raw, plan) == []


def test_templates_are_unmeasured_and_complete() -> None:
    plan = compile_plan(manifest())
    templates = observation_templates(plan)
    assert len(templates) == len(plan["cells"])
    assert all(row["status"] == "unmeasured" for row in templates)
    assert all(row["metrics"] == {} and row["receipts"] == [] for row in templates)


def test_model_cannot_gain_authority() -> None:
    raw = manifest()
    raw["authority"]["model_role"] = "decision_authority"
    try:
        validate_manifest(raw)
    except EdgeError as exc:
        assert "proposal_only" in str(exc)
    else:
        raise AssertionError("model authority widening must fail")


def test_survival_floor_cannot_require_wan_or_gpu() -> None:
    for key in ("wan_required", "gpu_required", "remote_auth_required"):
        raw = manifest()
        raw["survival_floor"][key] = True
        try:
            validate_manifest(raw)
        except EdgeError as exc:
            assert "survival floor" in str(exc)
        else:
            raise AssertionError(f"{key} must fail closed")


def test_pooled_vram_claim_fails() -> None:
    raw = manifest()
    raw["hardware_profiles"][1]["memory_pooling"] = True
    try:
        validate_manifest(raw)
    except EdgeError as exc:
        assert "pooled-VRAM" in str(exc)
    else:
        raise AssertionError("pooled VRAM must not be admitted")


def test_connectivity_must_add_each_stream_once() -> None:
    raw = manifest()
    raw["connectivity_profiles"][2]["adds_streams"].append("local_device")
    try:
        validate_manifest(raw)
    except EdgeError as exc:
        assert "re-adds existing streams" in str(exc)
    else:
        raise AssertionError("connectivity must remain additive rather than duplicative")


def test_fault_cannot_drop_survival_capabilities() -> None:
    raw = manifest()
    raw["faults"][0]["expected_retained_capabilities"].remove("mission_state")
    try:
        validate_manifest(raw)
    except EdgeError as exc:
        assert "drop survival capabilities" in str(exc)
    else:
        raise AssertionError("fault may not drop survival state")


def test_plan_tamper_fails() -> None:
    raw = manifest()
    plan = compile_plan(raw)
    plan["cells"][0]["hardware"]["memory_pooling"] = True
    assert verify_plan(raw, plan)


def test_candidate_beats_baseline_on_vector_without_score() -> None:
    raw = manifest()
    plan = compile_plan(raw)
    rows = full_rows(plan, {"baseline-current", "axm-3090-250"})
    report = analyze(raw, plan, rows)
    by_id = {row["treatment_id"]: row for row in report["treatments"]}
    assert by_id["baseline-current"]["verdict"] == "BASELINE"
    assert by_id["axm-3090-250"]["verdict"] == "ADMISSIBLE"
    assert by_id["axm-3090-250"]["matched_baseline_delta"]["accepted_products"] > 0
    assert by_id["axm-3090-250"]["matched_baseline_delta"]["human_active_ms_saved"] > 0
    assert by_id["axm-3090-250"]["metric_vector"]["accepted_products_per_wh"]
    rendered = json.dumps(report, sort_keys=True)
    assert '"score"' not in rendered
    assert '"aggregate_score"' not in rendered
    assert report["production_claim"] is False
    assert report["promotion_authorized"] is False


def test_incomplete_telemetry_holds_candidate() -> None:
    raw = manifest()
    plan = compile_plan(raw)
    rows = full_rows(plan, {"baseline-current", "axm-3090-250"})
    rows = [row for row in rows if not (
        row["treatment_id"] == "axm-3090-250" and row["cell_id"] == next(
            cell["cell_id"] for cell in plan["cells"] if cell["treatment_id"] == "axm-3090-250"
        )
    )]
    report = analyze(raw, plan, rows)
    candidate = next(row for row in report["treatments"] if row["treatment_id"] == "axm-3090-250")
    assert candidate["verdict"] == "HELD"
    assert candidate["missing_cells"] == 1


def test_remote_conflict_without_human_disposition_rejects() -> None:
    raw = manifest()
    plan = compile_plan(raw)
    rows = full_rows(plan, {"baseline-current", "axm-3090-250"})
    for row in rows:
        cell = next(cell for cell in plan["cells"] if cell["cell_id"] == row["cell_id"])
        if row["treatment_id"] == "axm-3090-250" and any(
            fault["kind"] == "remote_local_conflict" for fault in cell["faults"]
        ):
            row["outcomes"]["human_disposition_recorded"] = False
            break
    report = analyze(raw, plan, rows)
    candidate = next(row for row in report["treatments"] if row["treatment_id"] == "axm-3090-250")
    assert candidate["verdict"] == "REJECTED"
    assert any("human disposition" in item["reason"] for item in candidate["survival_failures"])


def test_gpu_disconnect_must_retain_basic_state() -> None:
    raw = manifest()
    plan = compile_plan(raw)
    rows = full_rows(plan, {"baseline-current", "axm-3090-250"})
    for row in rows:
        cell = next(cell for cell in plan["cells"] if cell["cell_id"] == row["cell_id"])
        if row["treatment_id"] == "axm-3090-250" and any(
            fault["kind"] == "gpu_disconnect" for fault in cell["faults"]
        ):
            row["outcomes"]["gpu_required_for_basic_state"] = True
            row["outcomes"]["survival_floor_retained"] = False
            break
    report = analyze(raw, plan, rows)
    candidate = next(row for row in report["treatments"] if row["treatment_id"] == "axm-3090-250")
    assert candidate["verdict"] == "REJECTED"
    assert any("burst GPU" in item["reason"] for item in candidate["survival_failures"])


def test_duplicate_observation_fails() -> None:
    raw = manifest()
    plan = compile_plan(raw)
    row = measured_observation(plan["cells"][0], plan["plan_id"], treatment="baseline-current")
    try:
        analyze(raw, plan, [row, copy.deepcopy(row)])
    except EdgeError as exc:
        assert "duplicate observation" in str(exc)
    else:
        raise AssertionError("duplicate cells must fail")


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"MENACE EDGE TESTS PASS: {len(tests)}/{len(tests)}")


if __name__ == "__main__":
    main()
