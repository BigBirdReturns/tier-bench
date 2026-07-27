"""Receipt verification, paired analysis, and fail-closed promotion decisions."""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import statistics
from typing import Any, Iterable

from .conditional_memory_common import MemoryLabError, hash_json, load_json, without_hash
from .conditional_memory_plan import trial_by_id
from .conditional_memory_schema import RECEIPT_SCHEMA, REPORT_SCHEMA


def validate_receipt(receipt: Any, plan: dict[str, Any]) -> list[str]:
    if not isinstance(receipt, dict):
        return ["receipt must be an object"]
    errors: list[str] = []
    if receipt.get("schema") != RECEIPT_SCHEMA:
        errors.append(f"receipt.schema must be {RECEIPT_SCHEMA}")
    observed_hash = receipt.get("receipt_sha256")
    if observed_hash != hash_json(without_hash(receipt, "receipt_sha256")):
        errors.append("receipt.receipt_sha256 does not match canonical content")
    for key in ("lab_id", "profile", "lab_sha256", "plan_sha256"):
        expected = plan["lab_id"] if key == "lab_id" else plan[key]
        if receipt.get(key) != expected:
            errors.append(f"receipt.{key} does not match plan")
    try:
        trial = trial_by_id(plan, receipt.get("trial_id"))
    except MemoryLabError as exc:
        errors.append(str(exc))
        return errors
    for key in ("arm_id", "architecture", "seed", "seat", "pair_id", "paired_baseline_trial_id"):
        if receipt.get(key) != trial.get(key):
            errors.append(f"receipt.{key} does not match planned trial")
    if receipt.get("status") not in {"completed", "failed"}:
        errors.append("receipt.status must be completed or failed")
    if receipt.get("status") == "completed":
        evaluation = receipt.get("evaluation")
        performance = receipt.get("performance")
        model = receipt.get("model")
        data = receipt.get("data")
        if not isinstance(evaluation, dict) or not isinstance(
            evaluation.get("validation_loss"), (int, float)
        ):
            errors.append("completed receipt requires numeric evaluation.validation_loss")
        if not isinstance(performance, dict) or not isinstance(
            performance.get("step_time_ms"), dict
        ):
            errors.append("completed receipt requires performance.step_time_ms")
        if not isinstance(model, dict) or not isinstance(model.get("topology_ledger"), dict):
            errors.append("completed receipt requires model.topology_ledger")
        if not isinstance(data, dict) or not data.get("combined_sha256"):
            errors.append("completed receipt requires data.combined_sha256")
        if receipt.get("failure") is not None:
            errors.append("completed receipt cannot contain failure")
    else:
        if not isinstance(receipt.get("failure"), dict):
            errors.append("failed receipt requires failure object")
    return errors


def discover_receipts(state_dir: Path, plan: dict[str, Any]) -> list[tuple[Path, dict[str, Any]]]:
    result: list[tuple[Path, dict[str, Any]]] = []
    if not state_dir.exists():
        return result
    for path in sorted(state_dir.rglob("receipt.json")):
        try:
            receipt = load_json(path)
        except MemoryLabError:
            continue
        if isinstance(receipt, dict) and receipt.get("plan_sha256") == plan["plan_sha256"]:
            result.append((path, receipt))
    return result


def _select_attempts(
    discovered: Iterable[tuple[Path, dict[str, Any]]], plan: dict[str, Any]
) -> tuple[dict[str, tuple[Path, dict[str, Any]]], list[dict[str, Any]], list[str]]:
    grouped: dict[str, list[tuple[Path, dict[str, Any]]]] = defaultdict(list)
    invalid: list[dict[str, Any]] = []
    for path, receipt in discovered:
        errors = validate_receipt(receipt, plan)
        if errors:
            invalid.append({"path": str(path), "errors": errors})
            continue
        grouped[receipt["trial_id"]].append((path, receipt))
    selected: dict[str, tuple[Path, dict[str, Any]]] = {}
    duplicate_attempts: list[str] = []
    for trial_id, rows in grouped.items():
        by_attempt: dict[int, list[tuple[Path, dict[str, Any]]]] = defaultdict(list)
        for row in rows:
            by_attempt[int(row[1]["attempt"])].append(row)
        for attempt, same in by_attempt.items():
            if len(same) > 1:
                duplicate_attempts.append(f"{trial_id} attempt {attempt} appears more than once")
        completed = [row for row in rows if row[1]["status"] == "completed"]
        pool = completed or rows
        selected[trial_id] = min(pool, key=lambda row: (int(row[1]["attempt"]), str(row[0])))
    return selected, invalid, duplicate_attempts


def status_report(plan: dict[str, Any], state_dir: Path) -> dict[str, Any]:
    selected, invalid, duplicates = _select_attempts(discover_receipts(state_dir, plan), plan)
    completed = sorted(
        trial_id for trial_id, (_, receipt) in selected.items() if receipt["status"] == "completed"
    )
    failed = sorted(
        trial_id for trial_id, (_, receipt) in selected.items() if receipt["status"] == "failed"
    )
    planned = [trial["id"] for trial in plan["trials"]]
    missing = sorted(set(planned) - set(selected))
    return {
        "ok": not invalid and not duplicates and not failed and not missing,
        "plan_sha256": plan["plan_sha256"],
        "planned": len(planned),
        "completed": completed,
        "failed": failed,
        "missing": missing,
        "invalid": invalid,
        "duplicate_attempts": duplicates,
    }


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _paired_delta(candidate: float, baseline: float) -> float | None:
    if baseline == 0:
        return None
    return (candidate - baseline) / baseline


def _arm_summary(
    arm: dict[str, Any],
    receipts: list[dict[str, Any]],
    baseline_by_seed: dict[int, dict[str, Any]],
    plan: dict[str, Any],
    global_conflicts: list[str],
) -> dict[str, Any]:
    receipts = sorted(receipts, key=lambda row: row["seed"])
    validation = [float(row["evaluation"]["validation_loss"]) for row in receipts]
    p95 = [float(row["performance"]["step_time_ms"]["p95"]) for row in receipts]
    peak = [
        float(row["performance"]["peak_cuda_allocated_bytes"])
        for row in receipts
        if row["performance"].get("peak_cuda_allocated_bytes") is not None
    ]
    paired: list[dict[str, Any]] = []
    for receipt in receipts:
        baseline = baseline_by_seed.get(receipt["seed"])
        if baseline is None:
            continue
        loss_delta = _paired_delta(
            float(receipt["evaluation"]["validation_loss"]),
            float(baseline["evaluation"]["validation_loss"]),
        )
        latency_delta = _paired_delta(
            float(receipt["performance"]["step_time_ms"]["p95"]),
            float(baseline["performance"]["step_time_ms"]["p95"]),
        )
        candidate_peak = receipt["performance"].get("peak_cuda_allocated_bytes")
        baseline_peak = baseline["performance"].get("peak_cuda_allocated_bytes")
        memory_delta = (
            _paired_delta(float(candidate_peak), float(baseline_peak))
            if candidate_peak is not None and baseline_peak not in {None, 0}
            else None
        )
        paired.append(
            {
                "seed": receipt["seed"],
                "candidate_trial_id": receipt["trial_id"],
                "baseline_trial_id": baseline["trial_id"],
                "relative_validation_loss_change": loss_delta,
                "relative_validation_loss_improvement": (
                    -loss_delta if loss_delta is not None else None
                ),
                "relative_p95_step_time_change": latency_delta,
                "relative_peak_memory_change": memory_delta,
            }
        )
    quality = [
        row["relative_validation_loss_improvement"]
        for row in paired
        if row["relative_validation_loss_improvement"] is not None
    ]
    latency = [
        row["relative_p95_step_time_change"]
        for row in paired
        if row["relative_p95_step_time_change"] is not None
    ]
    memory = [
        row["relative_peak_memory_change"]
        for row in paired
        if row["relative_peak_memory_change"] is not None
    ]
    seat_counts = Counter(row["seat"]["id"] for row in receipts)
    planned_seats = [seat["id"] for seat in plan["resolved"]["topology"]["seats"]]
    seat_balance = all(seat_counts.get(seat, 0) > 0 for seat in planned_seats)
    if seat_counts:
        seat_balance = seat_balance and max(seat_counts.values()) - min(
            seat_counts.get(seat, 0) for seat in planned_seats
        ) <= 1
    checkpoint_identity = all(
        row["model"].get("final_state_sha256")
        and (
            not row["training"]["config"]["save_checkpoint"]
            or row["model"].get("checkpoint_sha256")
        )
        for row in receipts
    )
    policy = plan["resolved"]["promotion"]
    is_baseline = arm["id"] == policy["baseline_arm"]
    gates = {
        "complete_seed_count": len(paired) if not is_baseline else len(receipts),
        "minimum_complete_seeds": (
            len(paired) >= policy["min_complete_seeds"]
            if not is_baseline
            else len(receipts) >= policy["min_complete_seeds"]
        ),
        "quality": (
            True
            if is_baseline
            else bool(quality)
            and statistics.fmean(quality)
            >= policy["min_relative_validation_loss_improvement"]
        ),
        "latency": (
            True
            if is_baseline
            else bool(latency)
            and statistics.fmean(latency) <= policy["max_p95_step_time_regression"]
        ),
        "peak_memory": (
            True
            if is_baseline
            else bool(memory)
            and statistics.fmean(memory) <= policy["max_peak_memory_regression"]
        ),
        "seat_balance": seat_balance if policy["require_seat_balance"] else True,
        "checkpoint_identity": (
            checkpoint_identity if policy["require_checkpoint_identity"] else True
        ),
        "global_integrity": not global_conflicts,
    }
    gate_values = [value for key, value in gates.items() if key != "complete_seed_count"]
    decision = "control" if is_baseline else ("promote" if all(gate_values) else "hold")
    first_ledger = receipts[0]["model"]["topology_ledger"] if receipts else None
    ledger_consistent = len(
        {hash_json(row["model"]["topology_ledger"]) for row in receipts}
    ) <= 1
    if not ledger_consistent:
        gates["global_integrity"] = False
        if not is_baseline:
            decision = "hold"
    return {
        "arm_id": arm["id"],
        "architecture": arm["architecture"],
        "role": arm["role"],
        "completed_seeds": [row["seed"] for row in receipts],
        "seat_counts": dict(sorted(seat_counts.items())),
        "metrics": {
            "validation_loss_mean": _mean(validation),
            "validation_loss_stdev": statistics.stdev(validation) if len(validation) > 1 else 0.0,
            "p95_step_time_ms_mean": _mean(p95),
            "peak_cuda_allocated_bytes_mean": _mean(peak),
            "paired_relative_validation_loss_improvement_mean": _mean(quality),
            "paired_relative_p95_step_time_change_mean": _mean(latency),
            "paired_relative_peak_memory_change_mean": _mean(memory),
        },
        "paired": paired,
        "topology_ledger": first_ledger,
        "topology_ledger_consistent": ledger_consistent,
        "gates": gates,
        "decision": decision,
    }


def _pareto(arms: list[dict[str, Any]]) -> list[str]:
    candidates = [arm for arm in arms if arm["metrics"]["validation_loss_mean"] is not None]
    frontier: list[str] = []
    for candidate in candidates:
        c_loss = candidate["metrics"]["validation_loss_mean"]
        c_latency = candidate["metrics"]["p95_step_time_ms_mean"]
        c_memory = candidate["metrics"]["peak_cuda_allocated_bytes_mean"]
        dominated = False
        for other in candidates:
            if other is candidate:
                continue
            o_loss = other["metrics"]["validation_loss_mean"]
            o_latency = other["metrics"]["p95_step_time_ms_mean"]
            o_memory = other["metrics"]["peak_cuda_allocated_bytes_mean"]
            if None in {c_loss, c_latency, o_loss, o_latency}:
                continue
            memory_comparable = c_memory is not None and o_memory is not None
            no_worse = o_loss <= c_loss and o_latency <= c_latency
            strictly_better = o_loss < c_loss or o_latency < c_latency
            if memory_comparable:
                no_worse = no_worse and o_memory <= c_memory
                strictly_better = strictly_better or o_memory < c_memory
            if no_worse and strictly_better:
                dominated = True
                break
        if not dominated:
            frontier.append(candidate["arm_id"])
    return sorted(frontier)


def build_report(plan: dict[str, Any], state_dir: Path) -> dict[str, Any]:
    discovered = discover_receipts(state_dir, plan)
    selected, invalid, duplicate_attempts = _select_attempts(discovered, plan)
    planned_ids = {trial["id"] for trial in plan["trials"]}
    missing = sorted(planned_ids - set(selected))
    failed = sorted(
        trial_id for trial_id, (_, receipt) in selected.items() if receipt["status"] == "failed"
    )
    completed = {
        trial_id: receipt
        for trial_id, (_, receipt) in selected.items()
        if receipt["status"] == "completed"
    }
    conflicts: list[str] = []
    if missing:
        conflicts.append("one or more planned trials are missing")
    if failed:
        conflicts.append("one or more planned trials failed")
    if invalid:
        conflicts.append("one or more receipts fail canonical validation")
    if duplicate_attempts:
        conflicts.extend(duplicate_attempts)
    # Matched arms must see exactly the same train and validation bytes for each seed.
    for seed in plan["resolved"]["training"]["seeds"]:
        hashes = {
            receipt["data"]["combined_sha256"]
            for receipt in completed.values()
            if receipt["seed"] == seed
        }
        if len(hashes) > 1:
            conflicts.append(f"seed {seed} has mismatched dataset fingerprints")
    source_sets = {hash_json(receipt["source_hashes"]) for receipt in completed.values()}
    if len(source_sets) > 1:
        conflicts.append("selected receipts were produced by different module source bytes")
    service_gpu_uuids = {
        service["gpu"]["uuid"]
        for receipt in completed.values()
        for service in [receipt.get("seat_resolution", {}).get("service_gpu")]
        if isinstance(service, dict)
        and service.get("resolved")
        and isinstance(service.get("gpu"), dict)
        and service["gpu"].get("uuid")
    }
    if len(service_gpu_uuids) > 1:
        conflicts.append("selected receipts resolve different service GPU identities")
    baseline_id = plan["resolved"]["promotion"]["baseline_arm"]
    baseline_by_seed = {
        receipt["seed"]: receipt
        for receipt in completed.values()
        if receipt["arm_id"] == baseline_id
    }
    by_arm: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for receipt in completed.values():
        by_arm[receipt["arm_id"]].append(receipt)
    arm_summaries = [
        _arm_summary(arm, by_arm.get(arm["id"], []), baseline_by_seed, plan, conflicts)
        for arm in plan["arms"]
    ]
    report = {
        "schema": REPORT_SCHEMA,
        "lab_id": plan["lab_id"],
        "profile": plan["profile"],
        "lab_sha256": plan["lab_sha256"],
        "plan_sha256": plan["plan_sha256"],
        "authority": {
            "quality": "paired frozen validation loss by seed",
            "performance": "paired target-runtime p95 step time and peak CUDA allocation",
            "promotion": "all declared gates must pass; no automatic production routing",
            "failure_default": plan["resolved"]["promotion"]["failure_default"],
        },
        "status": {
            "ok": (
                not missing
                and not failed
                and not invalid
                and not duplicate_attempts
                and not conflicts
            ),
            "planned_trials": len(planned_ids),
            "completed_trials": len(completed),
            "failed_trials": failed,
            "missing_trials": missing,
            "invalid_receipts": invalid,
            "duplicate_attempts": duplicate_attempts,
            "integrity_conflicts": conflicts,
        },
        "arms": arm_summaries,
        "pareto_frontier": _pareto(arm_summaries),
        "promotable_arms": sorted(
            arm["arm_id"] for arm in arm_summaries if arm["decision"] == "promote"
        ),
        "promotion_authorized": False,
    }
    report["report_sha256"] = hash_json(report)
    return report
