"""Compile a conditional-memory lab into paired, crossover-balanced work."""
from __future__ import annotations

from typing import Any

from .conditional_memory_common import MemoryLabError, hash_json
from .conditional_memory_schema import PLAN_SCHEMA, resolve_profile


def _seat_for(
    lab: dict[str, Any], *, arm_id: str, arm_index: int, seed_index: int
) -> dict[str, Any]:
    topology = lab["topology"]
    seats = topology["seats"]
    assignment = topology["assignment"]
    if assignment == "fixed":
        seat_id = topology["fixed_assignments"].get(arm_id)
        if seat_id is None:
            raise MemoryLabError(f"fixed assignment has no seat for arm {arm_id}")
        return next(seat for seat in seats if seat["id"] == seat_id)
    if assignment == "round_robin":
        return seats[(arm_index + seed_index) % len(seats)]
    # paired_crossover rotates both the control and every candidate across seats.
    # With two seats, adjacent arms in the matrix run on opposite cards per seed.
    return seats[(arm_index + seed_index) % len(seats)]


def _trial_id(lab_id: str, profile: str, arm_id: str, seed: int) -> str:
    return f"cmem/{lab_id}/{profile}/{arm_id}/seed-{seed}"


def _stages() -> list[dict[str, Any]]:
    return [
        {
            "id": "identity",
            "depends_on": [],
            "authority": "runtime_probe",
            "purpose": (
                "Resolve the declared GPU seat and reject identity drift before torch loads."
            ),
            "outputs": ["hardware_identity"],
            "acceptance": "declared UUID resolves and expected device name matches",
        },
        {
            "id": "data",
            "depends_on": ["identity"],
            "authority": "dataset_fingerprint",
            "purpose": "Materialize the frozen training and validation streams for this seed.",
            "outputs": ["dataset_fingerprint"],
            "acceptance": "all matched arms for a seed receive identical dataset bytes",
        },
        {
            "id": "train",
            "depends_on": ["data"],
            "authority": "declared_optimizer",
            "purpose": "Train the exact arm under the resolved profile and placement contract.",
            "outputs": ["checkpoint", "training_trace"],
            "acceptance": "planned step count completes without non-finite loss",
        },
        {
            "id": "evaluate",
            "depends_on": ["train"],
            "authority": "frozen_validation_stream",
            "purpose": "Evaluate quality on the same held validation bytes used by every arm.",
            "outputs": ["validation_metrics", "golden_logits"],
            "acceptance": "finite validation loss and deterministic golden-logit identity",
        },
        {
            "id": "profile",
            "depends_on": ["evaluate"],
            "authority": "target_runtime",
            "purpose": "Measure step latency, tokens per second, peak memory, and access topology.",
            "outputs": ["performance_metrics", "topology_ledger"],
            "acceptance": "profile contains declared warmup and measured steps",
        },
        {
            "id": "seal",
            "depends_on": ["profile"],
            "authority": "append_only_receipt",
            "purpose": "Bind lab, plan, source, hardware, data, checkpoint, and measurements.",
            "outputs": ["trial_receipt"],
            "acceptance": "receipt hash verifies and no previous attempt is overwritten",
        },
    ]


def compile_plan(raw: Any, profile: str | None = None) -> dict[str, Any]:
    lab = resolve_profile(raw, profile)
    if lab["topology"]["assignment"] == "paired_crossover" and len(lab["topology"]["seats"]) < 2:
        raise MemoryLabError("paired_crossover requires at least two declared seats")
    arms = lab["arms"]
    seeds = lab["training"]["seeds"]
    baseline_id = lab["promotion"]["baseline_arm"]
    baseline_index = next(index for index, arm in enumerate(arms) if arm["id"] == baseline_id)
    trials: list[dict[str, Any]] = []
    baseline_by_seed: dict[int, str] = {}
    for seed_index, seed in enumerate(seeds):
        baseline_by_seed[seed] = _trial_id(lab["id"], lab["profile"], baseline_id, seed)
        for arm_index, arm in enumerate(arms):
            seat = _seat_for(
                lab, arm_id=arm["id"], arm_index=arm_index, seed_index=seed_index
            )
            trial_id = _trial_id(lab["id"], lab["profile"], arm["id"], seed)
            trials.append(
                {
                    "id": trial_id,
                    "arm_id": arm["id"],
                    "architecture": arm["architecture"],
                    "role": arm["role"],
                    "seed": seed,
                    "seed_index": seed_index,
                    "seat": seat,
                    "pair_id": f"{lab['id']}:{lab['profile']}:seed-{seed}",
                    "paired_baseline_trial_id": (
                        None if arm["id"] == baseline_id else baseline_by_seed[seed]
                    ),
                    "arm": arm,
                    "dataset": lab["dataset"],
                    "training": lab["training"],
                    "measurement": lab["measurement"],
                    "stages": _stages(),
                }
            )
    # Preserve the matrix order by seed, then arm. It is intentional and is part of the hash.
    seat_counts: dict[str, dict[str, int]] = {
        arm["id"]: {seat["id"]: 0 for seat in lab["topology"]["seats"]} for arm in arms
    }
    for trial in trials:
        seat_counts[trial["arm_id"]][trial["seat"]["id"]] += 1
    plan = {
        "schema": PLAN_SCHEMA,
        "lab_id": lab["id"],
        "profile": lab["profile"],
        "lab_sha256": hash_json(lab),
        "authority": {
            "quality": "frozen_validation_stream",
            "hardware": "runtime_uuid_and_name",
            "performance": "target_runtime_measurement",
            "promotion": "conditional_memory_report_gates",
            "failure_default": lab["promotion"]["failure_default"],
        },
        "resolved": {
            "dataset": lab["dataset"],
            "model": lab["model"],
            "training": lab["training"],
            "measurement": lab["measurement"],
            "topology": lab["topology"],
            "promotion": lab["promotion"],
        },
        "arms": arms,
        "trials": trials,
        "pairing": {
            "baseline_arm": baseline_id,
            "baseline_arm_index": baseline_index,
            "seeds": seeds,
            "seat_counts": seat_counts,
        },
        "commands": {
            "run_seats": [
                {
                    "seat_id": seat["id"],
                    "argv": [
                        "tiermemory",
                        "run-seat",
                        "--lab",
                        "<lab.json>",
                        "--plan",
                        "<plan.json>",
                        "--seat",
                        seat["id"],
                        "--state-dir",
                        "<state-dir>",
                    ],
                }
                for seat in lab["topology"]["seats"]
            ],
            "report": [
                "tiermemory",
                "report",
                "--lab",
                "<lab.json>",
                "--plan",
                "<plan.json>",
                "--state-dir",
                "<state-dir>",
                "--out",
                "<report.json>",
            ],
        },
    }
    plan["plan_sha256"] = hash_json(plan)
    return plan


def verify_plan(raw_lab: Any, raw_plan: Any, profile: str | None = None) -> list[str]:
    expected = compile_plan(raw_lab, profile)
    if not isinstance(raw_plan, dict):
        return ["plan must be an object"]
    errors: list[str] = []
    for key in (
        "schema",
        "lab_id",
        "profile",
        "lab_sha256",
        "authority",
        "resolved",
        "arms",
        "trials",
        "pairing",
        "commands",
        "plan_sha256",
    ):
        if raw_plan.get(key) != expected.get(key):
            errors.append(f"plan.{key} does not match deterministic recompilation")
    return errors


def trial_by_id(plan: dict[str, Any], trial_id: str) -> dict[str, Any]:
    for trial in plan.get("trials", []):
        if trial.get("id") == trial_id:
            return trial
    raise MemoryLabError(f"plan has no trial {trial_id!r}")


def trials_for_seat(plan: dict[str, Any], seat_id: str) -> list[dict[str, Any]]:
    trials = [trial for trial in plan.get("trials", []) if trial["seat"]["id"] == seat_id]
    if not trials:
        known = sorted({trial["seat"]["id"] for trial in plan.get("trials", [])})
        raise MemoryLabError(f"plan has no trials for seat {seat_id!r}; known seats: {known}")
    return trials
