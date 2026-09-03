"""Strict schemas for the Community Home Lab Anchor Crate floor."""
from __future__ import annotations

from typing import Any

from .anchor_crate_common import (
    BACKEND_REGISTRY_SCHEMA,
    BACKEND_SCHEMA,
    CARTRIDGE_SCHEMA,
    FLOOR_SCHEMA,
    AnchorError,
    exact_keys,
    need_array,
    need_boolean,
    need_digest,
    need_integer,
    need_object,
    need_text,
    optional_text,
    safe_id,
    string_set,
    text_list,
    unique_by_id,
)

SEMANTIC_CLASSES = {"exact", "validator_equivalent", "human_disposition", "effect"}
NODE_KINDS = {
    "deterministic.transform",
    "candidate.generate",
    "human.disposition",
    "effect.apply",
    "verify.accept",
}
NETWORK_POLICIES = {"none", "local_only", "declared_remote"}
EXECUTION_CLASSES = {
    "host_process",
    "container",
    "remote_service",
    "accelerator_driver",
    "bare_metal_coprocessor",
}
ARCHITECTURES = {
    "x86_64",
    "arm64",
    "riscv64",
    "cuda-sm86",
    "cuda-sm89",
    "custom-accelerator",
    "fixture",
}
EFFECTS = {"none", "local_read", "local_write", "external_write", "device_control"}
DRIVER_OPERATIONS = {"describe", "probe", "execute", "cancel", "collect"}


def _node_kind(raw: Any, index: int) -> dict[str, Any]:
    row = need_object(raw, f"node_kinds[{index}]")
    exact_keys(
        row,
        {"id", "semantic_class", "authority_ceiling", "cacheable", "description"},
        set(),
        f"node_kinds[{index}]",
    )
    identifier = need_text(row["id"], f"node_kinds[{index}].id", limit=100)
    if identifier not in NODE_KINDS:
        raise AnchorError(f"node_kinds[{index}].id is not a recognized floor kind")
    semantic_class = need_text(
        row["semantic_class"], f"node_kinds[{index}].semantic_class", limit=80
    )
    if semantic_class not in SEMANTIC_CLASSES:
        raise AnchorError(f"node_kinds[{index}].semantic_class is invalid")
    return {
        "id": identifier,
        "semantic_class": semantic_class,
        "authority_ceiling": need_text(
            row["authority_ceiling"], f"node_kinds[{index}].authority_ceiling", limit=120
        ),
        "cacheable": need_boolean(row["cacheable"], f"node_kinds[{index}].cacheable"),
        "description": need_text(
            row["description"], f"node_kinds[{index}].description", limit=1000
        ),
    }


def _operation_contract(raw: Any, index: int) -> dict[str, Any]:
    row = need_object(raw, f"operations[{index}]")
    exact_keys(
        row,
        {
            "id",
            "semantic_class",
            "input_schema",
            "output_schema",
            "deterministic_output",
            "authority_ceiling",
        },
        set(),
        f"operations[{index}]",
    )
    semantic_class = need_text(
        row["semantic_class"], f"operations[{index}].semantic_class", limit=80
    )
    if semantic_class not in SEMANTIC_CLASSES:
        raise AnchorError(f"operations[{index}].semantic_class is invalid")
    deterministic = need_boolean(
        row["deterministic_output"], f"operations[{index}].deterministic_output"
    )
    if semantic_class == "exact" and not deterministic:
        raise AnchorError("exact operations must declare deterministic output")
    if semantic_class == "validator_equivalent" and deterministic:
        raise AnchorError("validator-equivalent operations must not claim byte determinism")
    return {
        "id": safe_id(row["id"], f"operations[{index}].id"),
        "semantic_class": semantic_class,
        "input_schema": safe_id(row["input_schema"], f"operations[{index}].input_schema"),
        "output_schema": safe_id(row["output_schema"], f"operations[{index}].output_schema"),
        "deterministic_output": deterministic,
        "authority_ceiling": need_text(
            row["authority_ceiling"], f"operations[{index}].authority_ceiling", limit=200
        ),
    }


def validate_floor(raw: Any) -> dict[str, Any]:
    row = need_object(raw, "anchor crate floor")
    exact_keys(
        row,
        {
            "schema",
            "id",
            "title",
            "claim",
            "authority",
            "node_kinds",
            "operations",
            "executor_protocol",
            "placement_policy",
            "required_seams",
            "commodity_bindings",
        },
        {"notes"},
        "anchor crate floor",
    )
    if row["schema"] != FLOOR_SCHEMA:
        raise AnchorError(f"floor.schema must be {FLOOR_SCHEMA}")

    authority = need_object(row["authority"], "authority")
    exact_keys(
        authority,
        {"controller_owns", "planner_may", "executor_may", "forbidden"},
        set(),
        "authority",
    )
    controller_owns = string_set(authority["controller_owns"], "authority.controller_owns", nonempty=True)
    planner_may = string_set(authority["planner_may"], "authority.planner_may", nonempty=True)
    executor_may = string_set(authority["executor_may"], "authority.executor_may", nonempty=True)
    forbidden = string_set(authority["forbidden"], "authority.forbidden", nonempty=True)
    mandatory_controller = {
        "acceptance",
        "anchor_hashing",
        "artifact_hashing",
        "backend_binding",
        "budget_enforcement",
        "crate_hashing",
        "dag_state",
        "effect_admission",
        "validator_execution",
    }
    missing = sorted(mandatory_controller - set(controller_owns))
    if missing:
        raise AnchorError(f"controller authority is missing mandatory custody: {missing}")
    if {"acceptance", "hashes", "hidden_validators"} & set(executor_may):
        raise AnchorError("executors may not own acceptance, hashes, or hidden validators")
    mandatory_forbidden = {
        "aggregate_memory_pooling",
        "backend_self_acceptance",
        "model_as_state_authority",
        "silent_backend_substitution",
    }
    if not mandatory_forbidden <= set(forbidden):
        raise AnchorError("floor must forbid pooling, self-acceptance, model state, and silent substitution")

    node_kinds = [
        _node_kind(item, index)
        for index, item in enumerate(need_array(row["node_kinds"], "node_kinds", nonempty=True))
    ]
    node_kind_map = unique_by_id(node_kinds, "node kind")
    if set(node_kind_map) != NODE_KINDS:
        raise AnchorError("floor must define the complete five-kind node vocabulary")

    operations = [
        _operation_contract(item, index)
        for index, item in enumerate(
            need_array(row["operations"], "operations", nonempty=True)
        )
    ]
    unique_by_id(operations, "operation")

    protocol = need_object(row["executor_protocol"], "executor_protocol")
    exact_keys(
        protocol,
        {"schema", "operations", "transport", "controller_injected_fields"},
        set(),
        "executor_protocol",
    )
    protocol_operations = string_set(
        protocol["operations"], "executor_protocol.operations", nonempty=True
    )
    if set(protocol_operations) != DRIVER_OPERATIONS:
        raise AnchorError("executor protocol must expose describe, probe, execute, cancel, and collect")
    injected = string_set(
        protocol["controller_injected_fields"],
        "executor_protocol.controller_injected_fields",
        nonempty=True,
    )
    required_injected = {
        "anchor_sha256",
        "backend_manifest_sha256",
        "crate_sha256",
        "input_artifact_sha256",
        "node_semantic_id",
        "plan_id",
        "remaining_budget",
    }
    if not required_injected <= set(injected):
        raise AnchorError("executor protocol omits controller-owned envelope fields")

    placement = need_object(row["placement_policy"], "placement_policy")
    exact_keys(
        placement,
        {
            "selection_order",
            "no_implicit_pooling",
            "fallback_creates_new_treatment",
            "wall_clock_policy",
            "energy_policy",
        },
        set(),
        "placement_policy",
    )
    if not need_boolean(placement["no_implicit_pooling"], "placement_policy.no_implicit_pooling"):
        raise AnchorError("placement must refuse implicit memory pooling")
    if not need_boolean(
        placement["fallback_creates_new_treatment"],
        "placement_policy.fallback_creates_new_treatment",
    ):
        raise AnchorError("fallback must create a new treatment identity")
    order = string_set(placement["selection_order"], "placement_policy.selection_order", nonempty=True)
    if order != sorted(order):
        # The list is semantically ordered. string_set sorts, so enforce the declared exact set below.
        pass
    required_order = {"backend_preference", "energy_class", "backend_id"}
    if set(order) != required_order:
        raise AnchorError("placement selection order must bind preference, energy class, and backend ID")

    seams = string_set(row["required_seams"], "required_seams", nonempty=True)
    required_seams = {
        "seam.capture",
        "seam.custody",
        "seam.degradation",
        "seam.disposition",
        "seam.identity",
        "seam.interpretation",
        "seam.outcome",
        "seam.resource-placement",
        "seam.selection",
        "seam.state-compilation",
        "seam.substitution",
    }
    missing_seams = sorted(required_seams - set(seams))
    if missing_seams:
        raise AnchorError(f"anchor crate floor is missing MENACE seams: {missing_seams}")

    bindings = need_object(row["commodity_bindings"], "commodity_bindings")
    normalized_bindings: dict[str, list[str]] = {}
    for role, suppliers in sorted(bindings.items()):
        normalized_bindings[safe_id(role, "commodity binding role")] = string_set(
            suppliers, f"commodity_bindings.{role}", nonempty=True
        )

    result = {
        "schema": FLOOR_SCHEMA,
        "id": safe_id(row["id"], "floor.id"),
        "title": need_text(row["title"], "floor.title", limit=300),
        "claim": need_text(row["claim"], "floor.claim", limit=5000),
        "authority": {
            "controller_owns": controller_owns,
            "planner_may": planner_may,
            "executor_may": executor_may,
            "forbidden": forbidden,
        },
        "node_kinds": node_kinds,
        "operations": operations,
        "executor_protocol": {
            "schema": need_text(protocol["schema"], "executor_protocol.schema", limit=120),
            "operations": protocol_operations,
            "transport": need_text(protocol["transport"], "executor_protocol.transport", limit=120),
            "controller_injected_fields": injected,
        },
        "placement_policy": {
            "selection_order": order,
            "no_implicit_pooling": True,
            "fallback_creates_new_treatment": True,
            "wall_clock_policy": need_text(
                placement["wall_clock_policy"], "placement_policy.wall_clock_policy", limit=500
            ),
            "energy_policy": need_text(
                placement["energy_policy"], "placement_policy.energy_policy", limit=500
            ),
        },
        "required_seams": seams,
        "commodity_bindings": normalized_bindings,
    }
    notes = optional_text(row.get("notes"), "floor.notes", limit=5000)
    if notes is not None:
        result["notes"] = notes
    return result


def _validator(raw: Any, index: int) -> dict[str, Any]:
    row = need_object(raw, f"validators[{index}]")
    exact_keys(
        row,
        {"id", "kind", "operation", "controller_owned", "hidden", "description"},
        set(),
        f"validators[{index}]",
    )
    if not need_boolean(row["controller_owned"], f"validators[{index}].controller_owned"):
        raise AnchorError("all cartridge validators must be controller-owned")
    return {
        "id": safe_id(row["id"], f"validators[{index}].id"),
        "kind": need_text(row["kind"], f"validators[{index}].kind", limit=80),
        "operation": safe_id(row["operation"], f"validators[{index}].operation"),
        "controller_owned": True,
        "hidden": need_boolean(row["hidden"], f"validators[{index}].hidden"),
        "description": need_text(
            row["description"], f"validators[{index}].description", limit=1000
        ),
    }


def _resource(raw: Any, node_id: str) -> dict[str, Any]:
    row = need_object(raw, f"node {node_id}.resources")
    exact_keys(
        row,
        {"memory_mib", "storage_mib", "network", "max_power_w"},
        set(),
        f"node {node_id}.resources",
    )
    network = need_text(row["network"], f"node {node_id}.resources.network", limit=40)
    if network not in NETWORK_POLICIES:
        raise AnchorError(f"node {node_id}.resources.network is invalid")
    power = row["max_power_w"]
    if power is not None:
        power = need_integer(power, f"node {node_id}.resources.max_power_w", 1, 100_000)
    return {
        "memory_mib": need_integer(
            row["memory_mib"], f"node {node_id}.resources.memory_mib", 0, 10_000_000
        ),
        "storage_mib": need_integer(
            row["storage_mib"], f"node {node_id}.resources.storage_mib", 0, 10_000_000
        ),
        "network": network,
        "max_power_w": power,
    }


def _node(raw: Any, index: int, validator_ids: set[str]) -> dict[str, Any]:
    row = need_object(raw, f"nodes[{index}]")
    exact_keys(
        row,
        {
            "id",
            "kind",
            "semantic_class",
            "operation",
            "depends_on",
            "required_capabilities",
            "input_refs",
            "output_schema",
            "validators",
            "cacheable",
            "effects",
            "resources",
            "stop_condition",
        },
        {"backend_preferences"},
        f"nodes[{index}]",
    )
    identifier = safe_id(row["id"], f"nodes[{index}].id")
    kind = need_text(row["kind"], f"node {identifier}.kind", limit=80)
    if kind not in NODE_KINDS:
        raise AnchorError(f"node {identifier}.kind is invalid")
    semantic_class = need_text(
        row["semantic_class"], f"node {identifier}.semantic_class", limit=80
    )
    if semantic_class not in SEMANTIC_CLASSES:
        raise AnchorError(f"node {identifier}.semantic_class is invalid")
    kind_class = {
        "deterministic.transform": "exact",
        "candidate.generate": "validator_equivalent",
        "human.disposition": "human_disposition",
        "effect.apply": "effect",
        "verify.accept": "exact",
    }[kind]
    if semantic_class != kind_class:
        raise AnchorError(f"node {identifier} kind requires semantic_class={kind_class}")
    effects = need_text(row["effects"], f"node {identifier}.effects", limit=40)
    if effects not in EFFECTS:
        raise AnchorError(f"node {identifier}.effects is invalid")
    if kind not in {"effect.apply", "human.disposition"} and effects not in {"none", "local_read"}:
        raise AnchorError(f"node {identifier} cannot carry write effects")
    validators = string_set(row["validators"], f"node {identifier}.validators")
    unknown_validators = sorted(set(validators) - validator_ids)
    if unknown_validators:
        raise AnchorError(f"node {identifier} references unknown validators: {unknown_validators}")
    if kind in {"candidate.generate", "verify.accept", "effect.apply"} and not validators:
        raise AnchorError(f"node {identifier} requires at least one controller validator")
    backend_preferences = string_set(
        row.get("backend_preferences", []), f"node {identifier}.backend_preferences"
    )
    return {
        "id": identifier,
        "kind": kind,
        "semantic_class": semantic_class,
        "operation": safe_id(row["operation"], f"node {identifier}.operation"),
        "depends_on": string_set(row["depends_on"], f"node {identifier}.depends_on"),
        "required_capabilities": string_set(
            row["required_capabilities"],
            f"node {identifier}.required_capabilities",
            nonempty=True,
        ),
        "input_refs": text_list(row["input_refs"], f"node {identifier}.input_refs", nonempty=True),
        "output_schema": safe_id(row["output_schema"], f"node {identifier}.output_schema"),
        "validators": validators,
        "cacheable": need_boolean(row["cacheable"], f"node {identifier}.cacheable"),
        "effects": effects,
        "resources": _resource(row["resources"], identifier),
        "stop_condition": need_text(
            row["stop_condition"], f"node {identifier}.stop_condition", limit=1000
        ),
        "backend_preferences": backend_preferences,
    }


def _assert_dag(nodes: dict[str, dict[str, Any]]) -> list[str]:
    for node in nodes.values():
        unknown = sorted(set(node["depends_on"]) - nodes.keys())
        if unknown:
            raise AnchorError(f"node {node['id']} has unknown dependencies: {unknown}")
        if node["id"] in node["depends_on"]:
            raise AnchorError(f"node {node['id']} cannot depend on itself")
    remaining = {identifier: set(row["depends_on"]) for identifier, row in nodes.items()}
    order: list[str] = []
    while remaining:
        ready = sorted(identifier for identifier, deps in remaining.items() if not deps)
        if not ready:
            raise AnchorError(f"cartridge DAG contains a cycle: {sorted(remaining)}")
        for identifier in ready:
            order.append(identifier)
            remaining.pop(identifier)
        for deps in remaining.values():
            deps.difference_update(ready)
    return order


def validate_cartridge(raw: Any) -> dict[str, Any]:
    row = need_object(raw, "anchor cartridge")
    exact_keys(
        row,
        {
            "schema",
            "id",
            "title",
            "task_family",
            "objective",
            "non_goals",
            "invariants",
            "input_payload",
            "budgets",
            "nodes",
            "validators",
            "acceptance",
            "required_seams",
        },
        {"notes"},
        "anchor cartridge",
    )
    if row["schema"] != CARTRIDGE_SCHEMA:
        raise AnchorError(f"cartridge.schema must be {CARTRIDGE_SCHEMA}")
    validators = [
        _validator(item, index)
        for index, item in enumerate(need_array(row["validators"], "validators", nonempty=True))
    ]
    validator_map = unique_by_id(validators, "validator")
    nodes = [
        _node(item, index, set(validator_map))
        for index, item in enumerate(need_array(row["nodes"], "nodes", nonempty=True))
    ]
    node_map = unique_by_id(nodes, "node")
    order = _assert_dag(node_map)

    budgets = need_object(row["budgets"], "budgets")
    exact_keys(
        budgets,
        {"max_nodes", "max_attempts_per_node", "max_wall_ms", "max_energy_mwh"},
        set(),
        "budgets",
    )
    if len(nodes) > need_integer(budgets["max_nodes"], "budgets.max_nodes", 1, 100_000):
        raise AnchorError("cartridge node count exceeds its own budget")

    acceptance = need_object(row["acceptance"], "acceptance")
    exact_keys(
        acceptance,
        {"final_node", "required_validators", "authority", "product_schema"},
        set(),
        "acceptance",
    )
    final_node = safe_id(acceptance["final_node"], "acceptance.final_node")
    if final_node not in node_map:
        raise AnchorError("acceptance.final_node is unknown")
    if node_map[final_node]["kind"] != "verify.accept":
        raise AnchorError("acceptance.final_node must be a verify.accept node")
    required_validators = string_set(
        acceptance["required_validators"], "acceptance.required_validators", nonempty=True
    )
    unknown = sorted(set(required_validators) - validator_map.keys())
    if unknown:
        raise AnchorError(f"acceptance references unknown validators: {unknown}")
    if acceptance["authority"] != "controller":
        raise AnchorError("only the deterministic controller may accept a cartridge result")

    seams = string_set(row["required_seams"], "required_seams", nonempty=True)
    mandatory = {
        "seam.custody",
        "seam.identity",
        "seam.interpretation",
        "seam.outcome",
        "seam.resource-placement",
        "seam.state-compilation",
        "seam.substitution",
    }
    if not mandatory <= set(seams):
        raise AnchorError(f"cartridge is missing mandatory seams: {sorted(mandatory - set(seams))}")

    result = {
        "schema": CARTRIDGE_SCHEMA,
        "id": safe_id(row["id"], "cartridge.id"),
        "title": need_text(row["title"], "cartridge.title", limit=300),
        "task_family": safe_id(row["task_family"], "cartridge.task_family"),
        "objective": need_text(row["objective"], "cartridge.objective", limit=5000),
        "non_goals": text_list(row["non_goals"], "cartridge.non_goals"),
        "invariants": text_list(row["invariants"], "cartridge.invariants", nonempty=True),
        "input_payload": need_object(row["input_payload"], "input_payload"),
        "budgets": {
            "max_nodes": need_integer(budgets["max_nodes"], "budgets.max_nodes", 1, 100_000),
            "max_attempts_per_node": need_integer(
                budgets["max_attempts_per_node"], "budgets.max_attempts_per_node", 1, 100
            ),
            "max_wall_ms": need_integer(
                budgets["max_wall_ms"], "budgets.max_wall_ms", 1, 10**12
            ),
            "max_energy_mwh": need_integer(
                budgets["max_energy_mwh"], "budgets.max_energy_mwh", 0, 10**15
            ),
        },
        "nodes": [node_map[identifier] for identifier in order],
        "validators": validators,
        "acceptance": {
            "final_node": final_node,
            "required_validators": required_validators,
            "authority": "controller",
            "product_schema": safe_id(
                acceptance["product_schema"], "acceptance.product_schema"
            ),
        },
        "required_seams": seams,
    }
    notes = optional_text(row.get("notes"), "cartridge.notes", limit=5000)
    if notes is not None:
        result["notes"] = notes
    return result


def _backend(raw: Any, index: int) -> dict[str, Any]:
    row = need_object(raw, f"backends[{index}]")
    exact_keys(
        row,
        {
            "schema",
            "id",
            "title",
            "execution_class",
            "architecture",
            "isa",
            "runtime_id",
            "runtime_version",
            "model_identity",
            "execution_cartridge_id",
            "execution_cartridge_sha256",
            "driver_command",
            "toolchain_sha256",
            "capabilities",
            "effects",
            "memory_mib",
            "storage_mib",
            "power_limit_w",
            "energy_class",
            "preference",
            "network",
            "telemetry",
            "physical_qualification",
            "model_formats",
            "lowerings",
        },
        {
            "notes",
            "backend_family",
            "ollama_vulkan",
            "cuda_visible_devices",
            "thermal_profile_id",
            "thermal_profile_receipt_sha256",
            "thermal_profile_public_receipt_sha256",
            "thermal_control_manifest_sha256",
            "fan_governance",
            "power_limit_target_watts",
            "fan_channels",
        },
        f"backends[{index}]",
    )
    if row["schema"] != BACKEND_SCHEMA:
        raise AnchorError(f"backends[{index}].schema must be {BACKEND_SCHEMA}")
    execution_class = need_text(
        row["execution_class"], f"backends[{index}].execution_class", limit=80
    )
    if execution_class not in EXECUTION_CLASSES:
        raise AnchorError(f"backends[{index}].execution_class is invalid")
    architecture = need_text(row["architecture"], f"backends[{index}].architecture", limit=80)
    if architecture not in ARCHITECTURES:
        raise AnchorError(f"backends[{index}].architecture is invalid")
    network = need_text(row["network"], f"backends[{index}].network", limit=40)
    if network not in NETWORK_POLICIES:
        raise AnchorError(f"backends[{index}].network is invalid")
    effects = string_set(row["effects"], f"backends[{index}].effects", nonempty=True)
    if not set(effects) <= EFFECTS:
        raise AnchorError(f"backends[{index}].effects contains unknown values")
    power = row["power_limit_w"]
    if power is not None:
        power = need_integer(power, f"backends[{index}].power_limit_w", 1, 100_000)
    telemetry = string_set(row["telemetry"], f"backends[{index}].telemetry", nonempty=True)
    required_telemetry = {"elapsed_ms", "memory_peak_mib", "status"}
    if not required_telemetry <= set(telemetry):
        raise AnchorError(f"backends[{index}] lacks basic telemetry")
    lowerings = need_object(row["lowerings"], f"backends[{index}].lowerings")
    normalized_lowerings = {
        safe_id(operation, f"backends[{index}].lowering operation"): need_digest(
            digest, f"backends[{index}].lowerings.{operation}"
        )
        for operation, digest in sorted(lowerings.items())
    }
    result = {
        "schema": BACKEND_SCHEMA,
        "id": safe_id(row["id"], f"backends[{index}].id"),
        "title": need_text(row["title"], f"backends[{index}].title", limit=300),
        "execution_class": execution_class,
        "architecture": architecture,
        "isa": need_text(row["isa"], f"backends[{index}].isa", limit=200),
        "runtime_id": need_text(row["runtime_id"], f"backends[{index}].runtime_id", limit=200),
        "runtime_version": need_text(
            row["runtime_version"], f"backends[{index}].runtime_version", limit=200
        ),
        "model_identity": need_text(
            row["model_identity"], f"backends[{index}].model_identity", limit=300
        ),
        "execution_cartridge_id": safe_id(
            row["execution_cartridge_id"], f"backends[{index}].execution_cartridge_id"
        ),
        "execution_cartridge_sha256": need_digest(
            row["execution_cartridge_sha256"],
            f"backends[{index}].execution_cartridge_sha256",
        ),
        "driver_command": text_list(
            row["driver_command"], f"backends[{index}].driver_command", nonempty=True
        ),
        "toolchain_sha256": need_digest(
            row["toolchain_sha256"], f"backends[{index}].toolchain_sha256"
        ),
        "capabilities": string_set(
            row["capabilities"], f"backends[{index}].capabilities", nonempty=True
        ),
        "effects": effects,
        "memory_mib": need_integer(
            row["memory_mib"], f"backends[{index}].memory_mib", 0, 10_000_000
        ),
        "storage_mib": need_integer(
            row["storage_mib"], f"backends[{index}].storage_mib", 0, 10_000_000
        ),
        "power_limit_w": power,
        "energy_class": need_integer(
            row["energy_class"], f"backends[{index}].energy_class", 0, 1_000_000
        ),
        "preference": need_integer(
            row["preference"], f"backends[{index}].preference", 0, 1_000_000
        ),
        "network": network,
        "telemetry": telemetry,
        "physical_qualification": need_boolean(
            row["physical_qualification"], f"backends[{index}].physical_qualification"
        ),
        "model_formats": string_set(
            row["model_formats"], f"backends[{index}].model_formats", nonempty=True
        ),
        "lowerings": normalized_lowerings,
    }
    if row.get("backend_family") is not None:
        result["backend_family"] = need_text(
            row["backend_family"], f"backends[{index}].backend_family", limit=80
        )
    if row.get("ollama_vulkan") is not None:
        result["ollama_vulkan"] = need_text(
            row["ollama_vulkan"], f"backends[{index}].ollama_vulkan", limit=40
        )
    if row.get("cuda_visible_devices") is not None:
        result["cuda_visible_devices"] = need_text(
            row["cuda_visible_devices"], f"backends[{index}].cuda_visible_devices", limit=200
        )
    if row.get("thermal_profile_id") is not None:
        result["thermal_profile_id"] = need_text(
            row["thermal_profile_id"], f"backends[{index}].thermal_profile_id", limit=200
        )
    if row.get("thermal_profile_receipt_sha256") is not None:
        result["thermal_profile_receipt_sha256"] = need_digest(
            row["thermal_profile_receipt_sha256"],
            f"backends[{index}].thermal_profile_receipt_sha256",
        )
    if row.get("thermal_profile_public_receipt_sha256") is not None:
        result["thermal_profile_public_receipt_sha256"] = need_digest(
            row["thermal_profile_public_receipt_sha256"],
            f"backends[{index}].thermal_profile_public_receipt_sha256",
        )
    if row.get("thermal_control_manifest_sha256") is not None:
        result["thermal_control_manifest_sha256"] = need_digest(
            row["thermal_control_manifest_sha256"],
            f"backends[{index}].thermal_control_manifest_sha256",
        )
    if row.get("fan_governance") is not None:
        result["fan_governance"] = need_text(
            row["fan_governance"], f"backends[{index}].fan_governance", limit=200
        )
    if row.get("power_limit_target_watts") is not None:
        power_target = row["power_limit_target_watts"]
        if not isinstance(power_target, (int, float)) or power_target <= 0:
            raise AnchorError(f"backends[{index}].power_limit_target_watts must be a positive number")
        result["power_limit_target_watts"] = int(power_target)
    if row.get("fan_channels") is not None:
        result["fan_channels"] = string_set(
            row["fan_channels"], f"backends[{index}].fan_channels", nonempty=True
        )
    notes = optional_text(row.get("notes"), f"backends[{index}].notes", limit=3000)
    if notes is not None:
        result["notes"] = notes
    return result


def validate_backend_registry(raw: Any) -> dict[str, Any]:
    row = need_object(raw, "backend registry")
    exact_keys(
        row,
        {"schema", "id", "title", "backends", "claim_boundary"},
        set(),
        "backend registry",
    )
    if row["schema"] != BACKEND_REGISTRY_SCHEMA:
        raise AnchorError(f"backend registry schema must be {BACKEND_REGISTRY_SCHEMA}")
    backends = [
        _backend(item, index)
        for index, item in enumerate(need_array(row["backends"], "backends", nonempty=True))
    ]
    unique_by_id(backends, "backend")
    if not any(item["architecture"] == "riscv64" for item in backends):
        raise AnchorError("reference registry must retain a RISC-V accelerator witness")
    if not any(item["architecture"] == "cuda-sm86" for item in backends):
        raise AnchorError("reference registry must retain the RTX 3090 CUDA route")
    return {
        "schema": BACKEND_REGISTRY_SCHEMA,
        "id": safe_id(row["id"], "backend registry.id"),
        "title": need_text(row["title"], "backend registry.title", limit=300),
        "claim_boundary": need_text(
            row["claim_boundary"], "backend registry.claim_boundary", limit=3000
        ),
        "backends": sorted(backends, key=lambda item: item["id"]),
    }
