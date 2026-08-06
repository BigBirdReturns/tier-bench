"""Strict schemas for the HALO3 Cell Zero laboratory and model fingerprint contract."""
from __future__ import annotations

from typing import Any

from .halo3_cell_common import (
    FINGERPRINT_SCHEMA,
    LAB_SCHEMA,
    Halo3Error,
    exact_keys,
    id_list,
    need_array,
    need_boolean,
    need_integer,
    need_number,
    need_object,
    need_text,
    optional_text,
    safe_id,
    text_list,
    unique_by_id,
)

IDENTITY_MODES = {"provider_observational", "exact_open_weight", "deterministic_control"}
MODEL_ROLES = {"planner", "solver", "critic", "control"}
NODE_CLASSES = {"foundry", "halo3", "evidence", "head", "foreign", "passive"}
NODE_STATES = {"declared", "observed", "qualified", "unavailable"}
STAGE_KINDS = {"foundry", "fingerprint", "physical", "fault", "reconciliation", "replay"}
CLAIM_CATEGORIES = {
    "preparation",
    "model",
    "cell",
    "integration",
    "survival",
    "continuity",
    "evidence",
}
FAULT_CLASSES = {"network", "power", "process", "state", "device", "cartridge", "human"}

MANDATORY_DIMENSIONS = {
    "identity",
    "capability",
    "disposition",
    "orchestration",
    "degradation",
    "thermodynamic",
    "affinity",
    "reproducibility",
}
MANDATORY_FAMILIES = {
    "cartridge-compilation",
    "physical-world-synthesis",
    "capability-composition",
    "foreign-system-adaptation",
    "attention-compilation",
    "degradation-recovery",
    "authority-discipline",
    "orchestration",
    "physical-closure",
}
MANDATORY_FINGERPRINT_METRICS = {
    "accepted",
    "consequential-miss",
    "critical-escaped-defects",
    "elapsed-ms",
    "external-bytes-in",
    "human-active-ms",
    "identity-confidence-ppm",
    "model-calls",
    "operator-interventions",
    "time-to-first-useful-ms",
    "wall-energy-mwh",
}
MANDATORY_LAB_METRICS = {
    "accepted-products",
    "consequential-misses",
    "elapsed-ms",
    "external-bytes-in",
    "gpu-energy-mwh",
    "human-active-ms",
    "manual-translations",
    "operator-interruptions",
    "recovery-ms",
    "role-seconds-served",
    "time-to-first-useful-ms",
    "wall-energy-mwh",
}
MANDATORY_STAGE_IDS = {
    "stage-000-foundry-compile",
    "stage-010-model-fingerprint",
    "stage-020-single-node",
    "stage-030-cell-union",
    "stage-040-halo3-enhancement",
    "stage-050-human-bind",
    "stage-060-partition",
    "stage-070-halo3-removal",
    "stage-080-head-loss",
    "stage-090-passive-sync",
    "stage-100-reconciliation",
    "stage-110-replay",
}
MANDATORY_MODEL_IDS = {"fable", "kimi3", "deterministic-control"}
MANDATORY_NODE_IDS = {
    "foundry-3090-a",
    "foundry-3090-b",
    "halo3-4060",
    "evidence-node",
    "head-a",
    "head-b",
    "head-c",
    "foreign-a",
    "passive-floor",
}


def _dimension(raw: Any, index: int) -> dict[str, Any]:
    row = need_object(raw, f"dimensions[{index}]")
    exact_keys(row, {"id", "title", "question"}, set(), f"dimensions[{index}]")
    return {
        "id": safe_id(row["id"], f"dimensions[{index}].id"),
        "title": need_text(row["title"], f"dimensions[{index}].title", limit=200),
        "question": need_text(row["question"], f"dimensions[{index}].question", limit=1000),
    }


def _family(raw: Any, index: int) -> dict[str, Any]:
    row = need_object(raw, f"families[{index}]")
    exact_keys(
        row,
        {
            "id",
            "title",
            "product",
            "hidden_acceptance",
            "negative_controls",
            "minimum_trials",
        },
        set(),
        f"families[{index}]",
    )
    identifier = safe_id(row["id"], f"families[{index}].id")
    return {
        "id": identifier,
        "title": need_text(row["title"], f"family {identifier}.title", limit=300),
        "product": need_text(row["product"], f"family {identifier}.product", limit=1000),
        "hidden_acceptance": need_text(
            row["hidden_acceptance"], f"family {identifier}.hidden_acceptance", limit=2000
        ),
        "negative_controls": text_list(
            row["negative_controls"], f"family {identifier}.negative_controls", nonempty=True
        ),
        "minimum_trials": need_integer(
            row["minimum_trials"], f"family {identifier}.minimum_trials", 1, 1000
        ),
    }


def _condition(raw: Any, index: int) -> dict[str, Any]:
    row = need_object(raw, f"conditions[{index}]")
    exact_keys(row, {"id", "title", "mutations"}, set(), f"conditions[{index}]")
    identifier = safe_id(row["id"], f"conditions[{index}].id")
    return {
        "id": identifier,
        "title": need_text(row["title"], f"condition {identifier}.title", limit=300),
        "mutations": text_list(
            row["mutations"], f"condition {identifier}.mutations", nonempty=True
        ),
    }


def validate_fingerprint_contract(raw: Any) -> dict[str, Any]:
    row = need_object(raw, "model fingerprint contract")
    exact_keys(
        row,
        {
            "schema",
            "id",
            "title",
            "dimensions",
            "families",
            "conditions",
            "required_metrics",
            "claim_boundary",
        },
        set(),
        "model fingerprint contract",
    )
    if row["schema"] != FINGERPRINT_SCHEMA:
        raise Halo3Error(f"fingerprint schema must be {FINGERPRINT_SCHEMA}")
    dimensions = [
        _dimension(item, index)
        for index, item in enumerate(
            need_array(row["dimensions"], "fingerprint dimensions", nonempty=True)
        )
    ]
    dimension_map = unique_by_id(dimensions, "fingerprint dimension")
    missing_dimensions = sorted(MANDATORY_DIMENSIONS - dimension_map.keys())
    if missing_dimensions:
        raise Halo3Error(f"fingerprint contract is missing dimensions: {missing_dimensions}")

    families = [
        _family(item, index)
        for index, item in enumerate(
            need_array(row["families"], "fingerprint families", nonempty=True)
        )
    ]
    family_map = unique_by_id(families, "fingerprint family")
    missing_families = sorted(MANDATORY_FAMILIES - family_map.keys())
    if missing_families:
        raise Halo3Error(f"fingerprint contract is missing families: {missing_families}")

    conditions = [
        _condition(item, index)
        for index, item in enumerate(
            need_array(row["conditions"], "fingerprint conditions", nonempty=True)
        )
    ]
    condition_map = unique_by_id(conditions, "fingerprint condition")
    if set(condition_map) != {"baseline", "degraded"}:
        raise Halo3Error("fingerprint conditions must be exactly baseline and degraded")

    metrics = id_list(row["required_metrics"], "fingerprint required_metrics", nonempty=True)
    missing_metrics = sorted(MANDATORY_FINGERPRINT_METRICS - set(metrics))
    if missing_metrics:
        raise Halo3Error(f"fingerprint contract is missing metrics: {missing_metrics}")

    return {
        "schema": FINGERPRINT_SCHEMA,
        "id": safe_id(row["id"], "fingerprint.id"),
        "title": need_text(row["title"], "fingerprint.title", limit=300),
        "dimensions": sorted(dimensions, key=lambda item: item["id"]),
        "families": sorted(families, key=lambda item: item["id"]),
        "conditions": sorted(conditions, key=lambda item: item["id"]),
        "required_metrics": metrics,
        "claim_boundary": need_text(
            row["claim_boundary"], "fingerprint.claim_boundary", limit=4000
        ),
    }


def _model(raw: Any, index: int) -> dict[str, Any]:
    row = need_object(raw, f"models[{index}]")
    exact_keys(
        row,
        {
            "id",
            "title",
            "identity_mode",
            "roles",
            "surface",
            "authority_ceiling",
            "required_identity_fields",
        },
        set(),
        f"models[{index}]",
    )
    identifier = safe_id(row["id"], f"models[{index}].id")
    identity_mode = need_text(row["identity_mode"], f"model {identifier}.identity_mode", limit=80)
    if identity_mode not in IDENTITY_MODES:
        raise Halo3Error(f"model {identifier}.identity_mode is invalid")
    roles = id_list(row["roles"], f"model {identifier}.roles", nonempty=True)
    if not set(roles) <= MODEL_ROLES:
        raise Halo3Error(f"model {identifier}.roles contains unknown roles")
    authority = need_text(
        row["authority_ceiling"], f"model {identifier}.authority_ceiling", limit=120
    )
    if authority != "candidate_only":
        raise Halo3Error(f"model {identifier} must remain candidate_only")
    identity_fields = id_list(
        row["required_identity_fields"],
        f"model {identifier}.required_identity_fields",
        nonempty=True,
    )
    return {
        "id": identifier,
        "title": need_text(row["title"], f"model {identifier}.title", limit=300),
        "identity_mode": identity_mode,
        "roles": roles,
        "surface": need_text(row["surface"], f"model {identifier}.surface", limit=500),
        "authority_ceiling": authority,
        "required_identity_fields": identity_fields,
    }


def _node(raw: Any, index: int) -> dict[str, Any]:
    row = need_object(raw, f"nodes[{index}]")
    exact_keys(
        row,
        {
            "id",
            "title",
            "class",
            "host_id",
            "failure_domain",
            "roles",
            "state",
            "physical_qualification",
            "receipt_refs",
            "survival_required",
        },
        set(),
        f"nodes[{index}]",
    )
    identifier = safe_id(row["id"], f"nodes[{index}].id")
    node_class = need_text(row["class"], f"node {identifier}.class", limit=80)
    if node_class not in NODE_CLASSES:
        raise Halo3Error(f"node {identifier}.class is invalid")
    state = need_text(row["state"], f"node {identifier}.state", limit=80)
    if state not in NODE_STATES:
        raise Halo3Error(f"node {identifier}.state is invalid")
    physical = need_boolean(
        row["physical_qualification"], f"node {identifier}.physical_qualification"
    )
    receipts = id_list(row["receipt_refs"], f"node {identifier}.receipt_refs")
    if physical and (state != "qualified" or not receipts):
        raise Halo3Error(
            f"node {identifier} cannot claim physical qualification without qualified state and receipts"
        )
    if state == "qualified" and not physical:
        raise Halo3Error(f"node {identifier} qualified state requires physical_qualification=true")
    return {
        "id": identifier,
        "title": need_text(row["title"], f"node {identifier}.title", limit=300),
        "class": node_class,
        "host_id": safe_id(row["host_id"], f"node {identifier}.host_id"),
        "failure_domain": safe_id(
            row["failure_domain"], f"node {identifier}.failure_domain", limit=300
        ),
        "roles": id_list(row["roles"], f"node {identifier}.roles", nonempty=True),
        "state": state,
        "physical_qualification": physical,
        "receipt_refs": receipts,
        "survival_required": need_boolean(
            row["survival_required"], f"node {identifier}.survival_required"
        ),
    }


def _stage(raw: Any, index: int) -> dict[str, Any]:
    row = need_object(raw, f"stages[{index}]")
    exact_keys(
        row,
        {
            "id",
            "sequence",
            "title",
            "kind",
            "intervention",
            "claim_ids",
            "required_nodes",
            "fault_ids",
            "acceptance",
        },
        set(),
        f"stages[{index}]",
    )
    identifier = safe_id(row["id"], f"stages[{index}].id")
    kind = need_text(row["kind"], f"stage {identifier}.kind", limit=80)
    if kind not in STAGE_KINDS:
        raise Halo3Error(f"stage {identifier}.kind is invalid")
    return {
        "id": identifier,
        "sequence": need_integer(row["sequence"], f"stage {identifier}.sequence", 0, 10000),
        "title": need_text(row["title"], f"stage {identifier}.title", limit=300),
        "kind": kind,
        "intervention": need_text(
            row["intervention"], f"stage {identifier}.intervention", limit=2000
        ),
        "claim_ids": id_list(row["claim_ids"], f"stage {identifier}.claim_ids", nonempty=True),
        "required_nodes": id_list(
            row["required_nodes"], f"stage {identifier}.required_nodes", nonempty=True
        ),
        "fault_ids": id_list(row["fault_ids"], f"stage {identifier}.fault_ids"),
        "acceptance": need_text(
            row["acceptance"], f"stage {identifier}.acceptance", limit=3000
        ),
    }


def _witness_token(value: Any, label: str) -> str:
    token = need_text(value, label, limit=300)
    if ":" not in token:
        raise Halo3Error(f"{label} must be a typed witness token")
    prefix, identifier = token.split(":", 1)
    if prefix not in {"node", "model", "human", "artifact", "passive"}:
        raise Halo3Error(f"{label} has unsupported witness type {prefix}")
    safe_id(identifier, label, limit=240)
    return f"{prefix}:{identifier}"


def _claim(raw: Any, index: int) -> dict[str, Any]:
    row = need_object(raw, f"claims[{index}]")
    exact_keys(
        row,
        {
            "id",
            "title",
            "category",
            "proof_stage",
            "minimal_witnesses",
            "negative_control",
            "subtraction_target",
            "required_receipts",
            "acceptance",
            "state",
        },
        set(),
        f"claims[{index}]",
    )
    identifier = safe_id(row["id"], f"claims[{index}].id")
    category = need_text(row["category"], f"claim {identifier}.category", limit=80)
    if category not in CLAIM_CATEGORIES:
        raise Halo3Error(f"claim {identifier}.category is invalid")
    witnesses = [
        _witness_token(item, f"claim {identifier}.minimal_witnesses[]")
        for item in need_array(
            row["minimal_witnesses"], f"claim {identifier}.minimal_witnesses", nonempty=True
        )
    ]
    if len(witnesses) != len(set(witnesses)):
        raise Halo3Error(f"claim {identifier}.minimal_witnesses contains duplicates")
    subtraction = _witness_token(row["subtraction_target"], f"claim {identifier}.subtraction_target")
    if subtraction not in witnesses:
        raise Halo3Error(f"claim {identifier}.subtraction_target must be in minimal_witnesses")
    state = need_text(row["state"], f"claim {identifier}.state", limit=80)
    if state not in {"declared", "measured", "accepted", "rejected", "held"}:
        raise Halo3Error(f"claim {identifier}.state is invalid")
    if state in {"measured", "accepted"}:
        raise Halo3Error(
            f"reference lab claim {identifier} cannot begin measured or accepted without observations"
        )
    return {
        "id": identifier,
        "title": need_text(row["title"], f"claim {identifier}.title", limit=300),
        "category": category,
        "proof_stage": safe_id(row["proof_stage"], f"claim {identifier}.proof_stage"),
        "minimal_witnesses": sorted(witnesses),
        "negative_control": need_text(
            row["negative_control"], f"claim {identifier}.negative_control", limit=2000
        ),
        "subtraction_target": subtraction,
        "required_receipts": id_list(
            row["required_receipts"], f"claim {identifier}.required_receipts", nonempty=True
        ),
        "acceptance": need_text(
            row["acceptance"], f"claim {identifier}.acceptance", limit=3000
        ),
        "state": state,
    }


def _fault(raw: Any, index: int) -> dict[str, Any]:
    row = need_object(raw, f"faults[{index}]")
    exact_keys(
        row,
        {"id", "title", "class", "target", "expected_loss", "retained_floor", "recovery"},
        set(),
        f"faults[{index}]",
    )
    identifier = safe_id(row["id"], f"faults[{index}].id")
    fault_class = need_text(row["class"], f"fault {identifier}.class", limit=80)
    if fault_class not in FAULT_CLASSES:
        raise Halo3Error(f"fault {identifier}.class is invalid")
    return {
        "id": identifier,
        "title": need_text(row["title"], f"fault {identifier}.title", limit=300),
        "class": fault_class,
        "target": _witness_token(row["target"], f"fault {identifier}.target"),
        "expected_loss": text_list(
            row["expected_loss"], f"fault {identifier}.expected_loss", nonempty=True
        ),
        "retained_floor": text_list(
            row["retained_floor"], f"fault {identifier}.retained_floor", nonempty=True
        ),
        "recovery": need_text(row["recovery"], f"fault {identifier}.recovery", limit=2000),
    }


def _validate_witness_refs(
    claims: list[dict[str, Any]],
    faults: list[dict[str, Any]],
    node_ids: set[str],
    model_ids: set[str],
) -> None:
    def check(token: str, label: str) -> None:
        prefix, identifier = token.split(":", 1)
        if prefix == "node" and identifier not in node_ids:
            raise Halo3Error(f"{label} references unknown node {identifier}")
        if prefix == "model" and identifier not in model_ids:
            raise Halo3Error(f"{label} references unknown model {identifier}")
        if prefix == "passive" and identifier != "floor":
            raise Halo3Error(f"{label} references unknown passive witness {identifier}")

    for claim in claims:
        for token in claim["minimal_witnesses"]:
            check(token, f"claim {claim['id']}")
        check(claim["subtraction_target"], f"claim {claim['id']}.subtraction_target")
    for fault in faults:
        check(fault["target"], f"fault {fault['id']}.target")


def validate_lab(raw: Any, raw_fingerprint: Any) -> dict[str, Any]:
    fingerprint = validate_fingerprint_contract(raw_fingerprint)
    row = need_object(raw, "HALO3 lab")
    exact_keys(
        row,
        {
            "schema",
            "id",
            "title",
            "claim",
            "authority",
            "models",
            "nodes",
            "stages",
            "claims",
            "faults",
            "required_metrics",
            "physical_boundary",
            "production_claim",
            "promotion_authorized",
        },
        {"notes"},
        "HALO3 lab",
    )
    if row["schema"] != LAB_SCHEMA:
        raise Halo3Error(f"lab schema must be {LAB_SCHEMA}")

    authority = need_object(row["authority"], "lab.authority")
    exact_keys(
        authority,
        {"controller_owns", "model_may", "human_owns", "forbidden"},
        set(),
        "lab.authority",
    )
    controller_owns = id_list(
        authority["controller_owns"], "lab.authority.controller_owns", nonempty=True
    )
    model_may = id_list(authority["model_may"], "lab.authority.model_may", nonempty=True)
    human_owns = id_list(
        authority["human_owns"], "lab.authority.human_owns", nonempty=True
    )
    forbidden = id_list(authority["forbidden"], "lab.authority.forbidden", nonempty=True)
    required_controller = {
        "acceptance",
        "artifact-hashing",
        "fault-admission",
        "hidden-grading",
        "model-identity-admission",
        "plan-compilation",
        "physical-outcome-reconciliation",
    }
    missing_controller = sorted(required_controller - set(controller_owns))
    if missing_controller:
        raise Halo3Error(f"controller authority is missing: {missing_controller}")
    required_forbidden = {
        "fixture-as-physical-evidence",
        "implicit-memory-pooling",
        "model-self-acceptance",
        "silent-state-rewrite",
        "undeclared-wan-dependency",
    }
    missing_forbidden = sorted(required_forbidden - set(forbidden))
    if missing_forbidden:
        raise Halo3Error(f"lab authority is missing refusals: {missing_forbidden}")
    if {"acceptance", "physical-outcome", "authority"} & set(model_may):
        raise Halo3Error("model permissions may not include acceptance, physical outcome, or authority")

    models = [
        _model(item, index)
        for index, item in enumerate(need_array(row["models"], "lab.models", nonempty=True))
    ]
    model_map = unique_by_id(models, "model")
    if set(model_map) != MANDATORY_MODEL_IDS:
        raise Halo3Error(f"lab models must be exactly {sorted(MANDATORY_MODEL_IDS)}")
    if model_map["fable"]["identity_mode"] != "provider_observational":
        raise Halo3Error("Fable identity must remain provider_observational")
    if model_map["kimi3"]["identity_mode"] != "exact_open_weight":
        raise Halo3Error("Kimi3 identity must remain exact_open_weight")
    if model_map["deterministic-control"]["identity_mode"] != "deterministic_control":
        raise Halo3Error("deterministic control identity mode is invalid")

    nodes = [
        _node(item, index)
        for index, item in enumerate(need_array(row["nodes"], "lab.nodes", nonempty=True))
    ]
    node_map = unique_by_id(nodes, "node")
    if set(node_map) != MANDATORY_NODE_IDS:
        raise Halo3Error(f"lab nodes must be exactly {sorted(MANDATORY_NODE_IDS)}")
    if node_map["evidence-node"]["survival_required"] is not True:
        raise Halo3Error("the evidence node must survive every run")
    if node_map["halo3-4060"]["survival_required"] is not False:
        raise Halo3Error("HALO3 must remain removable rather than required for survival")
    if any(node["physical_qualification"] for node in nodes):
        raise Halo3Error("reference lab topology is declared, not yet physically qualified")

    faults = [
        _fault(item, index)
        for index, item in enumerate(need_array(row["faults"], "lab.faults", nonempty=True))
    ]
    fault_map = unique_by_id(faults, "fault")

    claims = [
        _claim(item, index)
        for index, item in enumerate(need_array(row["claims"], "lab.claims", nonempty=True))
    ]
    claim_map = unique_by_id(claims, "claim")

    stages = [
        _stage(item, index)
        for index, item in enumerate(need_array(row["stages"], "lab.stages", nonempty=True))
    ]
    stage_map = unique_by_id(stages, "stage")
    if set(stage_map) != MANDATORY_STAGE_IDS:
        raise Halo3Error(f"lab stages must be exactly {sorted(MANDATORY_STAGE_IDS)}")
    ordered = sorted(stages, key=lambda item: item["sequence"])
    if [item["sequence"] for item in ordered] != list(range(len(ordered))):
        raise Halo3Error("lab stage sequences must be contiguous and start at zero")
    for stage in stages:
        unknown_claims = sorted(set(stage["claim_ids"]) - claim_map.keys())
        unknown_nodes = sorted(set(stage["required_nodes"]) - node_map.keys())
        unknown_faults = sorted(set(stage["fault_ids"]) - fault_map.keys())
        if unknown_claims:
            raise Halo3Error(f"stage {stage['id']} references unknown claims: {unknown_claims}")
        if unknown_nodes:
            raise Halo3Error(f"stage {stage['id']} references unknown nodes: {unknown_nodes}")
        if unknown_faults:
            raise Halo3Error(f"stage {stage['id']} references unknown faults: {unknown_faults}")
    for claim in claims:
        if claim["proof_stage"] not in stage_map:
            raise Halo3Error(f"claim {claim['id']} references unknown proof stage")
        if claim["id"] not in stage_map[claim["proof_stage"]]["claim_ids"]:
            raise Halo3Error(
                f"claim {claim['id']} and stage {claim['proof_stage']} must reference each other"
            )

    _validate_witness_refs(claims, faults, set(node_map), set(model_map))

    metrics = id_list(row["required_metrics"], "lab.required_metrics", nonempty=True)
    missing_metrics = sorted(MANDATORY_LAB_METRICS - set(metrics))
    if missing_metrics:
        raise Halo3Error(f"lab is missing required metrics: {missing_metrics}")
    if any("score" in item for item in metrics):
        raise Halo3Error("the HALO3 lab forbids aggregate score metrics")

    if need_boolean(row["production_claim"], "lab.production_claim"):
        raise Halo3Error("reference lab cannot claim production")
    if need_boolean(row["promotion_authorized"], "lab.promotion_authorized"):
        raise Halo3Error("reference lab cannot authorize promotion")

    result = {
        "schema": LAB_SCHEMA,
        "id": safe_id(row["id"], "lab.id"),
        "title": need_text(row["title"], "lab.title", limit=300),
        "claim": need_text(row["claim"], "lab.claim", limit=5000),
        "authority": {
            "controller_owns": controller_owns,
            "model_may": model_may,
            "human_owns": human_owns,
            "forbidden": forbidden,
        },
        "models": sorted(models, key=lambda item: item["id"]),
        "nodes": sorted(nodes, key=lambda item: item["id"]),
        "stages": ordered,
        "claims": sorted(claims, key=lambda item: item["id"]),
        "faults": sorted(faults, key=lambda item: item["id"]),
        "required_metrics": metrics,
        "physical_boundary": need_text(
            row["physical_boundary"], "lab.physical_boundary", limit=5000
        ),
        "fingerprint_contract_id": fingerprint["id"],
        "production_claim": False,
        "promotion_authorized": False,
    }
    notes = optional_text(row.get("notes"), "lab.notes", limit=5000)
    if notes is not None:
        result["notes"] = notes
    return result
