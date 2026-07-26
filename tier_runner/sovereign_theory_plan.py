"""Compile deterministic, counterbalanced plans for the Sovereign Theory Lab."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .sovereign_common import PlaneError, hash_json, now
from .sovereign_theory_common import PLAN_SCHEMA, stable_label
from .sovereign_theory_schema import validate_lab


def _ready_tasks(lab: dict[str, Any], theory: dict[str, Any]) -> list[dict[str, Any]]:
    families = set(theory["task_families"])
    return sorted(
        [
            task
            for task in lab["tasks"]
            if task["status"] == "ready" and task["family"] in families
        ],
        key=lambda row: (row["family"], row["id"]),
    )


def _rotated_arm_order(theory: dict[str, Any], task_index: int, replicate: int) -> list[dict[str, Any]]:
    arms = list(theory["arms"])
    offset = (task_index + replicate - 1) % len(arms)
    rotated = arms[offset:] + arms[:offset]
    # Reverse alternating blocks so a three-arm study does not always preserve
    # the same neighbor relation even though first position is balanced.
    if ((task_index // max(1, len(arms))) + replicate) % 2:
        rotated = [rotated[0], *reversed(rotated[1:])]
    return rotated


def compile_plan(raw: Any, *, include: set[str] | None = None) -> dict[str, Any]:
    lab = validate_lab(raw)
    selected = [
        theory for theory in lab["theories"] if include is None or theory["id"] in include
    ]
    if include:
        missing = include - {theory["id"] for theory in selected}
        if missing:
            raise PlaneError(f"unknown theory ids: {sorted(missing)}")
    runs: list[dict[str, Any]] = []
    theories: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    position_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    sequence = 0

    for theory in selected:
        tasks = _ready_tasks(lab, theory)
        enough = len(tasks) >= theory["minimum_distinct_tasks"]
        if not tasks:
            blocked.append(
                {
                    "theory_id": theory["id"],
                    "reason": "no ready task matches the declared task families",
                    "required_distinct_tasks": theory["minimum_distinct_tasks"],
                    "ready_distinct_tasks": 0,
                }
            )
            theories.append(
                {
                    "theory_id": theory["id"],
                    "status": "blocked",
                    "ready_tasks": 0,
                    "required_tasks": theory["minimum_distinct_tasks"],
                    "planned_runs": 0,
                }
            )
            continue

        start = len(runs)
        for task_index, task in enumerate(tasks):
            for replicate in range(1, theory["replicates_per_cell"] + 1):
                order = _rotated_arm_order(theory, task_index, replicate)
                for position, arm in enumerate(order):
                    sequence += 1
                    position_counts[theory["id"]][f"{arm['id']}:{position}"] += 1
                    run_basis = {
                        "lab_id": lab["id"],
                        "theory_id": theory["id"],
                        "task_id": task["id"],
                        "arm_id": arm["id"],
                        "replicate": replicate,
                        "position": position,
                    }
                    run_hash = hash_json(run_basis)
                    runs.append(
                        {
                            "sequence": sequence,
                            "run_id": f"st-{run_hash[:16]}",
                            "blind_label": stable_label(
                                theory["id"],
                                task["id"],
                                arm["id"],
                                str(replicate),
                            ),
                            "theory_id": theory["id"],
                            "task_id": task["id"],
                            "task_family": task["family"],
                            "acceptance_class": task["acceptance_class"],
                            "replicate": replicate,
                            "position": position,
                            "arm_id": arm["id"],
                            "arm_role": arm["role"],
                            "settings": arm["settings"],
                            "resource_hints": arm["resource_hints"],
                            "required_metrics": [
                                metric["id"] for metric in lab["metrics"] if metric["required"]
                            ],
                            "receipt_required": True,
                            "runtime_attestation_required": True,
                        }
                    )
        theories.append(
            {
                "theory_id": theory["id"],
                "status": "ready" if enough else "calibration_only",
                "ready_tasks": len(tasks),
                "required_tasks": theory["minimum_distinct_tasks"],
                "replicates_per_cell": theory["replicates_per_cell"],
                "arms": [arm["id"] for arm in theory["arms"]],
                "planned_runs": len(runs) - start,
                "claim": theory["claim"],
                "prediction": theory["prediction"],
                "falsifier": theory["falsifier"],
            }
        )
        if not enough:
            blocked.append(
                {
                    "theory_id": theory["id"],
                    "reason": "ready tasks are sufficient for calibration but not settlement",
                    "required_distinct_tasks": theory["minimum_distinct_tasks"],
                    "ready_distinct_tasks": len(tasks),
                }
            )

    balance: dict[str, Any] = {}
    for theory in selected:
        counts = position_counts.get(theory["id"], {})
        by_arm: dict[str, list[int]] = defaultdict(list)
        for key, value in counts.items():
            arm_id, _ = key.rsplit(":", 1)
            by_arm[arm_id].append(value)
        arm_spread = {
            arm_id: (max(values) - min(values) if values else 0)
            for arm_id, values in by_arm.items()
        }
        balance[theory["id"]] = {
            "position_counts": dict(sorted(counts.items())),
            "max_position_imbalance": max(arm_spread.values(), default=0),
        }

    return {
        "schema": PLAN_SCHEMA,
        "lab_id": lab["id"],
        "lab_sha256": hash_json(lab),
        "generated_at": now(),
        "authority": {
            "task_selection": "only tasks marked ready before plan compilation",
            "arm_order": "deterministic rotation with alternating neighbor reversal",
            "acceptance": "external to the tested runtime",
            "runtime_identity": "attested observations only",
            "errors": "non-decisive",
            "failure_default": "PARTIAL or UNMEASURED",
        },
        "theories": theories,
        "runs": runs,
        "blocked": blocked,
        "balance": balance,
        "totals": {
            "theories_selected": len(selected),
            "theories_with_runs": sum(1 for row in theories if row["planned_runs"]),
            "runs": len(runs),
            "distinct_ready_tasks": len({run["task_id"] for run in runs}),
        },
    }


def verify_plan(raw: Any, plan: Any) -> list[str]:
    if not isinstance(plan, dict):
        return ["plan must be an object"]
    include = {
        row["theory_id"]
        for row in plan.get("theories", [])
        if isinstance(row, dict) and isinstance(row.get("theory_id"), str)
    }
    try:
        expected = compile_plan(raw, include=include or None)
    except PlaneError as exc:
        return [str(exc)]
    errors: list[str] = []
    if plan.get("schema") != PLAN_SCHEMA:
        errors.append("plan schema mismatch")
    if plan.get("lab_id") != expected["lab_id"]:
        errors.append("plan lab_id mismatch")
    if plan.get("lab_sha256") != expected["lab_sha256"]:
        errors.append("plan lab binding mismatch")
    for key in ("theories", "runs", "blocked", "balance", "totals", "authority"):
        if plan.get(key) != expected.get(key):
            errors.append(f"plan {key} differs from deterministic compilation")
    return errors


def observation_templates(raw: Any, plan: Any) -> list[dict[str, Any]]:
    lab = validate_lab(raw)
    errors = verify_plan(raw, plan)
    if errors:
        raise PlaneError("; ".join(errors))
    return [
        {
            "schema": "tier-bench/sovereign-theory-observation@1",
            "theory_id": run["theory_id"],
            "run_id": run["run_id"],
            "task_id": run["task_id"],
            "arm_id": run["arm_id"],
            "replicate": run["replicate"],
            "outcome": "partial",
            "runtime": {
                "requested": "UNBOUND",
                "observed": "UNBOUND",
                "attested": False,
                "telemetry_complete": False,
            },
            "metrics": {
                metric["id"]: False if metric["kind"] == "boolean" else 0
                for metric in lab["metrics"]
                if metric["required"]
            },
            "receipt_sha256": "0" * 64,
            "notes": "template only; replace with sealed observation",
        }
        for run in plan["runs"]
    ]
