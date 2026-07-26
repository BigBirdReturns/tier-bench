"""Manifest normalization for the Sovereign Desktop Execution Plane."""
from __future__ import annotations

from typing import Any

from .sovereign_common import (
    BLOCK_KINDS,
    BLOCK_STABILITIES,
    BLOCK_STABILITY_ORDER,
    CACHE_MODES,
    CACHE_TIERS,
    CAMPAIGN_MODES,
    EXECUTION_CLASSES,
    PLANE_SCHEMA,
    PRIVACY_POLICIES,
    RESOURCE_KINDS,
    SOURCE_ACCESS,
    PlaneError,
    need_array,
    need_boolean,
    need_digest,
    need_integer,
    need_number,
    need_object,
    need_text,
    normalize_scope,
    optional_number,
    optional_text,
    safe_id,
    unique_by_id,
)


def _capabilities(value: Any, label: str) -> dict[str, bool]:
    raw = need_object(value or {}, label)
    result: dict[str, bool] = {}
    for key, enabled in raw.items():
        name = safe_id(key, f"{label} capability")
        result[name] = need_boolean(enabled, f"{label}.{name}")
    return dict(sorted(result.items()))


def _resource(raw: Any, index: int) -> dict[str, Any]:
    row = need_object(raw, f"resources[{index}]")
    identifier = safe_id(row.get("id"), f"resources[{index}].id")
    kind = need_text(row.get("kind"), f"resource {identifier}.kind", limit=40)
    if kind not in RESOURCE_KINDS:
        raise PlaneError(f"resource {identifier}.kind must be one of {sorted(RESOURCE_KINDS)}")
    result: dict[str, Any] = {
        "id": identifier,
        "kind": kind,
        "capacity": need_integer(
            row.get("capacity", 1), f"resource {identifier}.capacity", 1, 128
        ),
        "roles": sorted(
            {
                safe_id(item, f"resource {identifier}.roles")
                for item in need_array(row.get("roles", []), f"resource {identifier}.roles")
            }
        ),
    }
    for key in ("memory_gib", "bandwidth_gbps", "storage_gib"):
        if key in row:
            result[key] = need_number(row[key], f"resource {identifier}.{key}")
    notes = optional_text(row.get("notes"), f"resource {identifier}.notes", limit=1000)
    if notes is not None:
        result["notes"] = notes
    return result


def _runtime(
    raw: Any, index: int, resources: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    row = need_object(raw, f"runtimes[{index}]")
    identifier = safe_id(row.get("id"), f"runtimes[{index}].id")
    resource = safe_id(row.get("resource"), f"runtime {identifier}.resource")
    if resource not in resources:
        raise PlaneError(f"runtime {identifier} references unknown resource {resource}")
    execution_class = need_text(
        row.get("execution_class"), f"runtime {identifier}.execution_class", limit=40
    )
    if execution_class not in EXECUTION_CLASSES:
        raise PlaneError(
            f"runtime {identifier}.execution_class must be one of {sorted(EXECUTION_CLASSES)}"
        )
    source_access = need_text(
        row.get("source_access", "unknown"), f"runtime {identifier}.source_access", limit=40
    )
    if source_access not in SOURCE_ACCESS:
        raise PlaneError(
            f"runtime {identifier}.source_access must be one of {sorted(SOURCE_ACCESS)}"
        )

    cache_raw = need_object(row.get("cache", {}), f"runtime {identifier}.cache")
    cache_mode = need_text(cache_raw.get("mode", "none"), f"runtime {identifier}.cache.mode")
    if cache_mode not in CACHE_MODES:
        raise PlaneError(
            f"runtime {identifier}.cache.mode must be one of {sorted(CACHE_MODES)}"
        )
    cache = {
        "mode": cache_mode,
        "persistent": need_boolean(
            cache_raw.get("persistent", cache_mode in {"persistent_slot", "external_kv"}),
            f"runtime {identifier}.cache.persistent",
        ),
    }
    if "slot_save_path" in cache_raw:
        cache["slot_save_path"] = need_text(
            cache_raw["slot_save_path"], f"runtime {identifier}.cache.slot_save_path", limit=1000
        )

    backend = None
    if row.get("backend") is not None:
        raw_backend = need_object(row["backend"], f"runtime {identifier}.backend")
        arm = need_text(raw_backend.get("arm", "arm_b"), f"runtime {identifier}.backend.arm")
        if arm not in {"arm_a", "arm_b", "arm_c"}:
            raise PlaneError(f"runtime {identifier}.backend.arm is invalid")
        backend = {
            "manifest": normalize_scope(
                raw_backend.get("manifest"), f"runtime {identifier}.backend.manifest"
            ),
            "arm": arm,
            "estimated_max_cost_usd": optional_number(
                raw_backend.get("estimated_max_cost_usd"),
                f"runtime {identifier}.backend.estimated_max_cost_usd",
            ),
        }

    return {
        "id": identifier,
        "model_id": need_text(row.get("model_id"), f"runtime {identifier}.model_id", limit=200),
        "tokenizer_id": need_text(
            row.get("tokenizer_id"), f"runtime {identifier}.tokenizer_id", limit=200
        ),
        "runtime_id": need_text(
            row.get("runtime_id"), f"runtime {identifier}.runtime_id", limit=200
        ),
        "runtime_version": need_text(
            row.get("runtime_version"), f"runtime {identifier}.runtime_version", limit=200
        ),
        "quantization": need_text(
            row.get("quantization", "provider-native"),
            f"runtime {identifier}.quantization",
            limit=100,
        ),
        "resource": resource,
        "execution_class": execution_class,
        "source_access": source_access,
        "context_limit_tokens": need_integer(
            row.get("context_limit_tokens"),
            f"runtime {identifier}.context_limit_tokens",
            1,
        ),
        "capabilities": _capabilities(
            row.get("capabilities", {}), f"runtime {identifier}.capabilities"
        ),
        "cache": cache,
        "backend": backend,
        "load_cost_seconds": need_number(
            row.get("load_cost_seconds", 0), f"runtime {identifier}.load_cost_seconds"
        ),
        "declared_order": need_integer(
            row.get("declared_order", index),
            f"runtime {identifier}.declared_order",
            0,
            10_000,
        ),
    }


def _compression(raw: Any, pack_id: str, block_id: str) -> dict[str, Any] | None:
    if raw is None:
        return None
    row = need_object(raw, f"context block {pack_id}/{block_id}.compression")
    return {
        "covers_sha256": need_digest(
            row.get("covers_sha256"),
            f"context block {pack_id}/{block_id}.compression.covers_sha256",
        ),
        "method": need_text(
            row.get("method"), f"context block {pack_id}/{block_id}.compression.method", limit=120
        ),
        "validator_sha256": need_digest(
            row.get("validator_sha256"),
            f"context block {pack_id}/{block_id}.compression.validator_sha256",
        ),
        "loss_policy": need_text(
            row.get("loss_policy"),
            f"context block {pack_id}/{block_id}.compression.loss_policy",
            limit=1000,
        ),
    }


def _block(raw: Any, pack_id: str, index: int) -> dict[str, Any]:
    row = need_object(raw, f"context pack {pack_id}.blocks[{index}]")
    identifier = safe_id(row.get("id"), f"context pack {pack_id}.blocks[{index}].id")
    stability = need_text(
        row.get("stability"), f"context block {pack_id}/{identifier}.stability", limit=30
    )
    if stability not in BLOCK_STABILITIES:
        raise PlaneError(
            f"context block {pack_id}/{identifier}.stability must be one of "
            f"{sorted(BLOCK_STABILITIES)}"
        )
    kind = need_text(
        row.get("kind", "source"), f"context block {pack_id}/{identifier}.kind", limit=30
    )
    if kind not in BLOCK_KINDS:
        raise PlaneError(
            f"context block {pack_id}/{identifier}.kind must be one of {sorted(BLOCK_KINDS)}"
        )
    content_path = (
        normalize_scope(
            row.get("content_path"), f"context block {pack_id}/{identifier}.content_path"
        )
        if row.get("content_path") is not None
        else None
    )
    compression = _compression(row.get("compression"), pack_id, identifier)
    if kind == "compaction" and compression is None:
        raise PlaneError(
            f"context block {pack_id}/{identifier} is a compaction and requires provenance"
        )
    return {
        "id": identifier,
        "kind": kind,
        "stability": stability,
        "sha256": need_digest(
            row.get("sha256"), f"context block {pack_id}/{identifier}.sha256"
        ),
        "tokens": need_integer(
            row.get("tokens"), f"context block {pack_id}/{identifier}.tokens"
        ),
        "source": need_text(
            row.get("source"), f"context block {pack_id}/{identifier}.source", limit=1000
        ),
        "content_path": content_path,
        "compression": compression,
    }


def _pack(raw: Any, index: int) -> dict[str, Any]:
    row = need_object(raw, f"context_packs[{index}]")
    identifier = safe_id(row.get("id"), f"context_packs[{index}].id")
    blocks = [
        _block(item, identifier, i)
        for i, item in enumerate(
            need_array(row.get("blocks"), f"context pack {identifier}.blocks", nonempty=True)
        )
    ]
    unique_by_id(blocks, f"context block in {identifier}")
    ranks = [BLOCK_STABILITY_ORDER[item["stability"]] for item in blocks]
    if ranks != sorted(ranks):
        raise PlaneError(
            f"context pack {identifier} must order stable prefix blocks before job and "
            "ephemeral blocks"
        )
    source_tokens = need_integer(
        row.get("source_tokens"), f"context pack {identifier}.source_tokens"
    )
    selected_tokens = sum(item["tokens"] for item in blocks)
    if source_tokens < selected_tokens:
        raise PlaneError(
            f"context pack {identifier}.source_tokens ({source_tokens}) is smaller than "
            f"selected block tokens ({selected_tokens})"
        )
    return {
        "id": identifier,
        "source_identity": need_text(
            row.get("source_identity"), f"context pack {identifier}.source_identity", limit=1000
        ),
        "source_revision": need_text(
            row.get("source_revision"), f"context pack {identifier}.source_revision", limit=200
        ),
        "source_tokens": source_tokens,
        "blocks": blocks,
    }


def _cache(raw: Any, index: int) -> dict[str, Any]:
    row = need_object(raw, f"cache_inventory[{index}]")
    tier = need_text(row.get("tier"), f"cache_inventory[{index}].tier", limit=20)
    if tier not in CACHE_TIERS:
        raise PlaneError(f"cache_inventory[{index}].tier must be one of {sorted(CACHE_TIERS)}")
    return {
        "runtime_id": safe_id(row.get("runtime_id"), f"cache_inventory[{index}].runtime_id"),
        "context_pack": safe_id(
            row.get("context_pack"), f"cache_inventory[{index}].context_pack"
        ),
        "prefix_fingerprint": need_digest(
            row.get("prefix_fingerprint"),
            f"cache_inventory[{index}].prefix_fingerprint",
        ),
        "tier": tier,
        "tokens": need_integer(row.get("tokens"), f"cache_inventory[{index}].tokens"),
        "valid": need_boolean(
            row.get("valid", True), f"cache_inventory[{index}].valid"
        ),
        "receipt_sha256": (
            need_digest(
                row.get("receipt_sha256"),
                f"cache_inventory[{index}].receipt_sha256",
            )
            if row.get("receipt_sha256") is not None
            else None
        ),
    }


def _job(
    raw: Any,
    index: int,
    packs: dict[str, dict[str, Any]],
    runtimes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    row = need_object(raw, f"jobs[{index}]")
    identifier = safe_id(row.get("id"), f"jobs[{index}].id")
    pack = safe_id(row.get("context_pack"), f"job {identifier}.context_pack")
    if pack not in packs:
        raise PlaneError(f"job {identifier} references unknown context pack {pack}")
    candidates = [
        safe_id(item, f"job {identifier}.runtime_candidates")
        for item in need_array(
            row.get("runtime_candidates"),
            f"job {identifier}.runtime_candidates",
            nonempty=True,
        )
    ]
    if len(candidates) != len(set(candidates)):
        raise PlaneError(f"job {identifier}.runtime_candidates contains duplicates")
    unknown = [item for item in candidates if item not in runtimes]
    if unknown:
        raise PlaneError(f"job {identifier} references unknown runtimes: {unknown}")
    privacy = need_text(row.get("privacy", "sovereign_preferred"), f"job {identifier}.privacy")
    if privacy not in PRIVACY_POLICIES:
        raise PlaneError(f"job {identifier}.privacy must be one of {sorted(PRIVACY_POLICIES)}")
    dependencies = sorted(
        {
            safe_id(item, f"job {identifier}.depends_on")
            for item in need_array(row.get("depends_on", []), f"job {identifier}.depends_on")
        }
    )
    if identifier in dependencies:
        raise PlaneError(f"job {identifier} cannot depend on itself")
    campaign_raw = need_object(row.get("campaign", {}), f"job {identifier}.campaign")
    campaign_mode = need_text(
        campaign_raw.get("mode", "local_first"), f"job {identifier}.campaign.mode"
    )
    if campaign_mode not in CAMPAIGN_MODES:
        raise PlaneError(
            f"job {identifier}.campaign.mode must be one of {sorted(CAMPAIGN_MODES)}"
        )
    return {
        "id": identifier,
        "title": need_text(row.get("title", identifier), f"job {identifier}.title", limit=200),
        "task": need_text(row.get("task"), f"job {identifier}.task", limit=12_000),
        "files": sorted(
            {
                normalize_scope(item, f"job {identifier}.files")
                for item in need_array(row.get("files"), f"job {identifier}.files", nonempty=True)
            }
        ),
        "context_pack": pack,
        "context_delivery": need_text(
            row.get("context_delivery", "prompt_prefix"),
            f"job {identifier}.context_delivery",
            limit=40,
        ),
        "runtime_candidates": candidates,
        "privacy": privacy,
        "required_capabilities": sorted(
            {
                safe_id(item, f"job {identifier}.required_capabilities")
                for item in need_array(
                    row.get("required_capabilities", []),
                    f"job {identifier}.required_capabilities",
                )
            }
        ),
        "priority": need_integer(row.get("priority", 50), f"job {identifier}.priority", 0, 100),
        "delta_tokens": need_integer(
            row.get("delta_tokens", 0), f"job {identifier}.delta_tokens"
        ),
        "expected_output_tokens": need_integer(
            row.get("expected_output_tokens", 0),
            f"job {identifier}.expected_output_tokens",
        ),
        "depends_on": dependencies,
        "acceptance": need_text(
            row.get("acceptance"), f"job {identifier}.acceptance", limit=8000
        ),
        "campaign": {
            "mode": campaign_mode,
            "k": need_integer(
                campaign_raw.get("k", 1), f"job {identifier}.campaign.k", 1, 10
            ),
            "max_trials_per_route": need_integer(
                campaign_raw.get("max_trials_per_route", 4),
                f"job {identifier}.campaign.max_trials_per_route",
                1,
                100,
            ),
            "max_total_cost_usd": optional_number(
                campaign_raw.get("max_total_cost_usd"),
                f"job {identifier}.campaign.max_total_cost_usd",
            ),
            "max_remote_trials": (
                need_integer(
                    campaign_raw.get("max_remote_trials"),
                    f"job {identifier}.campaign.max_remote_trials",
                    0,
                    10_000,
                )
                if campaign_raw.get("max_remote_trials") is not None
                else None
            ),
        },
    }


def _assert_acyclic(jobs: dict[str, dict[str, Any]]) -> None:
    state: dict[str, int] = {}

    def visit(identifier: str, trail: list[str]) -> None:
        marker = state.get(identifier, 0)
        if marker == 1:
            raise PlaneError(f"job dependency cycle: {' -> '.join([*trail, identifier])}")
        if marker == 2:
            return
        state[identifier] = 1
        for dependency in jobs[identifier]["depends_on"]:
            visit(dependency, [*trail, identifier])
        state[identifier] = 2

    for identifier in sorted(jobs):
        visit(identifier, [])


def validate_manifest(raw: Any) -> dict[str, Any]:
    """Normalize and validate a complete desktop plane manifest."""
    manifest = need_object(raw, "manifest")
    if manifest.get("schema") != PLANE_SCHEMA:
        raise PlaneError(f"manifest.schema must be {PLANE_SCHEMA}")
    identifier = safe_id(manifest.get("id"), "manifest.id")
    optimization = need_object(manifest.get("optimization", {}), "manifest.optimization")
    wall_clock = need_text(
        optimization.get("wall_clock", "secondary"),
        "optimization.wall_clock",
        limit=40,
    )
    if wall_clock not in {"primary", "secondary", "constraint_only"}:
        raise PlaneError("optimization.wall_clock must be primary, secondary, or constraint_only")

    resource_rows = [
        _resource(item, index)
        for index, item in enumerate(
            need_array(manifest.get("resources"), "resources", nonempty=True)
        )
    ]
    resources = unique_by_id(resource_rows, "resource")
    runtime_rows = [
        _runtime(item, index, resources)
        for index, item in enumerate(
            need_array(manifest.get("runtimes"), "runtimes", nonempty=True)
        )
    ]
    runtimes = unique_by_id(runtime_rows, "runtime")
    pack_rows = [
        _pack(item, index)
        for index, item in enumerate(
            need_array(manifest.get("context_packs"), "context_packs", nonempty=True)
        )
    ]
    packs = unique_by_id(pack_rows, "context pack")
    job_rows = [
        _job(item, index, packs, runtimes)
        for index, item in enumerate(need_array(manifest.get("jobs"), "jobs", nonempty=True))
    ]
    jobs = unique_by_id(job_rows, "job")
    for job in job_rows:
        missing = [dependency for dependency in job["depends_on"] if dependency not in jobs]
        if missing:
            raise PlaneError(f"job {job['id']} has unknown dependencies: {missing}")
    _assert_acyclic(jobs)

    cache_rows = [
        _cache(item, index)
        for index, item in enumerate(
            need_array(manifest.get("cache_inventory", []), "cache_inventory")
        )
    ]
    for cache in cache_rows:
        if cache["runtime_id"] not in runtimes:
            raise PlaneError(
                f"cache inventory references unknown runtime {cache['runtime_id']}"
            )
        if cache["context_pack"] not in packs:
            raise PlaneError(
                f"cache inventory references unknown context pack {cache['context_pack']}"
            )

    return {
        "schema": PLANE_SCHEMA,
        "id": identifier,
        "title": need_text(manifest.get("title", identifier), "manifest.title", limit=200),
        "optimization": {
            "primary": need_text(
                optimization.get("primary", "operator_attention"),
                "optimization.primary",
                limit=80,
            ),
            "wall_clock": wall_clock,
            "max_parallel_jobs": need_integer(
                optimization.get("max_parallel_jobs", 1),
                "optimization.max_parallel_jobs",
                1,
                64,
            ),
        },
        "resources": resource_rows,
        "runtimes": runtime_rows,
        "context_packs": pack_rows,
        "cache_inventory": cache_rows,
        "jobs": job_rows,
    }
