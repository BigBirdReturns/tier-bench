#!/usr/bin/env python3
"""Zero-model-call tests for the Desktop Distillation Lab."""
from __future__ import annotations

import copy
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tier_runner.distillation_plan import (  # noqa: E402
    artifact_strategy,
    compile_lab_plan,
    lane_for,
    verify_lab_plan,
    work_orders,
)
from tier_runner.distillation_schema import LabError, validate_lab  # noqa: E402


def h(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()


def lab() -> dict:
    def evidence(name: str) -> dict:
        return {
            "task_fingerprint": h(name + ":task"),
            "teacher_receipt_sha256": h(name + ":teacher"),
            "floor_receipt_sha256": h(name + ":floor"),
            "grader_sha256": h(name + ":grader"),
            "source_packet_sha256": h(name + ":source"),
        }

    return {
        "schema": "tier-bench/desktop-distillation-lab@1",
        "id": "fixture-lab",
        "title": "Fixture lab",
        "student": {
            "model_id": "qwen-local-27b",
            "source_access": "source_and_weights",
            "trainable": True,
            "cost_usd_per_job": 0.05,
            "operator_minutes_per_job": 1,
        },
        "policy": {
            "min_distinct_replays": 3,
            "minimize_before_variants": True,
            "promotion_authority": "capture_ledger",
            "failure_default": "open",
        },
        "candidates": [
            {
                "id": "closed-recovery",
                "task_family": "autonomous-recovery",
                "claim": "Fable recovered after an induced failure that the local floor missed.",
                "teacher": {
                    "model_id": "claude-fable-5",
                    "source_access": "subscription_only",
                    "outcome": "pass",
                    "cost_usd_per_job": 2.5,
                    "operator_minutes_per_job": 18,
                },
                "floor": {
                    "model_id": "qwen-local-27b",
                    "outcome": "wall",
                    "attempts": 3,
                    "cost_usd_per_job": 0.05,
                    "operator_minutes_per_job": 1,
                },
                "recurrence": {"jobs_per_month": 8},
                "evidence": evidence("closed-recovery"),
                "suggested_artifacts": [
                    "prompt_scaffold",
                    "curriculum",
                    "verifier",
                    "lora",
                ],
                "capture_cost_estimate_usd": 40,
                "capture_operator_minutes_estimate": 120,
            },
            {
                "id": "open-routing",
                "task_family": "context-routing",
                "claim": "An open teacher found the minimal sufficient context route.",
                "teacher": {
                    "model_id": "kimi-k3-open",
                    "source_access": "weights",
                    "outcome": "pass",
                    "cost_usd_per_job": 1.0,
                    "operator_minutes_per_job": 5,
                },
                "floor": {
                    "model_id": "qwen-local-27b",
                    "outcome": "unstable",
                    "attempts": 5,
                    "cost_usd_per_job": 0.05,
                    "operator_minutes_per_job": 1,
                },
                "recurrence": {"jobs_per_month": 20},
                "evidence": evidence("open-routing"),
                "suggested_artifacts": ["context_compiler", "lora", "inference_policy"],
                "capture_cost_estimate_usd": 12,
                "capture_operator_minutes_estimate": 45,
            },
            {
                "id": "transport-only",
                "task_family": "transport",
                "claim": "The local adapter failed before grading.",
                "teacher": {
                    "model_id": "frontier",
                    "source_access": "api_only",
                    "outcome": "pass",
                    "cost_usd_per_job": 0.5,
                    "operator_minutes_per_job": 2,
                },
                "floor": {
                    "model_id": "local",
                    "outcome": "transport_error",
                    "attempts": 3,
                    "cost_usd_per_job": 0,
                    "operator_minutes_per_job": 0,
                },
                "recurrence": {"jobs_per_month": 5},
                "evidence": evidence("transport-only"),
                "suggested_artifacts": [],
                "capture_cost_estimate_usd": 5,
                "capture_operator_minutes_estimate": 10,
            },
            {
                "id": "unmeasured",
                "task_family": "unknown",
                "claim": "No lower-route measurement exists.",
                "teacher": {
                    "model_id": "frontier",
                    "source_access": "api_only",
                    "outcome": "pass",
                    "cost_usd_per_job": 0.5,
                    "operator_minutes_per_job": 2,
                },
                "floor": {
                    "model_id": "local",
                    "outcome": "unmeasured",
                    "attempts": 0,
                    "cost_usd_per_job": 0,
                    "operator_minutes_per_job": 0,
                },
                "recurrence": {"jobs_per_month": 5},
                "evidence": evidence("unmeasured"),
                "suggested_artifacts": [],
                "capture_cost_estimate_usd": 5,
                "capture_operator_minutes_estimate": 10,
            },
        ],
    }


def test_validation_is_strict() -> None:
    raw = lab()
    normalized = validate_lab(raw)
    assert normalized["student"]["trainable"] is True
    raw["student"]["trainable"] = "false"
    try:
        validate_lab(raw)
    except LabError as exc:
        assert "must be boolean" in str(exc)
    else:
        raise AssertionError("truthy string should not become trainable")


def test_lanes_and_blocking() -> None:
    raw = lab()
    normalized = validate_lab(raw)
    candidates = {item["id"]: item for item in normalized["candidates"]}
    assert lane_for(candidates["closed-recovery"]) == "behavioral"
    assert lane_for(candidates["open-routing"]) == "mechanistic"
    plan = compile_lab_plan(raw)
    assert len(plan["queue"]) == 2
    blocked = {item["candidate_id"]: item["reason"] for item in plan["blocked"]}
    assert "transport error" in blocked["transport-only"]
    assert "no decisive measurement" in blocked["unmeasured"]


def test_attention_first_priority() -> None:
    plan = compile_lab_plan(lab())
    assert plan["queue"][0]["candidate_id"] == "closed-recovery"
    assert plan["queue"][0]["economics"]["monthly_attention_savings_minutes"] == 136
    assert plan["queue"][1]["economics"]["monthly_attention_savings_minutes"] == 80


def test_behavioral_lane_excludes_weight_artifacts() -> None:
    normalized = validate_lab(lab())
    candidate = next(
        item for item in normalized["candidates"] if item["id"] == "closed-recovery"
    )
    artifacts = artifact_strategy(candidate, normalized["student"])
    assert "lora" not in artifacts
    assert "prompt_scaffold" in artifacts


def test_mechanistic_lane_keeps_trainable_artifacts() -> None:
    normalized = validate_lab(lab())
    candidate = next(item for item in normalized["candidates"] if item["id"] == "open-routing")
    artifacts = artifact_strategy(candidate, normalized["student"])
    assert "lora" in artifacts and "inference_policy" in artifacts


def test_break_even_uses_cost_delta() -> None:
    plan = compile_lab_plan(lab())
    row = next(item for item in plan["queue"] if item["candidate_id"] == "closed-recovery")
    economics = row["economics"]
    assert economics["cost_savings_usd_per_job"] == 2.45
    assert economics["projected_cost_break_even_jobs"] == 17
    assert economics["projected_attention_break_even_jobs"] == 8


def test_work_orders_are_dependency_bound() -> None:
    orders = work_orders(lab())
    closed = [
        item for item in orders["orders"] if item["candidate_id"] == "closed-recovery"
    ]
    assert [item["stage"] for item in closed] == [
        "minimize",
        "freeze",
        "variants",
        "capture",
        "replay",
        "promote",
    ]
    promote = closed[-1]
    assert promote["depends_on"] == ["distill-closed-recovery-replay"]


def test_plan_tamper_fails() -> None:
    raw = lab()
    plan = compile_lab_plan(raw)
    assert verify_lab_plan(raw, plan) == []
    tampered = copy.deepcopy(plan)
    tampered["totals"]["planned_candidates"] = 99
    assert any("totals" in error for error in verify_lab_plan(raw, tampered))


def main() -> int:
    parent = Path(tempfile.mkdtemp(prefix="distillation-lab-"))
    tests = [
        test_validation_is_strict,
        test_lanes_and_blocking,
        test_attention_first_priority,
        test_behavioral_lane_excludes_weight_artifacts,
        test_mechanistic_lane_keeps_trainable_artifacts,
        test_break_even_uses_cost_delta,
        test_work_orders_are_dependency_bound,
        test_plan_tamper_fails,
    ]
    failed = 0
    try:
        for test in tests:
            try:
                test()
                print(f"  ok  {test.__name__}")
            except Exception as exc:
                failed += 1
                print(f"FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
        print(f"\n{len(tests) - failed}/{len(tests)} distillation-lab tests passed")
        return 1 if failed else 0
    finally:
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
