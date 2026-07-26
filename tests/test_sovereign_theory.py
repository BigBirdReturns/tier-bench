#!/usr/bin/env python3
"""Zero-model-call tests for the Sovereign Theory Lab."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tier_runner.sovereign_common import PlaneError  # noqa: E402
from tier_runner.sovereign_theory_analysis import analyze  # noqa: E402
from tier_runner.sovereign_theory_plan import (  # noqa: E402
    compile_plan,
    observation_templates,
    verify_plan,
)
from tier_runner.sovereign_theory_schema import validate_lab, validate_observation  # noqa: E402


def fixture() -> dict:
    return {
        "schema": "tier-bench/sovereign-theory-lab@1",
        "id": "fixture-theory-lab",
        "title": "Fixture",
        "objective": "Test the theory instrument without model calls.",
        "laws": ["Errors are non-decisive.", "Runtime identity must match."],
        "metrics": [
            {
                "id": "operator_minutes",
                "kind": "number",
                "direction": "minimize",
                "required": True,
                "unit": "minutes",
                "description": "Operator time.",
            },
            {
                "id": "wall_seconds",
                "kind": "number",
                "direction": "minimize",
                "required": True,
                "unit": "seconds",
                "description": "Elapsed time.",
            },
            {
                "id": "escaped_defects",
                "kind": "count",
                "direction": "minimize",
                "required": True,
                "unit": "defects",
                "description": "Audit defects.",
            },
        ],
        "tasks": [
            {
                "id": "task-a",
                "title": "Task A",
                "family": "bounded",
                "status": "ready",
                "acceptance_class": "hidden_grade",
                "source": "fixture",
                "selection_contract": "frozen",
                "tags": [],
            },
            {
                "id": "task-b",
                "title": "Task B",
                "family": "bounded",
                "status": "ready",
                "acceptance_class": "hidden_grade",
                "source": "fixture",
                "selection_contract": "frozen",
                "tags": [],
            },
            {
                "id": "slot-c",
                "title": "Future task",
                "family": "future",
                "status": "operator_task_required",
                "acceptance_class": "mixed",
                "source": "future",
                "selection_contract": "select before execution",
                "tags": [],
            },
        ],
        "theories": [
            {
                "id": "H-fixture",
                "title": "Treatment reduces time",
                "status": "hypothesis",
                "priority": 100,
                "claim": "The treatment preserves acceptance and reduces time.",
                "mechanism": "The treatment removes repeated work.",
                "prediction": "Wall time falls by at least twenty percent.",
                "task_families": ["bounded"],
                "minimum_distinct_tasks": 2,
                "replicates_per_cell": 2,
                "arms": [
                    {
                        "id": "control",
                        "label": "Control",
                        "role": "control",
                        "settings": {"mode": "cold"},
                        "resource_hints": ["gpu:3090"],
                    },
                    {
                        "id": "treatment",
                        "label": "Treatment",
                        "role": "treatment",
                        "settings": {"mode": "warm"},
                        "resource_hints": ["gpu:3090"],
                    },
                ],
                "support": [
                    {
                        "metric": "pass_rate",
                        "aggregate": "rate",
                        "op": "gte_control",
                        "note": "Yield preserved.",
                    },
                    {
                        "metric": "wall_seconds",
                        "aggregate": "median",
                        "op": "ratio_lte_control",
                        "value": 0.8,
                        "note": "At least twenty percent faster.",
                    },
                    {
                        "metric": "operator_minutes",
                        "aggregate": "median",
                        "op": "lte_control",
                        "note": "Attention does not rise.",
                    },
                ],
                "falsify": [
                    {
                        "metric": "pass_rate",
                        "aggregate": "rate",
                        "op": "delta_lte_control",
                        "value": -0.2,
                        "note": "Large yield loss.",
                    }
                ],
                "confounds": ["OS cache."],
                "falsifier": "A twenty-point yield loss falsifies the treatment.",
                "failure_default": "PARTIAL.",
            },
            {
                "id": "H-blocked",
                "title": "Future-only theory",
                "status": "hypothesis",
                "priority": 10,
                "claim": "A future task will test this.",
                "mechanism": "Not yet selected.",
                "prediction": "Unknown.",
                "task_families": ["future"],
                "minimum_distinct_tasks": 1,
                "replicates_per_cell": 1,
                "arms": [
                    {"id": "c", "label": "C", "role": "control", "settings": {}, "resource_hints": []},
                    {"id": "t", "label": "T", "role": "treatment", "settings": {}, "resource_hints": []},
                ],
                "support": [
                    {"metric": "pass_rate", "aggregate": "rate", "op": "gte_control", "note": "pass"}
                ],
                "falsify": [
                    {"metric": "pass_rate", "aggregate": "rate", "op": "lt_control", "note": "fail"}
                ],
                "confounds": ["No task yet."],
                "falsifier": "A lower pass rate.",
                "failure_default": "UNMEASURED.",
            },
        ],
    }


def observation(
    theory: str,
    task: str,
    arm: str,
    replicate: int,
    *,
    outcome: str = "pass",
    wall: float = 100,
    operator: float = 1,
    defects: int = 0,
    requested: str | None = None,
    observed: str | None = None,
    attested: bool = True,
    telemetry: bool = True,
) -> dict:
    requested = requested or arm
    observed = observed or requested
    return {
        "schema": "tier-bench/sovereign-theory-observation@1",
        "theory_id": theory,
        "run_id": f"{theory}-{task}-{arm}-{replicate}",
        "task_id": task,
        "arm_id": arm,
        "replicate": replicate,
        "outcome": outcome,
        "runtime": {
            "requested": requested,
            "observed": observed,
            "attested": attested,
            "telemetry_complete": telemetry,
        },
        "metrics": {
            "operator_minutes": operator,
            "wall_seconds": wall,
            "escaped_defects": defects,
        },
        "receipt_sha256": "a" * 64,
        "notes": "fixture",
    }


def full_rows(*, treatment_wall: float = 70, treatment_outcome: str = "pass") -> list[dict]:
    rows = []
    for task in ("task-a", "task-b"):
        for replicate in (1, 2):
            rows.append(observation("H-fixture", task, "control", replicate, wall=100))
            rows.append(
                observation(
                    "H-fixture",
                    task,
                    "treatment",
                    replicate,
                    wall=treatment_wall,
                    outcome=treatment_outcome,
                )
            )
    return rows


def test_validate_real_registry() -> None:
    raw = json.loads(
        (ROOT / "experiments/sovereign_desktop/theories.json").read_text(encoding="utf-8")
    )
    lab = validate_lab(raw)
    assert len(lab["theories"]) == 22
    assert len(lab["tasks"]) == 22
    assert len(lab["metrics"]) == 29


def test_plan_is_deterministic_and_balanced() -> None:
    raw = fixture()
    first = compile_plan(raw)
    second = compile_plan(raw)
    assert first["runs"] == second["runs"]
    assert first["totals"]["runs"] == 8
    assert first["balance"]["H-fixture"]["max_position_imbalance"] <= 1
    blocked = {row["theory_id"]: row for row in first["blocked"]}
    assert blocked["H-blocked"]["ready_distinct_tasks"] == 0


def test_plan_tamper_fails() -> None:
    raw = fixture()
    plan = compile_plan(raw)
    assert verify_plan(raw, plan) == []
    plan["runs"][0]["arm_id"] = "treatment"
    assert any("runs" in error for error in verify_plan(raw, plan))


def test_templates_are_non_evidence() -> None:
    raw = fixture()
    plan = compile_plan(raw, include={"H-fixture"})
    rows = observation_templates(raw, plan)
    assert len(rows) == 8
    assert all(row["outcome"] == "partial" for row in rows)
    assert all(row["runtime"]["attested"] is False for row in rows)


def test_strict_boolean_rejection() -> None:
    lab = validate_lab(fixture())
    row = observation("H-fixture", "task-a", "control", 1)
    row["runtime"]["attested"] = "false"
    try:
        validate_observation(row, lab)
    except PlaneError as exc:
        assert "must be boolean" in str(exc)
    else:
        raise AssertionError("truthy string must not pass as attestation")


def test_supported_verdict() -> None:
    report = analyze(fixture(), full_rows(treatment_wall=70))
    result = {row["theory_id"]: row for row in report["theories"]}["H-fixture"]
    assert result["verdict"] == "SUPPORTED"
    assert result["treatments"][0]["verdict"] == "SUPPORTED"


def test_falsified_verdict() -> None:
    rows = full_rows(treatment_wall=70, treatment_outcome="fail")
    report = analyze(fixture(), rows)
    result = {row["theory_id"]: row for row in report["theories"]}["H-fixture"]
    assert result["verdict"] == "FALSIFIED"


def test_runtime_fallback_is_non_decisive() -> None:
    rows = full_rows(treatment_wall=70)
    for row in rows:
        if row["arm_id"] == "treatment" and row["task_id"] == "task-a":
            row["runtime"]["observed"] = "fallback"
    report = analyze(fixture(), rows)
    result = {row["theory_id"]: row for row in report["theories"]}["H-fixture"]
    assert result["verdict"] == "PARTIAL"
    assert result["arm_summaries"]["treatment"]["contaminated"] == 2


def test_error_does_not_buy_evidence() -> None:
    rows = full_rows(treatment_wall=70)
    rows[1]["outcome"] = "error"
    report = analyze(fixture(), rows)
    result = {row["theory_id"]: row for row in report["theories"]}["H-fixture"]
    assert result["verdict"] == "PARTIAL"
    assert result["arm_summaries"]["treatment"]["contaminated"] == 1


def test_duplicate_run_refused() -> None:
    rows = full_rows()
    rows.append(copy.deepcopy(rows[0]))
    try:
        analyze(fixture(), rows)
    except PlaneError as exc:
        assert "duplicate observation run_id" in str(exc)
    else:
        raise AssertionError("duplicate run should not count twice")


def main() -> int:
    tests = [
        test_validate_real_registry,
        test_plan_is_deterministic_and_balanced,
        test_plan_tamper_fails,
        test_templates_are_non_evidence,
        test_strict_boolean_rejection,
        test_supported_verdict,
        test_falsified_verdict,
        test_runtime_fallback_is_non_decisive,
        test_error_does_not_buy_evidence,
        test_duplicate_run_refused,
    ]
    parent = Path(tempfile.mkdtemp(prefix="sovereign-theory-"))
    try:
        for test in tests:
            test()
        print(f"OK - {len(tests)}/{len(tests)} theory-lab tests passed; zero model calls")
        return 0
    finally:
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
