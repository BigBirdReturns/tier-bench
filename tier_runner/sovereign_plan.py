"""Attention-first scheduling and campaign compilation."""
from __future__ import annotations

import hashlib
from typing import Any

from .sovereign_common import (
    CAMPAIGN_SCHEMA,
    PLAN_SCHEMA,
    PlaneError,
    hash_json,
    now,
)
from .sovereign_context import pack_metrics, prefix_fingerprint
from .sovereign_schema import validate_manifest


def runtime_eligible(
    runtime: dict[str, Any], job: dict[str, Any], pack: dict[str, Any]
) -> bool:
    if job["privacy"] == "local_only" and runtime["execution_class"] != "local":
        return False
    if any(runtime["capabilities"].get(name) is not True for name in job["required_capabilities"]):
        return False
    metrics = pack_metrics(pack)
    required = metrics.selected_tokens + job["delta_tokens"] + job["expected_output_tokens"]
    return required <= runtime["context_limit_tokens"]


def eligible_runtimes(
    job: dict[str, Any],
    runtimes: dict[str, dict[str, Any]],
    packs: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    pack = packs[job["context_pack"]]
    rows = [
        runtimes[identifier]
        for identifier in job["runtime_candidates"]
        if runtime_eligible(runtimes[identifier], job, pack)
    ]
    if job["privacy"] == "sovereign_preferred":
        return [
            *[row for row in rows if row["execution_class"] == "local"],
            *[row for row in rows if row["execution_class"] != "local"],
        ]
    return rows


def choose_runtime(
    job: dict[str, Any],
    runtimes: dict[str, dict[str, Any]],
    packs: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    rows = eligible_runtimes(job, runtimes, packs)
    return rows[0] if rows else None


def group_key(runtime: dict[str, Any], pack: dict[str, Any]) -> tuple[str, str, str]:
    return runtime["resource"], runtime["id"], prefix_fingerprint(runtime, pack)


def _schedule(
    jobs: dict[str, dict[str, Any]],
    runtimes: dict[str, dict[str, Any]],
    packs: dict[str, dict[str, Any]],
) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], list[dict[str, Any]]]:
    pending = set(jobs)
    planned: set[str] = set()
    blocked_ids: set[str] = set()
    ordered: list[tuple[dict[str, Any], dict[str, Any]]] = []
    blocked: list[dict[str, Any]] = []
    sticky: tuple[str, str, str] | None = None

    while pending:
        changed = False
        for identifier in sorted(pending):
            failed = sorted(set(jobs[identifier]["depends_on"]) & blocked_ids)
            if failed:
                blocked.append(
                    {
                        "job_id": identifier,
                        "reason": "dependency blocked",
                        "blocked_by": failed,
                    }
                )
                pending.remove(identifier)
                blocked_ids.add(identifier)
                changed = True
                break
        if changed:
            continue

        ready = [
            jobs[identifier]
            for identifier in sorted(pending)
            if set(jobs[identifier]["depends_on"]) <= planned
        ]
        if not ready:
            raise PlaneError("no schedulable job remains despite an acyclic dependency graph")

        eligible: list[
            tuple[dict[str, Any], dict[str, Any], tuple[str, str, str]]
        ] = []
        for job in ready:
            runtime = choose_runtime(job, runtimes, packs)
            if runtime is None:
                blocked.append(
                    {
                        "job_id": job["id"],
                        "reason": (
                            "no declared runtime satisfies privacy, capability, and context limits"
                        ),
                        "blocked_by": [],
                    }
                )
                pending.remove(job["id"])
                blocked_ids.add(job["id"])
                changed = True
                break
            eligible.append((job, runtime, group_key(runtime, packs[job["context_pack"]])))
        if changed:
            continue

        same = [row for row in eligible if row[2] == sticky] if sticky else []
        if same:
            chosen = sorted(same, key=lambda row: (-row[0]["priority"], row[0]["id"]))[0]
        else:
            grouped: dict[
                tuple[str, str, str],
                list[tuple[dict[str, Any], dict[str, Any], tuple[str, str, str]]],
            ] = {}
            for row in eligible:
                grouped.setdefault(row[2], []).append(row)

            def score(
                item: tuple[
                    tuple[str, str, str],
                    list[tuple[dict[str, Any], dict[str, Any], tuple[str, str, str]]],
                ]
            ) -> tuple[int, int, str]:
                key, rows = item
                priority = sum(row[0]["priority"] for row in rows)
                reusable = sum(
                    pack_metrics(packs[row[0]["context_pack"]]).cacheable_tokens for row in rows
                )
                return -priority, -reusable, "|".join(key)

            sticky, rows = sorted(grouped.items(), key=score)[0]
            chosen = sorted(rows, key=lambda row: (-row[0]["priority"], row[0]["id"]))[0]

        job, runtime, _ = chosen
        ordered.append((job, runtime))
        pending.remove(job["id"])
        planned.add(job["id"])
    return ordered, blocked


def _waves(
    ordered: list[tuple[dict[str, Any], dict[str, Any]]],
    resources: dict[str, dict[str, Any]],
    max_parallel: int,
) -> list[dict[str, Any]]:
    waves: list[dict[str, Any]] = []
    job_wave: dict[str, int] = {}
    for job, runtime in ordered:
        earliest = max((job_wave[dependency] + 1 for dependency in job["depends_on"]), default=0)
        index = earliest
        while True:
            if index == len(waves):
                waves.append({"index": index, "jobs": [], "resource_counts": {}})
            wave = waves[index]
            resource = runtime["resource"]
            capacity = resources[resource]["capacity"]
            if (
                len(wave["jobs"]) < max_parallel
                and int(wave["resource_counts"].get(resource, 0)) < capacity
            ):
                wave["jobs"].append(
                    {
                        "job_id": job["id"],
                        "runtime": runtime["id"],
                        "resource": resource,
                    }
                )
                wave["resource_counts"][resource] = int(
                    wave["resource_counts"].get(resource, 0)
                ) + 1
                job_wave[job["id"]] = index
                break
            index += 1
    for wave in waves:
        wave["resource_counts"] = dict(sorted(wave["resource_counts"].items()))
    return waves


def _cache_inventory(
    manifest: dict[str, Any],
    runtimes: dict[str, dict[str, Any]],
    packs: dict[str, dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in manifest["cache_inventory"]:
        runtime = runtimes[row["runtime_id"]]
        pack = packs[row["context_pack"]]
        expected = prefix_fingerprint(runtime, pack)
        metrics = pack_metrics(pack)
        if row["prefix_fingerprint"] != expected:
            raise PlaneError(
                f"cache inventory binding mismatch for {row['runtime_id']} / "
                f"{row['context_pack']}"
            )
        if row["tokens"] != metrics.cacheable_tokens:
            raise PlaneError(
                f"cache inventory token count mismatch for {row['runtime_id']} / "
                f"{row['context_pack']}"
            )
        if row["valid"]:
            result[(row["runtime_id"], expected)] = row
    return result


def compile_plan(raw: Any) -> dict[str, Any]:
    manifest = validate_manifest(raw)
    resources = {row["id"]: row for row in manifest["resources"]}
    runtimes = {row["id"]: row for row in manifest["runtimes"]}
    packs = {row["id"]: row for row in manifest["context_packs"]}
    jobs = {row["id"]: row for row in manifest["jobs"]}
    ordered, blocked = _schedule(jobs, runtimes, packs)
    inventory = _cache_inventory(manifest, runtimes, packs)
    warm = set(inventory)
    seen_in_plan: set[tuple[str, str]] = set()
    batches: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    last_runtime_by_resource: dict[str, str] = {}

    totals: dict[str, Any] = {
        "jobs_planned": 0,
        "jobs_blocked": len(blocked),
        "naive_estate_input_tokens": 0,
        "selected_input_tokens": 0,
        "prefill_compute_tokens": 0,
        "planned_cache_read_tokens": 0,
        "selection_avoided_tokens": 0,
        "planned_cache_avoided_tokens": 0,
        "total_avoided_input_compute_tokens": 0,
        "expected_output_tokens": 0,
        "runtime_load_seconds": 0.0,
    }

    for sequence, (job, runtime) in enumerate(ordered, 1):
        pack = packs[job["context_pack"]]
        metrics = pack_metrics(pack)
        prefix = prefix_fingerprint(runtime, pack)
        key = runtime["id"], prefix
        cache_supported = (
            runtime["capabilities"].get("prefix_cache") is True
            and runtime["cache"]["mode"] != "none"
        )
        if cache_supported and key in inventory:
            reuse_state = "observed_inventory"
            evidence = inventory[key].get("receipt_sha256")
        elif cache_supported and key in seen_in_plan:
            reuse_state = "planned_after_prior_job"
            evidence = None
        else:
            reuse_state = "miss"
            evidence = None
        cache_read = metrics.cacheable_tokens if reuse_state != "miss" else 0
        prefill = metrics.selected_tokens + job["delta_tokens"] - cache_read
        naive = metrics.source_tokens + job["delta_tokens"]
        selected = metrics.selected_tokens + job["delta_tokens"]
        selection_avoided = metrics.source_tokens - metrics.selected_tokens
        total_avoided = naive - prefill
        if cache_supported:
            warm.add(key)
            seen_in_plan.add(key)

        key_group = group_key(runtime, pack)
        batch_key = "|".join(key_group)
        if current is None or current["batch_key"] != batch_key:
            load_seconds = (
                runtime["load_cost_seconds"]
                if last_runtime_by_resource.get(runtime["resource"]) != runtime["id"]
                else 0.0
            )
            last_runtime_by_resource[runtime["resource"]] = runtime["id"]
            current = {
                "id": f"batch-{len(batches) + 1:03d}",
                "batch_key": batch_key,
                "resource": runtime["resource"],
                "runtime": runtime["id"],
                "model_id": runtime["model_id"],
                "context_pack": pack["id"],
                "pack_fingerprint": metrics.pack_fingerprint,
                "prefix_fingerprint": prefix,
                "cacheable_prefix_tokens": metrics.cacheable_tokens,
                "runtime_load_seconds": load_seconds,
                "jobs": [],
            }
            batches.append(current)
            totals["runtime_load_seconds"] += load_seconds

        current["jobs"].append(
            {
                "sequence": sequence,
                "job_id": job["id"],
                "title": job["title"],
                "priority": job["priority"],
                "depends_on": job["depends_on"],
                "acceptance_sha256": hashlib.sha256(
                    job["acceptance"].encode("utf-8")
                ).hexdigest(),
                "privacy": job["privacy"],
                "context_delivery": job["context_delivery"],
                "naive_estate_input_tokens": naive,
                "selected_input_tokens": selected,
                "prefill_compute_tokens": prefill,
                "planned_cache_read_tokens": cache_read,
                "planned_cache_reuse": reuse_state,
                "cache_receipt_sha256": evidence,
                "selection_avoided_tokens": selection_avoided,
                "planned_cache_avoided_tokens": cache_read,
                "total_avoided_input_compute_tokens": total_avoided,
                "expected_output_tokens": job["expected_output_tokens"],
            }
        )
        totals["jobs_planned"] += 1
        totals["naive_estate_input_tokens"] += naive
        totals["selected_input_tokens"] += selected
        totals["prefill_compute_tokens"] += prefill
        totals["planned_cache_read_tokens"] += cache_read
        totals["selection_avoided_tokens"] += selection_avoided
        totals["planned_cache_avoided_tokens"] += cache_read
        totals["total_avoided_input_compute_tokens"] += total_avoided
        totals["expected_output_tokens"] += job["expected_output_tokens"]

    for batch in batches:
        batch.pop("batch_key", None)
    denominator = totals["naive_estate_input_tokens"]
    totals["input_compute_avoidance_ratio"] = (
        round(totals["total_avoided_input_compute_tokens"] / denominator, 6)
        if denominator
        else 0.0
    )
    plan = {
        "schema": PLAN_SCHEMA,
        "plane_id": manifest["id"],
        "manifest_sha256": hash_json(manifest),
        "generated_at": now(),
        "optimization": manifest["optimization"],
        "authority": {
            "routing_order": "operator_declared_with_local_preference_when_requested",
            "cache_plan": "exact_model_tokenizer_runtime_quantization_and_prefix_hash",
            "cache_observation": "runtime_receipt_required_after_execution",
            "acceptance": "external_to_model",
            "failure_default": "blocked_or_unmeasured",
        },
        "waves": _waves(
            ordered,
            resources,
            int(manifest["optimization"]["max_parallel_jobs"]),
        ),
        "batches": batches,
        "blocked": blocked,
        "totals": totals,
    }
    plan["plan_sha256"] = hash_json(
        {key: value for key, value in plan.items() if key != "generated_at"}
    )
    return plan


def verify_plan(raw_manifest: Any, raw_plan: Any) -> list[str]:
    expected = compile_plan(raw_manifest)
    if not isinstance(raw_plan, dict):
        return ["plan must be an object"]
    errors: list[str] = []
    for key in (
        "schema",
        "plane_id",
        "manifest_sha256",
        "optimization",
        "authority",
        "waves",
        "batches",
        "blocked",
        "totals",
        "plan_sha256",
    ):
        if raw_plan.get(key) != expected.get(key):
            errors.append(f"plan.{key} does not match deterministic recompilation")
    return errors


def compile_campaigns(raw: Any) -> dict[str, Any]:
    """Compile each job into a draft Frontier Residue Refinery campaign."""
    manifest = validate_manifest(raw)
    runtimes = {row["id"]: row for row in manifest["runtimes"]}
    packs = {row["id"]: row for row in manifest["context_packs"]}
    campaigns: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for job in manifest["jobs"]:
        routes = []
        for runtime in eligible_runtimes(job, runtimes, packs):
            backend = runtime.get("backend")
            if backend is None:
                continue
            routes.append(
                {
                    "id": runtime["id"],
                    "label": runtime["model_id"],
                    "manifest": backend["manifest"],
                    "arm": backend["arm"],
                    "execution_class": runtime["execution_class"],
                    "source_access": runtime["source_access"],
                    "capability_basis": "unmeasured",
                    "estimated_max_cost_usd": backend["estimated_max_cost_usd"],
                    "resource_key": runtime["resource"],
                    "max_concurrency": 1,
                }
            )
        if not routes:
            blocked.append(
                {
                    "job_id": job["id"],
                    "reason": "no eligible runtime has a committed backend binding",
                }
            )
            continue
        pack = packs[job["context_pack"]]
        metrics = pack_metrics(pack)
        campaign = {
            "schema": CAMPAIGN_SCHEMA,
            "id": f"sdp-{manifest['id']}-{job['id']}"[:56],
            "title": job["title"],
            "mode": job["campaign"]["mode"],
            "k": job["campaign"]["k"],
            "max_trials_per_route": job["campaign"]["max_trials_per_route"],
            "queue_now": False,
            "task": {
                "task": (
                    job["task"]
                    + "\n\nSOVEREIGN CONTEXT CONTRACT\n"
                    + f"pack_id={pack['id']}\n"
                    + f"pack_fingerprint={metrics.pack_fingerprint}\n"
                    + f"delivery={job['context_delivery']}\n"
                    + "Use only the materialized, hash-bound pack supplied by the execution plane."
                ),
                "files": job["files"],
                "acceptance": job["acceptance"],
                "priority": job["priority"],
            },
            "policy": {
                "max_total_cost_usd": job["campaign"]["max_total_cost_usd"],
                "max_remote_trials": job["campaign"]["max_remote_trials"],
                "materialize_candidates": True,
            },
            "routes": routes,
            "sovereign_context": {
                "pack_id": pack["id"],
                "pack_fingerprint": metrics.pack_fingerprint,
                "source_identity": pack["source_identity"],
                "source_revision": pack["source_revision"],
                "selected_tokens": metrics.selected_tokens,
                "source_tokens": metrics.source_tokens,
            },
        }
        campaigns.append(campaign)
    return {
        "schema": "tier-bench/sovereign-campaign-bundle@1",
        "plane_id": manifest["id"],
        "manifest_sha256": hash_json(manifest),
        "campaigns": campaigns,
        "blocked": blocked,
    }
