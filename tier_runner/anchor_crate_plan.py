"""Deterministic DAG compilation and backend placement for Anchor Crates."""
from __future__ import annotations

import copy
from typing import Any

from .anchor_crate_common import (
    FLOOR_SCHEMA,
    PLAN_SCHEMA,
    AnchorError,
    canonical_bytes,
    hash_json,
)
from .anchor_crate_schema import validate_backend_registry, validate_cartridge, validate_floor


def _semantic_floor(floor: dict[str, Any]) -> dict[str, Any]:
    """Project the floor into its ABI and constitutional semantics.

    Human-facing titles, prose, notes, and community supplier suggestions are excluded so an
    editorial revision does not invalidate a portable task. Authority, node semantics,
    protocol, placement law, and required seams remain identity-bearing.
    """
    return {
        "schema": floor["schema"],
        "id": floor["id"],
        "authority": floor["authority"],
        "node_kinds": [
            {
                "id": row["id"],
                "semantic_class": row["semantic_class"],
                "authority_ceiling": row["authority_ceiling"],
                "cacheable": row["cacheable"],
            }
            for row in floor["node_kinds"]
        ],
        "operations": floor["operations"],
        "executor_protocol": floor["executor_protocol"],
        "placement_policy": floor["placement_policy"],
        "required_seams": floor["required_seams"],
    }


def _semantic_cartridge(cartridge: dict[str, Any]) -> dict[str, Any]:
    """Project a cartridge into backend-neutral task semantics."""
    return {
        "schema": cartridge["schema"],
        "id": cartridge["id"],
        "task_family": cartridge["task_family"],
        "objective": cartridge["objective"],
        "non_goals": cartridge["non_goals"],
        "invariants": cartridge["invariants"],
        "input_payload": cartridge["input_payload"],
        "budgets": cartridge["budgets"],
        "nodes": [
            {
                key: value
                for key, value in node.items()
                if key != "backend_preferences"
            }
            for node in cartridge["nodes"]
        ],
        "validators": [
            {
                "id": row["id"],
                "kind": row["kind"],
                "operation": row["operation"],
                "controller_owned": row["controller_owned"],
                "hidden": row["hidden"],
            }
            for row in cartridge["validators"]
        ],
        "acceptance": cartridge["acceptance"],
        "required_seams": cartridge["required_seams"],
    }


def _network_admissible(requested: str, available: str) -> bool:
    order = {"none": 0, "local_only": 1, "declared_remote": 2}
    return order[available] >= order[requested]


def _eligible(node: dict[str, Any], backend: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    missing = sorted(set(node["required_capabilities"]) - set(backend["capabilities"]))
    if missing:
        reasons.append(f"missing capabilities {missing}")
    if node["operation"] not in backend["lowerings"]:
        reasons.append(f"no lowering for {node['operation']}")
    if node["resources"]["memory_mib"] > backend["memory_mib"]:
        reasons.append("single-backend memory floor not met")
    if node["resources"]["storage_mib"] > backend["storage_mib"]:
        reasons.append("single-backend storage floor not met")
    if not _network_admissible(node["resources"]["network"], backend["network"]):
        reasons.append("network policy not met")
    requested_power = node["resources"]["max_power_w"]
    if requested_power is not None:
        backend_power = backend["power_limit_w"]
        if backend_power is None or backend_power > requested_power:
            reasons.append("backend power envelope exceeds node limit")
    if node["effects"] not in backend["effects"]:
        reasons.append(f"effect {node['effects']} not supported")
    return not reasons, reasons


def _choose_backend(
    node: dict[str, Any],
    backends: dict[str, dict[str, Any]],
    override: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    assessments = []
    eligible = []
    for backend in backends.values():
        admitted, reasons = _eligible(node, backend)
        assessments.append(
            {
                "backend_id": backend["id"],
                "admitted": admitted,
                "reasons": reasons,
                "physical_qualification": backend["physical_qualification"],
            }
        )
        if admitted:
            eligible.append(backend)
    if override is not None:
        if override not in backends:
            raise AnchorError(f"node {node['id']} binding references unknown backend {override}")
        backend = backends[override]
        admitted, reasons = _eligible(node, backend)
        if not admitted:
            raise AnchorError(
                f"node {node['id']} cannot bind {override}: " + "; ".join(reasons)
            )
        return backend, sorted(assessments, key=lambda item: item["backend_id"])
    if not eligible:
        raise AnchorError(f"node {node['id']} has no admissible backend")

    preference_rank = {
        backend_id: index for index, backend_id in enumerate(node["backend_preferences"])
    }

    def key(backend: dict[str, Any]) -> tuple[int, int, int, str]:
        explicit = preference_rank.get(backend["id"], len(preference_rank) + 1)
        return (explicit, backend["preference"], backend["energy_class"], backend["id"])

    return min(eligible, key=key), sorted(assessments, key=lambda item: item["backend_id"])


def compile_plan(
    raw_floor: Any,
    raw_cartridge: Any,
    raw_registry: Any,
    *,
    bindings: dict[str, str] | None = None,
) -> dict[str, Any]:
    floor = validate_floor(raw_floor)
    cartridge = validate_cartridge(raw_cartridge)
    registry = validate_backend_registry(raw_registry)
    backends = {row["id"]: row for row in registry["backends"]}
    bindings = dict(bindings or {})
    unknown_binding_nodes = sorted(set(bindings) - {row["id"] for row in cartridge["nodes"]})
    if unknown_binding_nodes:
        raise AnchorError(f"bindings reference unknown nodes: {unknown_binding_nodes}")

    operation_contracts = {row["id"]: row for row in floor["operations"]}
    for node in cartridge["nodes"]:
        if node["operation"] not in operation_contracts:
            raise AnchorError(
                f"node {node['id']} references operation outside the floor: {node['operation']}"
            )
        contract = operation_contracts[node["operation"]]
        if node["semantic_class"] != contract["semantic_class"]:
            raise AnchorError(f"node {node['id']} semantic class differs from operation contract")
        if node["output_schema"] != contract["output_schema"]:
            raise AnchorError(f"node {node['id']} output schema differs from operation contract")

    floor_sha256 = hash_json(floor)
    cartridge_sha256 = hash_json(cartridge)
    backend_registry_sha256 = hash_json(registry)
    floor_contract_sha256 = hash_json(_semantic_floor(floor))
    semantic_cartridge_sha256 = hash_json(_semantic_cartridge(cartridge))
    portable_task_body = {
        "abi": FLOOR_SCHEMA,
        "floor_id": floor["id"],
        "floor_contract_sha256": floor_contract_sha256,
        "semantic_cartridge_sha256": semantic_cartridge_sha256,
        "task_family": cartridge["task_family"],
        "objective": cartridge["objective"],
        "required_seams": cartridge["required_seams"],
    }
    portable_task_id = f"anchortask1_{hash_json(portable_task_body)}"

    semantic_ids: dict[str, str] = {}
    planned_nodes = []
    for position, node in enumerate(cartridge["nodes"]):
        dependency_semantics = [semantic_ids[item] for item in node["depends_on"]]
        semantic_node = copy.deepcopy(node)
        semantic_node.pop("backend_preferences", None)
        semantic_body = {
            "portable_task_id": portable_task_id,
            "node": semantic_node,
            "dependency_semantic_ids": dependency_semantics,
        }
        node_semantic_id = f"anchornode1_{hash_json(semantic_body)}"
        semantic_ids[node["id"]] = node_semantic_id

        backend, assessments = _choose_backend(node, backends, bindings.get(node["id"]))
        backend_manifest_sha256 = hash_json(backend)
        lowering_sha256 = backend["lowerings"][node["operation"]]
        execution_body = {
            "node_semantic_id": node_semantic_id,
            "backend_id": backend["id"],
            "backend_manifest_sha256": backend_manifest_sha256,
            "lowering_sha256": lowering_sha256,
            "runtime_id": backend["runtime_id"],
            "runtime_version": backend["runtime_version"],
            "model_identity": backend["model_identity"],
            "execution_cartridge_id": backend["execution_cartridge_id"],
            "execution_cartridge_sha256": backend["execution_cartridge_sha256"],
            "toolchain_sha256": backend["toolchain_sha256"],
        }
        planned_nodes.append(
            {
                "position": position,
                "node_id": node["id"],
                "node_semantic_id": node_semantic_id,
                "execution_id": f"anchorexec1_{hash_json(execution_body)}",
                "kind": node["kind"],
                "semantic_class": node["semantic_class"],
                "operation": node["operation"],
                "depends_on": node["depends_on"],
                "required_capabilities": node["required_capabilities"],
                "input_refs": node["input_refs"],
                "output_schema": node["output_schema"],
                "validators": node["validators"],
                "cacheable": node["cacheable"],
                "effects": node["effects"],
                "resources": node["resources"],
                "stop_condition": node["stop_condition"],
                "backend": {
                    "id": backend["id"],
                    "manifest_sha256": backend_manifest_sha256,
                    "driver_command": backend["driver_command"],
                    "architecture": backend["architecture"],
                    "isa": backend["isa"],
                    "runtime_id": backend["runtime_id"],
                    "runtime_version": backend["runtime_version"],
                    "model_identity": backend["model_identity"],
                    "execution_cartridge_id": backend["execution_cartridge_id"],
                    "execution_cartridge_sha256": backend["execution_cartridge_sha256"],
                    "toolchain_sha256": backend["toolchain_sha256"],
                    "lowering_sha256": lowering_sha256,
                    "physical_qualification": backend["physical_qualification"],
                    "power_limit_w": backend["power_limit_w"],
                    "memory_mib": backend["memory_mib"],
                },
                "backend_assessments": assessments,
            }
        )

    body = {
        "schema": PLAN_SCHEMA,
        "floor_id": floor["id"],
        "floor_sha256": floor_sha256,
        "floor_contract_sha256": floor_contract_sha256,
        "cartridge_id": cartridge["id"],
        "cartridge_sha256": cartridge_sha256,
        "semantic_cartridge_sha256": semantic_cartridge_sha256,
        "backend_registry_id": registry["id"],
        "backend_registry_sha256": backend_registry_sha256,
        "portable_task_id": portable_task_id,
        "nodes": planned_nodes,
        "acceptance": cartridge["acceptance"],
        "budgets": cartridge["budgets"],
        "required_seams": sorted(set(floor["required_seams"]) | set(cartridge["required_seams"])),
        "bindings": {item["node_id"]: item["backend"]["id"] for item in planned_nodes},
        "claims": {
            "pooled_memory": False,
            "backend_neutral_task_identity": True,
            "production": False,
            "promotion_authorized": False,
        },
    }
    return {"plan_id": f"anchorplan1_{hash_json(body)}", **body}


def verify_plan(
    raw_floor: Any,
    raw_cartridge: Any,
    raw_registry: Any,
    candidate: Any,
    *,
    bindings: dict[str, str] | None = None,
) -> list[str]:
    expected = compile_plan(raw_floor, raw_cartridge, raw_registry, bindings=bindings)
    if not isinstance(candidate, dict):
        return ["plan must be an object"]
    if canonical_bytes(expected) == canonical_bytes(candidate):
        return []
    errors = []
    for key in (
        "schema",
        "plan_id",
        "portable_task_id",
        "floor_sha256",
        "floor_contract_sha256",
        "cartridge_sha256",
        "semantic_cartridge_sha256",
        "backend_registry_sha256",
        "nodes",
        "acceptance",
        "bindings",
        "claims",
    ):
        if candidate.get(key) != expected.get(key):
            errors.append(f"plan.{key} differs from deterministic compilation")
    return errors or ["plan differs from deterministic compilation"]


def compare_backend_bindings(
    raw_floor: Any,
    raw_cartridge: Any,
    raw_registry: Any,
    *,
    node_id: str,
    backend_a: str,
    backend_b: str,
) -> dict[str, Any]:
    first = compile_plan(
        raw_floor,
        raw_cartridge,
        raw_registry,
        bindings={node_id: backend_a},
    )
    second = compile_plan(
        raw_floor,
        raw_cartridge,
        raw_registry,
        bindings={node_id: backend_b},
    )
    first_node = next((row for row in first["nodes"] if row["node_id"] == node_id), None)
    second_node = next((row for row in second["nodes"] if row["node_id"] == node_id), None)
    if first_node is None or second_node is None:
        raise AnchorError(f"comparison node is unknown: {node_id}")
    body = {
        "schema": "tier-bench/anchor-backend-equivalence-plan@1",
        "node_id": node_id,
        "portable_task_id": first["portable_task_id"],
        "semantic_cartridge_sha256": first["semantic_cartridge_sha256"],
        "floor_contract_sha256": first["floor_contract_sha256"],
        "node_semantic_id": first_node["node_semantic_id"],
        "backend_a": {
            "id": backend_a,
            "plan_id": first["plan_id"],
            "execution_id": first_node["execution_id"],
            "architecture": first_node["backend"]["architecture"],
            "isa": first_node["backend"]["isa"],
            "model_identity": first_node["backend"]["model_identity"],
            "execution_cartridge_id": first_node["backend"]["execution_cartridge_id"],
            "execution_cartridge_sha256": first_node["backend"]["execution_cartridge_sha256"],
            "physical_qualification": first_node["backend"]["physical_qualification"],
        },
        "backend_b": {
            "id": backend_b,
            "plan_id": second["plan_id"],
            "execution_id": second_node["execution_id"],
            "architecture": second_node["backend"]["architecture"],
            "isa": second_node["backend"]["isa"],
            "model_identity": second_node["backend"]["model_identity"],
            "execution_cartridge_id": second_node["backend"]["execution_cartridge_id"],
            "execution_cartridge_sha256": second_node["backend"]["execution_cartridge_sha256"],
            "physical_qualification": second_node["backend"]["physical_qualification"],
        },
        "assertions": {
            "portable_task_identity_equal": first["portable_task_id"] == second["portable_task_id"],
            "semantic_node_identity_equal": first_node["node_semantic_id"] == second_node["node_semantic_id"],
            "execution_identity_distinct": first_node["execution_id"] != second_node["execution_id"],
            "plan_identity_distinct": first["plan_id"] != second["plan_id"],
            "acceptance_contract_equal": first["acceptance"] == second["acceptance"],
            "model_identity_equal": (
                first_node["backend"]["model_identity"]
                == second_node["backend"]["model_identity"]
            ),
            "execution_cartridge_distinct": (
                first_node["backend"]["execution_cartridge_sha256"]
                != second_node["backend"]["execution_cartridge_sha256"]
            ),
        },
        "claim_boundary": (
            "This proves deterministic plan-level portability across two declared ABI fixtures. "
            "It does not prove physical execution, performance, security, or production admission."
        ),
        "production_claim": False,
        "promotion_authorized": False,
    }
    if not all(body["assertions"].values()):
        raise AnchorError("backend comparison violated the portable identity contract")
    return {"comparison_id": f"anchorcompare1_{hash_json(body)}", **body}
