"""Contracts and validation for the Desktop Distillation Lab."""
from __future__ import annotations

import hashlib
import json
from typing import Any

LAB_SCHEMA = "tier-bench/desktop-distillation-lab@1"
DISTILL_PLAN_SCHEMA = "tier-bench/desktop-distillation-plan@1"
SOURCE_ACCESS = {
    "source_and_weights",
    "weights",
    "runtime_source",
    "api_only",
    "subscription_only",
    "unknown",
}
FLOOR_OUTCOMES = {"wall", "unstable", "transport_error", "unmeasured"}
ARTIFACT_TYPES = {
    "prompt_scaffold",
    "context_compiler",
    "routing_rule",
    "verifier",
    "tool_policy",
    "curriculum",
    "adapter",
    "lora",
    "weight_delta",
    "inference_policy",
}
import re

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class LabError(ValueError):
    """A distillation candidate or plan violated its evidence contract."""


def canonical(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def hash_json(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def need_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LabError(f"{label} must be an object")
    return value


def need_array(value: Any, label: str, *, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        suffix = " and non-empty" if nonempty else ""
        raise LabError(f"{label} must be an array{suffix}")
    return value


def need_text(value: Any, label: str, limit: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise LabError(f"{label} must be a non-empty string of at most {limit} characters")
    return value.strip()


def safe_id(value: Any, label: str, limit: int = 120) -> str:
    result = need_text(value, label, limit)
    if not SAFE_ID.fullmatch(result):
        raise LabError(f"{label} contains unsafe characters")
    return result


def need_integer(value: Any, label: str, low: int = 0, high: int = 10**9) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise LabError(f"{label} must be an integer between {low} and {high}")
    return value


def need_number(value: Any, label: str, low: float = 0.0, high: float = 10**12) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LabError(f"{label} must be a number")
    result = float(value)
    if not low <= result <= high:
        raise LabError(f"{label} must be between {low} and {high}")
    return result


def optional_number(value: Any, label: str) -> float | None:
    return None if value is None else need_number(value, label)


def need_boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise LabError(f"{label} must be boolean")
    return value


def digest(value: Any, label: str) -> str:
    result = need_text(value, label, 64)
    if not SHA256.fullmatch(result):
        raise LabError(f"{label} must be lowercase SHA-256")
    return result


def _source_access(value: Any, label: str) -> str:
    result = need_text(value, label, 40)
    if result not in SOURCE_ACCESS:
        raise LabError(f"{label} must be one of {sorted(SOURCE_ACCESS)}")
    return result


def _candidate(raw: Any, index: int) -> dict[str, Any]:
    row = need_object(raw, f"candidates[{index}]")
    identifier = safe_id(row.get("id"), f"candidates[{index}].id")
    teacher = need_object(row.get("teacher"), f"candidate {identifier}.teacher")
    floor = need_object(row.get("floor"), f"candidate {identifier}.floor")
    recurrence = need_object(row.get("recurrence"), f"candidate {identifier}.recurrence")
    evidence = need_object(row.get("evidence"), f"candidate {identifier}.evidence")
    if teacher.get("outcome") != "pass":
        raise LabError(f"candidate {identifier}.teacher.outcome must be pass")
    floor_outcome = need_text(
        floor.get("outcome"), f"candidate {identifier}.floor.outcome", 40
    )
    if floor_outcome not in FLOOR_OUTCOMES:
        raise LabError(
            f"candidate {identifier}.floor.outcome must be one of {sorted(FLOOR_OUTCOMES)}"
        )
    artifacts = sorted(
        {
            need_text(item, f"candidate {identifier}.suggested_artifacts", 60)
            for item in need_array(
                row.get("suggested_artifacts", []),
                f"candidate {identifier}.suggested_artifacts",
            )
        }
    )
    unknown = sorted(set(artifacts) - ARTIFACT_TYPES)
    if unknown:
        raise LabError(f"candidate {identifier} has unknown artifact types: {unknown}")
    return {
        "id": identifier,
        "task_family": safe_id(
            row.get("task_family"), f"candidate {identifier}.task_family"
        ),
        "claim": need_text(row.get("claim"), f"candidate {identifier}.claim", 2000),
        "teacher": {
            "model_id": need_text(
                teacher.get("model_id"), f"candidate {identifier}.teacher.model_id", 200
            ),
            "source_access": _source_access(
                teacher.get("source_access"),
                f"candidate {identifier}.teacher.source_access",
            ),
            "outcome": "pass",
            "cost_usd_per_job": need_number(
                teacher.get("cost_usd_per_job", 0),
                f"candidate {identifier}.teacher.cost_usd_per_job",
            ),
            "operator_minutes_per_job": need_number(
                teacher.get("operator_minutes_per_job", 0),
                f"candidate {identifier}.teacher.operator_minutes_per_job",
            ),
        },
        "floor": {
            "model_id": need_text(
                floor.get("model_id"), f"candidate {identifier}.floor.model_id", 200
            ),
            "outcome": floor_outcome,
            "attempts": need_integer(
                floor.get("attempts", 0), f"candidate {identifier}.floor.attempts"
            ),
            "cost_usd_per_job": need_number(
                floor.get("cost_usd_per_job", 0),
                f"candidate {identifier}.floor.cost_usd_per_job",
            ),
            "operator_minutes_per_job": need_number(
                floor.get("operator_minutes_per_job", 0),
                f"candidate {identifier}.floor.operator_minutes_per_job",
            ),
        },
        "recurrence": {
            "jobs_per_month": need_integer(
                recurrence.get("jobs_per_month"),
                f"candidate {identifier}.recurrence.jobs_per_month",
                1,
            ),
        },
        "evidence": {
            "task_fingerprint": digest(
                evidence.get("task_fingerprint"),
                f"candidate {identifier}.evidence.task_fingerprint",
            ),
            "teacher_receipt_sha256": digest(
                evidence.get("teacher_receipt_sha256"),
                f"candidate {identifier}.evidence.teacher_receipt_sha256",
            ),
            "floor_receipt_sha256": digest(
                evidence.get("floor_receipt_sha256"),
                f"candidate {identifier}.evidence.floor_receipt_sha256",
            ),
            "grader_sha256": digest(
                evidence.get("grader_sha256"),
                f"candidate {identifier}.evidence.grader_sha256",
            ),
            "source_packet_sha256": digest(
                evidence.get("source_packet_sha256"),
                f"candidate {identifier}.evidence.source_packet_sha256",
            ),
        },
        "suggested_artifacts": artifacts,
        "capture_cost_estimate_usd": optional_number(
            row.get("capture_cost_estimate_usd"),
            f"candidate {identifier}.capture_cost_estimate_usd",
        ),
        "capture_operator_minutes_estimate": optional_number(
            row.get("capture_operator_minutes_estimate"),
            f"candidate {identifier}.capture_operator_minutes_estimate",
        ),
    }


def validate_lab(raw: Any) -> dict[str, Any]:
    lab = need_object(raw, "lab")
    if lab.get("schema") != LAB_SCHEMA:
        raise LabError(f"lab.schema must be {LAB_SCHEMA}")
    identifier = safe_id(lab.get("id"), "lab.id")
    student_raw = need_object(lab.get("student"), "lab.student")
    policy = need_object(lab.get("policy", {}), "lab.policy")
    candidates = [
        _candidate(item, index)
        for index, item in enumerate(
            need_array(lab.get("candidates"), "lab.candidates", nonempty=True)
        )
    ]
    identifiers = [item["id"] for item in candidates]
    if len(identifiers) != len(set(identifiers)):
        raise LabError("candidate ids must be unique")
    return {
        "schema": LAB_SCHEMA,
        "id": identifier,
        "title": need_text(lab.get("title", identifier), "lab.title", 200),
        "student": {
            "model_id": need_text(
                student_raw.get("model_id"), "lab.student.model_id", 200
            ),
            "source_access": _source_access(
                student_raw.get("source_access"), "lab.student.source_access"
            ),
            "trainable": need_boolean(
                student_raw.get("trainable", False), "lab.student.trainable"
            ),
            "cost_usd_per_job": need_number(
                student_raw.get("cost_usd_per_job", 0),
                "lab.student.cost_usd_per_job",
            ),
            "operator_minutes_per_job": need_number(
                student_raw.get("operator_minutes_per_job", 0),
                "lab.student.operator_minutes_per_job",
            ),
        },
        "policy": {
            "min_distinct_replays": need_integer(
                policy.get("min_distinct_replays", 3),
                "lab.policy.min_distinct_replays",
                1,
                1000,
            ),
            "minimize_before_variants": need_boolean(
                policy.get("minimize_before_variants", True),
                "lab.policy.minimize_before_variants",
            ),
            "promotion_authority": need_text(
                policy.get("promotion_authority", "capture_ledger"),
                "lab.policy.promotion_authority",
                100,
            ),
            "failure_default": need_text(
                policy.get("failure_default", "open"),
                "lab.policy.failure_default",
                100,
            ),
        },
        "candidates": candidates,
    }
