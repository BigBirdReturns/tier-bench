#!/usr/bin/env python3
"""Zero-model-call and fixture-executor tests for the Anchor Crate floor."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tier_runner.anchor_crate_common import AnchorError, DRIVER_RESPONSE_SCHEMA  # noqa: E402
from tier_runner.anchor_crate_plan import compare_backend_bindings, compile_plan, verify_plan  # noqa: E402
from tier_runner.anchor_crate_runtime import (  # noqa: E402
    _validate_driver_response,
    backend_conformance,
    run_cartridge,
)
from tier_runner.anchor_crate_schema import (  # noqa: E402
    validate_backend_registry,
    validate_cartridge,
    validate_floor,
)

FIXTURE = ROOT / "labs" / "community-home-lab" / "anchor-crate"


def load(name: str) -> dict:
    return json.loads((FIXTURE / name).read_text(encoding="utf-8"))


def test_floor_and_fixtures_validate() -> None:
    floor = validate_floor(load("floor.json"))
    cartridge = validate_cartridge(load("physical_availability_cartridge.json"))
    registry = validate_backend_registry(load("backend_registry.json"))
    assert floor["id"] == "community-home-lab.anchor-crate-v1"
    assert len(cartridge["nodes"]) == 4
    assert {row["architecture"] for row in registry["backends"]} >= {"cuda-sm86", "riscv64"}
    assert all(row["physical_qualification"] is False for row in registry["backends"])


def test_default_plan_selects_cuda_but_keeps_portable_identity() -> None:
    plan = compile_plan(load("floor.json"), load("physical_availability_cartridge.json"), load("backend_registry.json"))
    assert plan["bindings"]["generate_decision_packet"] == "backend.cuda3090-fixture"
    assert plan["claims"]["pooled_memory"] is False
    assert plan["claims"]["backend_neutral_task_identity"] is True
    assert verify_plan(
        load("floor.json"),
        load("physical_availability_cartridge.json"),
        load("backend_registry.json"),
        plan,
    ) == []


def test_cuda_and_riscv_share_task_identity_but_not_execution_identity() -> None:
    floor = load("floor.json")
    cartridge = load("physical_availability_cartridge.json")
    registry = load("backend_registry.json")
    cuda = compile_plan(floor, cartridge, registry)
    riscv = compile_plan(
        floor,
        cartridge,
        registry,
        bindings={"generate_decision_packet": "backend.riscv-llm-fixture"},
    )
    assert cuda["portable_task_id"] == riscv["portable_task_id"]
    assert cuda["semantic_cartridge_sha256"] == riscv["semantic_cartridge_sha256"]
    assert cuda["plan_id"] != riscv["plan_id"]
    cuda_node = next(row for row in cuda["nodes"] if row["node_id"] == "generate_decision_packet")
    riscv_node = next(row for row in riscv["nodes"] if row["node_id"] == "generate_decision_packet")
    assert cuda_node["node_semantic_id"] == riscv_node["node_semantic_id"]
    assert cuda_node["execution_id"] != riscv_node["execution_id"]


def test_no_implicit_pooling() -> None:
    registry = load("backend_registry.json")
    for backend in registry["backends"]:
        if backend["id"] in {"backend.cuda3090-fixture", "backend.riscv-llm-fixture"}:
            backend["memory_mib"] = 1024
    try:
        compile_plan(load("floor.json"), load("physical_availability_cartridge.json"), registry)
    except AnchorError as exc:
        assert "no admissible backend" in str(exc)
    else:
        raise AssertionError("two undersized backends must not be pooled")


def test_cycle_fails_closed() -> None:
    cartridge = load("physical_availability_cartridge.json")
    cartridge["nodes"][0]["depends_on"] = ["verify_decision_packet"]
    try:
        validate_cartridge(cartridge)
    except AnchorError as exc:
        assert "cycle" in str(exc)
    else:
        raise AssertionError("cyclic DAG must fail")


def test_floor_refuses_backend_acceptance() -> None:
    floor = load("floor.json")
    floor["authority"]["executor_may"].append("acceptance")
    try:
        validate_floor(floor)
    except AnchorError as exc:
        assert "may not own acceptance" in str(exc)
    else:
        raise AssertionError("executor acceptance authority must fail")


def test_executor_response_cannot_claim_acceptance() -> None:
    response = {
        "schema": DRIVER_RESPONSE_SCHEMA,
        "request_id": "request-1",
        "backend_id": "backend.fixture",
        "status": "ok",
        "output": {},
        "telemetry": {"status": "ok", "elapsed_ms": 1, "memory_peak_mib": 1, "energy_mwh": 0},
        "advisory": [],
        "accepted": True,
    }
    try:
        _validate_driver_response(response, request_id="request-1", backend_id="backend.fixture")
    except AnchorError as exc:
        assert "controller-owned" in str(exc)
    else:
        raise AssertionError("executor self-acceptance must fail")


def _run(root: Path, *, riscv: bool = False, stop_after: str | None = None, resume: Path | None = None) -> dict:
    bindings = {"generate_decision_packet": "backend.riscv-llm-fixture"} if riscv else None
    return run_cartridge(
        load("floor.json"),
        load("physical_availability_cartridge.json"),
        load("backend_registry.json"),
        run_root=root,
        controller_cwd=ROOT,
        bindings=bindings,
        stop_after_node=stop_after,
        resume_anchor=resume,
    )


def test_cuda_and_riscv_runs_are_validator_equivalent() -> None:
    with tempfile.TemporaryDirectory() as temp:
        parent = Path(temp)
        cuda = _run(parent / "cuda")
        riscv = _run(parent / "riscv", riscv=True)
        assert cuda["status"] == riscv["status"] == "accepted"
        assert cuda["portable_task_id"] == riscv["portable_task_id"]
        assert cuda["plan_id"] != riscv["plan_id"]
        assert cuda["final_product"]["availability_state"] == riscv["final_product"]["availability_state"]
        assert cuda["final_product"]["decision_packet"]["claim"] == "not_physically_available"
        assert riscv["final_product"]["decision_packet"]["claim"] == "not_physically_available"
        assert cuda["final_product"]["decision_packet"]["summary"] != riscv["final_product"]["decision_packet"]["summary"]
        assert cuda["production_claim"] is False and riscv["promotion_authorized"] is False


def test_controller_replacement_resumes_from_anchor() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp) / "resume"
        paused = _run(root, stop_after="derive_availability")
        assert paused["status"] == "paused"
        assert paused["anchor"]["sequence"] == 2
        anchor_path = next((root / "anchors").glob(f"0002-{paused['anchor']['anchor_sha256']}.json"))
        resumed = _run(root, resume=anchor_path)
        assert resumed["status"] == "accepted"
        assert resumed["anchor"]["sequence"] == 4
        assert resumed["final_product"]["decision_packet"]["requires_human_review"] is True
        events = (root / "events.jsonl").read_text(encoding="utf-8")
        assert '"event":"controller_resume"' in events


def test_existing_partial_run_requires_explicit_anchor() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp) / "partial"
        _run(root, stop_after="derive_availability")
        try:
            _run(root)
        except AnchorError as exc:
            assert "resume requires an explicit anchor" in str(exc)
        else:
            raise AssertionError("implicit conversational recovery must fail")


def test_tampered_anchor_fails() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp) / "tamper"
        paused = _run(root, stop_after="derive_availability")
        original = next((root / "anchors").glob(f"0002-{paused['anchor']['anchor_sha256']}.json"))
        tampered = root / "tampered-anchor.json"
        payload = json.loads(original.read_text(encoding="utf-8"))
        payload["node_states"]["derive_availability"]["status"] = "pending"
        tampered.write_text(json.dumps(payload), encoding="utf-8")
        try:
            _run(root, resume=tampered)
        except AnchorError as exc:
            assert "hash mismatch" in str(exc)
        else:
            raise AssertionError("tampered anchor must fail")


def test_artifact_and_anchor_chain_are_content_addressed() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp) / "chain"
        result = _run(root)
        anchors = sorted((root / "anchors").glob("*.json"))
        assert len(anchors) == 5
        previous = None
        for sequence, path in enumerate(anchors):
            row = json.loads(path.read_text(encoding="utf-8"))
            assert row["sequence"] == sequence
            assert row["parent_anchor_sha256"] == previous
            previous = row["anchor_sha256"]
        assert previous == result["anchor"]["anchor_sha256"]
        for descriptor in result["anchor"]["artifacts"].values():
            artifact = root / "artifacts" / descriptor["sha256"][:2] / f"{descriptor['sha256']}.json"
            assert artifact.is_file()


def test_backend_conformance_covers_all_abi_operations() -> None:
    registry = load("backend_registry.json")
    for backend_id in (
        "backend.host-controller-fixture",
        "backend.cuda3090-fixture",
        "backend.riscv-llm-fixture",
    ):
        report = backend_conformance(registry, backend_id=backend_id, controller_cwd=ROOT)
        assert report["passed"] is True
        assert {row["id"] for row in report["cases"]} == {"describe", "probe", "execute", "cancel", "collect"}
        assert report["physical_qualification"] is False
        assert report["production_claim"] is False


def test_backend_toolchain_drift_changes_execution_not_task() -> None:
    floor = load("floor.json")
    cartridge = load("physical_availability_cartridge.json")
    first_registry = load("backend_registry.json")
    second_registry = copy.deepcopy(first_registry)
    backend = next(row for row in second_registry["backends"] if row["id"] == "backend.cuda3090-fixture")
    backend["toolchain_sha256"] = "f" * 64
    first = compile_plan(floor, cartridge, first_registry)
    second = compile_plan(floor, cartridge, second_registry)
    assert first["portable_task_id"] == second["portable_task_id"]
    assert first["plan_id"] != second["plan_id"]
    first_exec = next(row for row in first["nodes"] if row["node_id"] == "generate_decision_packet")["execution_id"]
    second_exec = next(row for row in second["nodes"] if row["node_id"] == "generate_decision_packet")["execution_id"]
    assert first_exec != second_exec



def test_editorial_changes_do_not_rekey_portable_task() -> None:
    floor = load("floor.json")
    cartridge = load("physical_availability_cartridge.json")
    registry = load("backend_registry.json")
    baseline = compile_plan(floor, cartridge, registry)
    floor["title"] = "Editorially revised home-lab floor"
    floor["claim"] = "Reworded claim with unchanged authority and ABI."
    floor["commodity_bindings"]["telemetry"] = ["another-observer"]
    cartridge["title"] = "Editorially revised cartridge"
    cartridge["notes"] = "Editorial note only."
    for validator in cartridge["validators"]:
        validator["description"] += " Editorial clarification."
    revised = compile_plan(floor, cartridge, registry)
    assert baseline["portable_task_id"] == revised["portable_task_id"]
    assert baseline["semantic_cartridge_sha256"] == revised["semantic_cartridge_sha256"]
    assert baseline["floor_contract_sha256"] == revised["floor_contract_sha256"]
    assert baseline["plan_id"] != revised["plan_id"]


def test_authority_change_rekeys_portable_task() -> None:
    floor = load("floor.json")
    cartridge = load("physical_availability_cartridge.json")
    registry = load("backend_registry.json")
    baseline = compile_plan(floor, cartridge, registry)
    floor["authority"]["planner_may"].append("additional-bounded-proposal")
    revised = compile_plan(floor, cartridge, registry)
    assert baseline["floor_contract_sha256"] != revised["floor_contract_sha256"]
    assert baseline["portable_task_id"] != revised["portable_task_id"]


def test_backend_equivalence_report_is_exact() -> None:
    report = compare_backend_bindings(
        load("floor.json"),
        load("physical_availability_cartridge.json"),
        load("backend_registry.json"),
        node_id="generate_decision_packet",
        backend_a="backend.cuda3090-fixture",
        backend_b="backend.riscv-llm-fixture",
    )
    assert all(report["assertions"].values())
    assert report["backend_a"]["physical_qualification"] is False
    assert report["backend_b"]["physical_qualification"] is False
    assert report["production_claim"] is False


def test_node_must_match_floor_operation_contract() -> None:
    cartridge = load("physical_availability_cartridge.json")
    cartridge["nodes"][2]["output_schema"] = "schema.unrelated-v1"
    try:
        compile_plan(load("floor.json"), cartridge, load("backend_registry.json"))
    except AnchorError as exc:
        assert "output schema differs" in str(exc)
    else:
        raise AssertionError("node lowering must match the floor operation contract")

def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"ANCHOR CRATE TESTS PASS: {len(tests)}/{len(tests)}")


if __name__ == "__main__":
    main()
