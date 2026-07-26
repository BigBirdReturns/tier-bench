"""Compile bounded frontier residue into desktop acquisition work orders."""
from __future__ import annotations

import math
from typing import Any

from .distillation_schema import (
    DISTILL_PLAN_SCHEMA,
    hash_json,
    validate_lab,
)


def lane_for(candidate: dict[str, Any]) -> str:
    access = candidate["teacher"]["source_access"]
    if access in {"source_and_weights", "weights", "runtime_source"}:
        return "mechanistic"
    if access in {"api_only", "subscription_only"}:
        return "behavioral"
    return "blocked"


def artifact_strategy(
    candidate: dict[str, Any], student: dict[str, Any]
) -> list[str]:
    lane = lane_for(candidate)
    if candidate["suggested_artifacts"]:
        result = list(candidate["suggested_artifacts"])
    elif lane == "mechanistic" and student["trainable"]:
        result = ["adapter", "lora", "inference_policy", "verifier"]
    else:
        result = ["prompt_scaffold", "context_compiler", "verifier", "curriculum"]
    if lane == "behavioral":
        result = [
            item
            for item in result
            if item not in {"adapter", "lora", "weight_delta"}
        ]
        if not result:
            result = ["prompt_scaffold", "curriculum", "verifier"]
    if not student["trainable"]:
        result = [
            item
            for item in result
            if item not in {"adapter", "lora", "weight_delta"}
        ]
    return sorted(set(result))


def _stages(
    candidate: dict[str, Any],
    *,
    lane: str,
    student: dict[str, Any],
    replay_count: int,
    promotion_authority: str,
) -> list[dict[str, Any]]:
    stages = [
        {
            "id": "minimize",
            "depends_on": [],
            "authority": "external_grader",
            "purpose": (
                "Remove context, tools, and ceremony until the teacher still passes and "
                "the floor still fails or remains unstable."
            ),
            "inputs": [
                candidate["evidence"]["source_packet_sha256"],
                candidate["evidence"]["teacher_receipt_sha256"],
                candidate["evidence"]["floor_receipt_sha256"],
                candidate["evidence"]["grader_sha256"],
            ],
            "outputs": ["minimized_case", "separation_receipt"],
            "acceptance": "teacher passes; floor result preserved; grader hash unchanged",
        },
        {
            "id": "freeze",
            "depends_on": ["minimize"],
            "authority": "AXM_and_Git_bytes",
            "purpose": (
                "Bind source packet, model identities, receipts, and grader before "
                "synthesis or variant authoring."
            ),
            "inputs": ["minimized_case", "separation_receipt"],
            "outputs": ["immutable_acquisition_packet"],
            "acceptance": "all declared hashes resolve and the packet is immutable",
        },
        {
            "id": "variants",
            "depends_on": ["freeze"],
            "authority": "prospective_task_authoring",
            "purpose": (
                "Author distinct withheld variants without disclosing deciding keys to "
                "the student or teacher."
            ),
            "inputs": ["immutable_acquisition_packet"],
            "outputs": ["withheld_variant_set"],
            "acceptance": f"at least {replay_count} distinct work items with hidden graders",
        },
        {
            "id": "capture",
            "depends_on": ["variants"],
            "authority": "artifact_builder",
            "purpose": (
                "Convert the separating behavior into reusable machinery through the "
                f"{lane} lane."
            ),
            "inputs": ["immutable_acquisition_packet", "withheld_variant_set"],
            "outputs": artifact_strategy(candidate, student),
            "acceptance": "artifact bytes exist, are hash-bound, and do not contain hidden keys",
        },
        {
            "id": "replay",
            "depends_on": ["capture"],
            "authority": "hidden_grader",
            "purpose": (
                "Run fresh work through the student plus artifact without teacher access."
            ),
            "inputs": ["withheld_variant_set", "captured_artifact"],
            "outputs": ["replay_receipts"],
            "acceptance": f"{replay_count} distinct hidden-graded pass receipts",
        },
        {
            "id": "promote",
            "depends_on": ["replay"],
            "authority": promotion_authority,
            "purpose": "Admit the artifact only after replay evidence closes the burden.",
            "inputs": ["captured_artifact", "replay_receipts"],
            "outputs": ["capture_ledger_event"],
            "acceptance": "captured capability or explicit open gap",
        },
    ]
    return stages


def _economics(
    candidate: dict[str, Any], student: dict[str, Any]
) -> dict[str, Any]:
    jobs = candidate["recurrence"]["jobs_per_month"]
    teacher_cost = candidate["teacher"]["cost_usd_per_job"]
    student_cost = student["cost_usd_per_job"]
    teacher_attention = candidate["teacher"]["operator_minutes_per_job"]
    student_attention = student["operator_minutes_per_job"]
    savings_per_job = max(teacher_cost - student_cost, 0.0)
    attention_per_job = max(teacher_attention - student_attention, 0.0)
    monthly_cost = savings_per_job * jobs
    monthly_attention = attention_per_job * jobs
    capture_cost = candidate["capture_cost_estimate_usd"]
    capture_attention = candidate["capture_operator_minutes_estimate"]
    return {
        "jobs_per_month": jobs,
        "teacher_cost_usd_per_job": teacher_cost,
        "student_cost_usd_per_job": student_cost,
        "cost_savings_usd_per_job": round(savings_per_job, 6),
        "monthly_cost_savings_usd": round(monthly_cost, 6),
        "teacher_operator_minutes_per_job": teacher_attention,
        "student_operator_minutes_per_job": student_attention,
        "attention_savings_minutes_per_job": round(attention_per_job, 3),
        "monthly_attention_savings_minutes": round(monthly_attention, 3),
        "capture_cost_estimate_usd": capture_cost,
        "capture_operator_minutes_estimate": capture_attention,
        "projected_cost_break_even_jobs": (
            math.ceil(capture_cost / savings_per_job)
            if capture_cost is not None and savings_per_job > 0
            else None
        ),
        "projected_attention_break_even_jobs": (
            math.ceil(capture_attention / attention_per_job)
            if capture_attention is not None and attention_per_job > 0
            else None
        ),
    }


def compile_lab_plan(raw: Any) -> dict[str, Any]:
    lab = validate_lab(raw)
    queue: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for candidate in lab["candidates"]:
        lane = lane_for(candidate)
        outcome = candidate["floor"]["outcome"]
        if outcome == "transport_error":
            blocked.append(
                {
                    "candidate_id": candidate["id"],
                    "reason": "transport error is not capability residue",
                }
            )
            continue
        if outcome == "unmeasured":
            blocked.append(
                {
                    "candidate_id": candidate["id"],
                    "reason": "lower route has no decisive measurement",
                }
            )
            continue
        if lane == "blocked":
            blocked.append(
                {
                    "candidate_id": candidate["id"],
                    "reason": "teacher source access is unknown",
                }
            )
            continue
        economics = _economics(candidate, lab["student"])
        queue.append(
            {
                "candidate_id": candidate["id"],
                "task_family": candidate["task_family"],
                "claim": candidate["claim"],
                "lane": lane,
                "evidence_state": (
                    "measured_wall" if outcome == "wall" else "unstable"
                ),
                "teacher_model": candidate["teacher"]["model_id"],
                "student_model": lab["student"]["model_id"],
                "evidence": candidate["evidence"],
                "economics": economics,
                "stages": _stages(
                    candidate,
                    lane=lane,
                    student=lab["student"],
                    replay_count=lab["policy"]["min_distinct_replays"],
                    promotion_authority=lab["policy"]["promotion_authority"],
                ),
            }
        )
    queue.sort(
        key=lambda item: (
            -item["economics"]["monthly_attention_savings_minutes"],
            -item["economics"]["monthly_cost_savings_usd"],
            -item["economics"]["jobs_per_month"],
            item["candidate_id"],
        )
    )
    plan = {
        "schema": DISTILL_PLAN_SCHEMA,
        "lab_id": lab["id"],
        "lab_sha256": hash_json(lab),
        "student": lab["student"],
        "policy": lab["policy"],
        "authority": {
            "teacher_output": "candidate_evidence_only",
            "grader": "external_and_hidden",
            "promotion": lab["policy"]["promotion_authority"],
            "closed_weight_claim": (
                "behavioral reproduction only; proprietary weights are not recovered"
            ),
            "failure_default": lab["policy"]["failure_default"],
        },
        "queue": queue,
        "blocked": blocked,
        "totals": {
            "planned_candidates": len(queue),
            "blocked_candidates": len(blocked),
            "monthly_cost_savings_usd": round(
                sum(item["economics"]["monthly_cost_savings_usd"] for item in queue),
                6,
            ),
            "monthly_attention_savings_minutes": round(
                sum(
                    item["economics"]["monthly_attention_savings_minutes"]
                    for item in queue
                ),
                3,
            ),
        },
    }
    plan["plan_sha256"] = hash_json(plan)
    return plan


def verify_lab_plan(raw_lab: Any, raw_plan: Any) -> list[str]:
    expected = compile_lab_plan(raw_lab)
    if not isinstance(raw_plan, dict):
        return ["plan must be an object"]
    errors: list[str] = []
    for key in (
        "schema",
        "lab_id",
        "lab_sha256",
        "student",
        "policy",
        "authority",
        "queue",
        "blocked",
        "totals",
        "plan_sha256",
    ):
        if raw_plan.get(key) != expected.get(key):
            errors.append(f"plan.{key} does not match deterministic recompilation")
    return errors


def work_orders(raw: Any) -> dict[str, Any]:
    plan = compile_lab_plan(raw)
    orders = []
    for item in plan["queue"]:
        for stage in item["stages"]:
            orders.append(
                {
                    "id": f"distill-{item['candidate_id']}-{stage['id']}",
                    "candidate_id": item["candidate_id"],
                    "stage": stage["id"],
                    "depends_on": [
                        f"distill-{item['candidate_id']}-{dependency}"
                        for dependency in stage["depends_on"]
                    ],
                    "authority": stage["authority"],
                    "task": stage["purpose"],
                    "inputs": stage["inputs"],
                    "outputs": stage["outputs"],
                    "acceptance": stage["acceptance"],
                    "lane": item["lane"],
                    "priority_basis": {
                        "monthly_attention_savings_minutes": item["economics"][
                            "monthly_attention_savings_minutes"
                        ],
                        "monthly_cost_savings_usd": item["economics"][
                            "monthly_cost_savings_usd"
                        ],
                    },
                }
            )
    return {
        "schema": "tier-bench/desktop-distillation-work-orders@1",
        "lab_id": plan["lab_id"],
        "lab_sha256": plan["lab_sha256"],
        "orders": orders,
        "blocked": plan["blocked"],
    }
