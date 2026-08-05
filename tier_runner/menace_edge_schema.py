"""Strict campaign and observation validation for MENACE edge qualification."""
from __future__ import annotations

from typing import Any

from .menace_edge_common import (
    BASE_STREAM_ENVELOPE_FIELDS,
    MANIFEST_SCHEMA,
    MANDATORY_METRICS,
    MANDATORY_OUTCOMES,
    OBSERVATION_SCHEMA,
    EdgeError,
    exact_keys,
    need_array,
    need_boolean,
    need_digest,
    need_integer,
    need_object,
    need_text,
    optional_text,
    safe_id,
    unique_by_id,
)

MODEL_ROLES = {"proposal_only"}
STATE_AUTHORITIES = {"deterministic_local"}
ACTION_AUTHORITIES = {"named_human_or_controller"}
CONNECTIVITY_RULES = {"additive_streams_only"}
GPU_RULES = {"optional_burst_accelerator"}
HISTORY_RULES = {"append_only_branch_preserving"}
CLAIM_CLASSES = {"baseline", "comparison_only", "candidate"}
REACHBACK_CLASSES = {"none", "intermittent", "broad"}
FAULT_STAGES = {"ascent", "descent", "either"}
FAULT_KINDS = {
    "wan_loss",
    "peer_mesh_loss",
    "remote_local_conflict",
    "stale_remote_report",
    "model_server_restart",
    "gpu_disconnect",
    "head_swap",
    "storage_pressure",
    "adapter_loss",
    "operator_witness_loss",
}
EVIDENCE_CLASSES = {
    "implemented_fixture",
    "private_reported_trace",
    "public_record",
    "synthetic_control",
    "customer_historical",
    "unmeasured",
}
OBSERVATION_STATUSES = {"unmeasured", "measured", "error"}


def _string_set(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    rows = need_array(value, label, nonempty=nonempty)
    result = [safe_id(item, label) for item in rows]
    if len(result) != len(set(result)):
        raise EdgeError(f"{label} contains duplicates")
    return sorted(result)


def _text_list(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    rows = need_array(value, label, nonempty=nonempty)
    result = [need_text(item, label, limit=2000) for item in rows]
    if len(result) != len(set(result)):
        raise EdgeError(f"{label} contains duplicates")
    return result


def _authority(raw: Any) -> dict[str, Any]:
    row = need_object(raw, "authority")
    exact_keys(
        row,
        {
            "model_role",
            "state_authority",
            "action_authority",
            "connectivity_rule",
            "gpu_rule",
            "history_rule",
            "promotion_authority",
        },
        set(),
        "authority",
    )
    result = {
        "model_role": need_text(row["model_role"], "authority.model_role", limit=80),
        "state_authority": need_text(
            row["state_authority"], "authority.state_authority", limit=80
        ),
        "action_authority": need_text(
            row["action_authority"], "authority.action_authority", limit=80
        ),
        "connectivity_rule": need_text(
            row["connectivity_rule"], "authority.connectivity_rule", limit=80
        ),
        "gpu_rule": need_text(row["gpu_rule"], "authority.gpu_rule", limit=80),
        "history_rule": need_text(row["history_rule"], "authority.history_rule", limit=80),
        "promotion_authority": need_text(
            row["promotion_authority"], "authority.promotion_authority", limit=200
        ),
    }
    if result["model_role"] not in MODEL_ROLES:
        raise EdgeError("authority.model_role must remain proposal_only")
    if result["state_authority"] not in STATE_AUTHORITIES:
        raise EdgeError("authority.state_authority must remain deterministic_local")
    if result["action_authority"] not in ACTION_AUTHORITIES:
        raise EdgeError("authority.action_authority must remain named_human_or_controller")
    if result["connectivity_rule"] not in CONNECTIVITY_RULES:
        raise EdgeError("authority.connectivity_rule must remain additive_streams_only")
    if result["gpu_rule"] not in GPU_RULES:
        raise EdgeError("authority.gpu_rule must remain optional_burst_accelerator")
    if result["history_rule"] not in HISTORY_RULES:
        raise EdgeError("authority.history_rule must remain append_only_branch_preserving")
    return result


def _survival_floor(raw: Any) -> dict[str, Any]:
    row = need_object(raw, "survival_floor")
    exact_keys(
        row,
        {
            "wan_required",
            "gpu_required",
            "remote_auth_required",
            "required_capabilities",
            "max_recovery_ms",
        },
        set(),
        "survival_floor",
    )
    result = {
        "wan_required": need_boolean(row["wan_required"], "survival_floor.wan_required"),
        "gpu_required": need_boolean(row["gpu_required"], "survival_floor.gpu_required"),
        "remote_auth_required": need_boolean(
            row["remote_auth_required"], "survival_floor.remote_auth_required"
        ),
        "required_capabilities": _string_set(
            row["required_capabilities"],
            "survival_floor.required_capabilities",
            nonempty=True,
        ),
        "max_recovery_ms": need_integer(
            row["max_recovery_ms"], "survival_floor.max_recovery_ms", 0, 86_400_000
        ),
    }
    if result["wan_required"] or result["gpu_required"] or result["remote_auth_required"]:
        raise EdgeError("the survival floor cannot require WAN, burst GPU, or remote authentication")
    return result


def _connectivity_profile(raw: Any, index: int) -> dict[str, Any]:
    row = need_object(raw, f"connectivity_profiles[{index}]")
    exact_keys(
        row,
        {"id", "rank", "title", "adds_streams", "adds_outputs", "required_local_capabilities"},
        set(),
        f"connectivity_profiles[{index}]",
    )
    return {
        "id": safe_id(row["id"], f"connectivity_profiles[{index}].id"),
        "rank": need_integer(row["rank"], f"connectivity_profiles[{index}].rank", 0, 32),
        "title": need_text(row["title"], f"connectivity_profiles[{index}].title", limit=200),
        "adds_streams": _string_set(
            row["adds_streams"], f"connectivity_profiles[{index}].adds_streams"
        ),
        "adds_outputs": _string_set(
            row["adds_outputs"], f"connectivity_profiles[{index}].adds_outputs"
        ),
        "required_local_capabilities": _string_set(
            row["required_local_capabilities"],
            f"connectivity_profiles[{index}].required_local_capabilities",
            nonempty=True,
        ),
    }


def _role(raw: Any, index: int) -> dict[str, Any]:
    row = need_object(raw, f"roles[{index}]")
    exact_keys(
        row,
        {"id", "title", "questions", "may_decide", "may_not_decide"},
        set(),
        f"roles[{index}]",
    )
    return {
        "id": safe_id(row["id"], f"roles[{index}].id"),
        "title": need_text(row["title"], f"roles[{index}].title", limit=200),
        "questions": _text_list(row["questions"], f"roles[{index}].questions", nonempty=True),
        "may_decide": _string_set(row["may_decide"], f"roles[{index}].may_decide"),
        "may_not_decide": _string_set(
            row["may_not_decide"], f"roles[{index}].may_not_decide", nonempty=True
        ),
    }


def _stream_family(raw: Any, index: int) -> dict[str, Any]:
    row = need_object(raw, f"stream_families[{index}]")
    exact_keys(
        row,
        {
            "id",
            "title",
            "source_types",
            "envelope_fields",
            "local_at_c0",
            "model_may_interpret",
            "action_authority",
        },
        set(),
        f"stream_families[{index}]",
    )
    envelope_fields = _string_set(
        row["envelope_fields"], f"stream_families[{index}].envelope_fields", nonempty=True
    )
    missing = sorted(BASE_STREAM_ENVELOPE_FIELDS - set(envelope_fields))
    if missing:
        raise EdgeError(
            f"stream_families[{index}].envelope_fields is missing required custody fields: {missing}"
        )
    action_authority = need_text(
        row["action_authority"], f"stream_families[{index}].action_authority", limit=120
    )
    if action_authority not in {"none", "source_declared_only", "named_human_or_controller"}:
        raise EdgeError(f"stream_families[{index}].action_authority is invalid")
    return {
        "id": safe_id(row["id"], f"stream_families[{index}].id"),
        "title": need_text(row["title"], f"stream_families[{index}].title", limit=200),
        "source_types": _string_set(
            row["source_types"], f"stream_families[{index}].source_types", nonempty=True
        ),
        "envelope_fields": envelope_fields,
        "local_at_c0": need_boolean(
            row["local_at_c0"], f"stream_families[{index}].local_at_c0"
        ),
        "model_may_interpret": need_boolean(
            row["model_may_interpret"], f"stream_families[{index}].model_may_interpret"
        ),
        "action_authority": action_authority,
    }


def _workload(
    raw: Any,
    index: int,
    roles: dict[str, dict[str, Any]],
    streams: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    row = need_object(raw, f"workloads[{index}]")
    exact_keys(
        row,
        {
            "id",
            "title",
            "evidence_class",
            "roles",
            "streams",
            "decision_products",
            "model_jobs",
            "deterministic_jobs",
            "acceptance_contract",
        },
        {"donor_ref"},
        f"workloads[{index}]",
    )
    evidence_class = need_text(
        row["evidence_class"], f"workloads[{index}].evidence_class", limit=80
    )
    if evidence_class not in EVIDENCE_CLASSES:
        raise EdgeError(f"workloads[{index}].evidence_class is invalid")
    role_ids = _string_set(row["roles"], f"workloads[{index}].roles", nonempty=True)
    stream_ids = _string_set(row["streams"], f"workloads[{index}].streams", nonempty=True)
    unknown_roles = sorted(set(role_ids) - roles.keys())
    unknown_streams = sorted(set(stream_ids) - streams.keys())
    if unknown_roles:
        raise EdgeError(f"workloads[{index}] references unknown roles: {unknown_roles}")
    if unknown_streams:
        raise EdgeError(f"workloads[{index}] references unknown streams: {unknown_streams}")
    donor_ref = optional_text(row.get("donor_ref"), f"workloads[{index}].donor_ref", limit=500)
    result = {
        "id": safe_id(row["id"], f"workloads[{index}].id"),
        "title": need_text(row["title"], f"workloads[{index}].title", limit=200),
        "evidence_class": evidence_class,
        "roles": role_ids,
        "streams": stream_ids,
        "decision_products": _string_set(
            row["decision_products"], f"workloads[{index}].decision_products", nonempty=True
        ),
        "model_jobs": _string_set(row["model_jobs"], f"workloads[{index}].model_jobs"),
        "deterministic_jobs": _string_set(
            row["deterministic_jobs"],
            f"workloads[{index}].deterministic_jobs",
            nonempty=True,
        ),
        "acceptance_contract": need_text(
            row["acceptance_contract"],
            f"workloads[{index}].acceptance_contract",
            limit=4000,
        ),
    }
    if donor_ref is not None:
        result["donor_ref"] = donor_ref
    return result


def _hardware_profile(raw: Any, index: int) -> dict[str, Any]:
    row = need_object(raw, f"hardware_profiles[{index}]")
    exact_keys(
        row,
        {
            "id",
            "title",
            "head_class",
            "burst_gpu",
            "gpu_memory_mib",
            "power_limit_w",
            "thunderbolt",
            "memory_pooling",
            "survival_host",
        },
        set(),
        f"hardware_profiles[{index}]",
    )
    burst_gpu = need_text(row["burst_gpu"], f"hardware_profiles[{index}].burst_gpu", limit=80)
    if burst_gpu not in {"none", "rtx3090_24g"}:
        raise EdgeError(f"hardware_profiles[{index}].burst_gpu is invalid")
    power_limit = row["power_limit_w"]
    if power_limit is not None:
        power_limit = need_integer(
            power_limit, f"hardware_profiles[{index}].power_limit_w", 50, 500
        )
    gpu_memory = need_integer(
        row["gpu_memory_mib"], f"hardware_profiles[{index}].gpu_memory_mib", 0, 200_000
    )
    memory_pooling = need_boolean(
        row["memory_pooling"], f"hardware_profiles[{index}].memory_pooling"
    )
    if memory_pooling:
        raise EdgeError("MENACE qualification forbids pooled-VRAM claims")
    if burst_gpu == "none" and (gpu_memory != 0 or power_limit is not None):
        raise EdgeError("a host-only hardware profile cannot declare GPU memory or power")
    if burst_gpu == "rtx3090_24g" and (gpu_memory != 24_576 or power_limit is None):
        raise EdgeError("the RTX 3090 profile must declare 24576 MiB and an explicit power limit")
    return {
        "id": safe_id(row["id"], f"hardware_profiles[{index}].id"),
        "title": need_text(row["title"], f"hardware_profiles[{index}].title", limit=200),
        "head_class": need_text(
            row["head_class"], f"hardware_profiles[{index}].head_class", limit=200
        ),
        "burst_gpu": burst_gpu,
        "gpu_memory_mib": gpu_memory,
        "power_limit_w": power_limit,
        "thunderbolt": need_boolean(
            row["thunderbolt"], f"hardware_profiles[{index}].thunderbolt"
        ),
        "memory_pooling": memory_pooling,
        "survival_host": need_boolean(
            row["survival_host"], f"hardware_profiles[{index}].survival_host"
        ),
    }


def _treatment(
    raw: Any,
    index: int,
    hardware: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    row = need_object(raw, f"treatments[{index}]")
    exact_keys(
        row,
        {
            "id",
            "title",
            "claim_class",
            "hardware_profile",
            "axm_state",
            "local_model",
            "reachback",
            "role_apertures",
            "authority_gate",
            "evidence_custody",
        },
        set(),
        f"treatments[{index}]",
    )
    claim_class = need_text(
        row["claim_class"], f"treatments[{index}].claim_class", limit=40
    )
    if claim_class not in CLAIM_CLASSES:
        raise EdgeError(f"treatments[{index}].claim_class is invalid")
    hardware_profile = safe_id(
        row["hardware_profile"], f"treatments[{index}].hardware_profile"
    )
    if hardware_profile not in hardware:
        raise EdgeError(f"treatments[{index}] references unknown hardware profile {hardware_profile}")
    reachback = need_text(row["reachback"], f"treatments[{index}].reachback", limit=40)
    if reachback not in REACHBACK_CLASSES:
        raise EdgeError(f"treatments[{index}].reachback is invalid")
    result = {
        "id": safe_id(row["id"], f"treatments[{index}].id"),
        "title": need_text(row["title"], f"treatments[{index}].title", limit=200),
        "claim_class": claim_class,
        "hardware_profile": hardware_profile,
        "axm_state": need_boolean(row["axm_state"], f"treatments[{index}].axm_state"),
        "local_model": need_boolean(row["local_model"], f"treatments[{index}].local_model"),
        "reachback": reachback,
        "role_apertures": need_boolean(
            row["role_apertures"], f"treatments[{index}].role_apertures"
        ),
        "authority_gate": need_boolean(
            row["authority_gate"], f"treatments[{index}].authority_gate"
        ),
        "evidence_custody": need_boolean(
            row["evidence_custody"], f"treatments[{index}].evidence_custody"
        ),
    }
    if claim_class == "candidate":
        missing = [
            key
            for key in ("axm_state", "role_apertures", "authority_gate", "evidence_custody")
            if not result[key]
        ]
        if missing:
            raise EdgeError(f"candidate treatment {result['id']} lacks required organs: {missing}")
    if result["local_model"] and hardware[hardware_profile]["burst_gpu"] == "none":
        raise EdgeError(f"treatment {result['id']} requests a local model without a burst GPU")
    return result


def _fault(
    raw: Any,
    index: int,
    profiles: dict[str, dict[str, Any]],
    survival_capabilities: set[str],
) -> dict[str, Any]:
    row = need_object(raw, f"faults[{index}]")
    exact_keys(
        row,
        {
            "id",
            "kind",
            "profile_id",
            "stage",
            "expected_retained_capabilities",
            "human_disposition_required",
            "forbidden_outcomes",
        },
        set(),
        f"faults[{index}]",
    )
    kind = need_text(row["kind"], f"faults[{index}].kind", limit=80)
    if kind not in FAULT_KINDS:
        raise EdgeError(f"faults[{index}].kind is invalid")
    profile_id = safe_id(row["profile_id"], f"faults[{index}].profile_id")
    if profile_id not in profiles:
        raise EdgeError(f"faults[{index}] references unknown profile {profile_id}")
    stage = need_text(row["stage"], f"faults[{index}].stage", limit=20)
    if stage not in FAULT_STAGES:
        raise EdgeError(f"faults[{index}].stage is invalid")
    retained = set(
        _string_set(
            row["expected_retained_capabilities"],
            f"faults[{index}].expected_retained_capabilities",
            nonempty=True,
        )
    )
    missing = sorted(survival_capabilities - retained)
    if missing:
        raise EdgeError(f"faults[{index}] would drop survival capabilities: {missing}")
    return {
        "id": safe_id(row["id"], f"faults[{index}].id"),
        "kind": kind,
        "profile_id": profile_id,
        "stage": stage,
        "expected_retained_capabilities": sorted(retained),
        "human_disposition_required": need_boolean(
            row["human_disposition_required"],
            f"faults[{index}].human_disposition_required",
        ),
        "forbidden_outcomes": _string_set(
            row["forbidden_outcomes"], f"faults[{index}].forbidden_outcomes", nonempty=True
        ),
    }


def _acceptance(raw: Any, treatments: dict[str, dict[str, Any]]) -> dict[str, Any]:
    row = need_object(raw, "acceptance")
    exact_keys(
        row,
        {
            "baseline_treatment",
            "minimum_complete_cells",
            "require_survival_all_faults",
            "require_no_authority_widening",
            "require_branch_preservation",
            "require_no_consequential_miss_increase",
            "thermodynamic_comparison",
        },
        set(),
        "acceptance",
    )
    baseline = safe_id(row["baseline_treatment"], "acceptance.baseline_treatment")
    if baseline not in treatments:
        raise EdgeError(f"acceptance baseline treatment is unknown: {baseline}")
    if treatments[baseline]["claim_class"] != "baseline":
        raise EdgeError("acceptance baseline_treatment must name a baseline treatment")
    comparison = need_text(
        row["thermodynamic_comparison"], "acceptance.thermodynamic_comparison", limit=100
    )
    if comparison != "pareto_vector_without_aggregate_score":
        raise EdgeError("acceptance must preserve the Pareto vector and forbid aggregate scores")
    return {
        "baseline_treatment": baseline,
        "minimum_complete_cells": need_integer(
            row["minimum_complete_cells"], "acceptance.minimum_complete_cells", 1, 1_000_000
        ),
        "require_survival_all_faults": need_boolean(
            row["require_survival_all_faults"], "acceptance.require_survival_all_faults"
        ),
        "require_no_authority_widening": need_boolean(
            row["require_no_authority_widening"],
            "acceptance.require_no_authority_widening",
        ),
        "require_branch_preservation": need_boolean(
            row["require_branch_preservation"], "acceptance.require_branch_preservation"
        ),
        "require_no_consequential_miss_increase": need_boolean(
            row["require_no_consequential_miss_increase"],
            "acceptance.require_no_consequential_miss_increase",
        ),
        "thermodynamic_comparison": comparison,
    }


def validate_manifest(raw: Any) -> dict[str, Any]:
    row = need_object(raw, "campaign")
    exact_keys(
        row,
        {
            "schema",
            "id",
            "title",
            "claim",
            "authority",
            "survival_floor",
            "connectivity_profiles",
            "roles",
            "stream_families",
            "workloads",
            "hardware_profiles",
            "treatments",
            "faults",
            "required_metrics",
            "acceptance",
        },
        {"notes"},
        "campaign",
    )
    if row["schema"] != MANIFEST_SCHEMA:
        raise EdgeError(f"campaign.schema must be {MANIFEST_SCHEMA}")
    authority = _authority(row["authority"])
    survival = _survival_floor(row["survival_floor"])

    profiles = [
        _connectivity_profile(item, index)
        for index, item in enumerate(
            need_array(row["connectivity_profiles"], "connectivity_profiles", nonempty=True)
        )
    ]
    profile_map = unique_by_id(profiles, "connectivity profile")
    profiles.sort(key=lambda item: item["rank"])
    ranks = [item["rank"] for item in profiles]
    if ranks != list(range(len(profiles))):
        raise EdgeError("connectivity profile ranks must be contiguous and start at zero")
    if profiles[0]["id"] != "C0":
        raise EdgeError("the first connectivity profile must be C0")
    if profiles[0]["adds_streams"] or profiles[0]["adds_outputs"]:
        raise EdgeError("C0 is the survival floor and cannot depend on newly added streams or outputs")
    survival_set = set(survival["required_capabilities"])
    for profile in profiles:
        missing = sorted(survival_set - set(profile["required_local_capabilities"]))
        if missing:
            raise EdgeError(f"connectivity profile {profile['id']} drops survival capabilities: {missing}")

    roles = [
        _role(item, index)
        for index, item in enumerate(need_array(row["roles"], "roles", nonempty=True))
    ]
    role_map = unique_by_id(roles, "role")
    streams = [
        _stream_family(item, index)
        for index, item in enumerate(
            need_array(row["stream_families"], "stream_families", nonempty=True)
        )
    ]
    stream_map = unique_by_id(streams, "stream family")
    c0_streams = {item["id"] for item in streams if item["local_at_c0"]}
    seen_added_streams: set[str] = set()
    seen_added_outputs: set[str] = set()
    for profile in profiles[1:]:
        unknown = sorted(set(profile["adds_streams"]) - stream_map.keys())
        if unknown:
            raise EdgeError(f"connectivity profile {profile['id']} adds unknown streams: {unknown}")
        duplicate_streams = sorted(
            set(profile["adds_streams"]) & (c0_streams | seen_added_streams)
        )
        if duplicate_streams:
            raise EdgeError(
                f"connectivity profile {profile['id']} re-adds existing streams: {duplicate_streams}"
            )
        duplicate_outputs = sorted(set(profile["adds_outputs"]) & seen_added_outputs)
        if duplicate_outputs:
            raise EdgeError(
                f"connectivity profile {profile['id']} re-adds existing outputs: {duplicate_outputs}"
            )
        seen_added_streams.update(profile["adds_streams"])
        seen_added_outputs.update(profile["adds_outputs"])
    unplaced = sorted(set(stream_map) - c0_streams - seen_added_streams)
    if unplaced:
        raise EdgeError(f"stream families are never introduced by C0 or connectivity: {unplaced}")
    workloads = [
        _workload(item, index, role_map, stream_map)
        for index, item in enumerate(
            need_array(row["workloads"], "workloads", nonempty=True)
        )
    ]
    unique_by_id(workloads, "workload")
    hardware = [
        _hardware_profile(item, index)
        for index, item in enumerate(
            need_array(row["hardware_profiles"], "hardware_profiles", nonempty=True)
        )
    ]
    hardware_map = unique_by_id(hardware, "hardware profile")
    treatments = [
        _treatment(item, index, hardware_map)
        for index, item in enumerate(
            need_array(row["treatments"], "treatments", nonempty=True)
        )
    ]
    treatment_map = unique_by_id(treatments, "treatment")
    if sum(item["claim_class"] == "baseline" for item in treatments) != 1:
        raise EdgeError("the campaign must declare exactly one baseline treatment")
    faults = [
        _fault(item, index, profile_map, survival_set)
        for index, item in enumerate(need_array(row["faults"], "faults", nonempty=True))
    ]
    unique_by_id(faults, "fault")

    required_metrics = _string_set(row["required_metrics"], "required_metrics", nonempty=True)
    missing_metrics = sorted(set(MANDATORY_METRICS) - set(required_metrics))
    if missing_metrics:
        raise EdgeError(f"required_metrics is missing mandatory fields: {missing_metrics}")
    acceptance = _acceptance(row["acceptance"], treatment_map)
    weakened = [
        key
        for key in (
            "require_survival_all_faults",
            "require_no_authority_widening",
            "require_branch_preservation",
            "require_no_consequential_miss_increase",
        )
        if not acceptance[key]
    ]
    if weakened:
        raise EdgeError(f"acceptance cannot weaken mandatory gates: {weakened}")
    notes = optional_text(row.get("notes"), "notes", limit=5000)

    result = {
        "schema": MANIFEST_SCHEMA,
        "id": safe_id(row["id"], "campaign.id"),
        "title": need_text(row["title"], "campaign.title", limit=300),
        "claim": need_text(row["claim"], "campaign.claim", limit=5000),
        "authority": authority,
        "survival_floor": survival,
        "connectivity_profiles": profiles,
        "roles": roles,
        "stream_families": streams,
        "workloads": workloads,
        "hardware_profiles": hardware,
        "treatments": treatments,
        "faults": faults,
        "required_metrics": required_metrics,
        "acceptance": acceptance,
    }
    if notes is not None:
        result["notes"] = notes
    return result


def validate_observation(
    raw: Any,
    *,
    required_metrics: list[str],
    plan_cells: dict[str, dict[str, Any]],
    plan_id: str,
) -> dict[str, Any]:
    row = need_object(raw, "observation")
    exact_keys(
        row,
        {
            "schema",
            "status",
            "plan_id",
            "cell_id",
            "treatment_id",
            "workload_id",
            "hardware_profile",
            "connectivity_profile",
            "sequence",
            "direction",
            "observed_at",
            "hardware_identity",
            "runtime_identity",
            "model_identity",
            "metrics",
            "outcomes",
            "receipts",
        },
        {"error"},
        "observation",
    )
    if row["schema"] != OBSERVATION_SCHEMA:
        raise EdgeError(f"observation.schema must be {OBSERVATION_SCHEMA}")
    status = need_text(row["status"], "observation.status", limit=30)
    if status not in OBSERVATION_STATUSES:
        raise EdgeError("observation.status is invalid")
    if row["plan_id"] != plan_id:
        raise EdgeError("observation.plan_id does not match the plan")
    cell_id = safe_id(row["cell_id"], "observation.cell_id")
    if cell_id not in plan_cells:
        raise EdgeError(f"observation references unknown cell {cell_id}")
    cell = plan_cells[cell_id]
    identity_fields = {
        "treatment_id": cell["treatment_id"],
        "workload_id": cell["workload_id"],
        "hardware_profile": cell["hardware_profile"],
        "connectivity_profile": cell["connectivity_profile"],
        "sequence": cell["sequence"],
        "direction": cell["direction"],
    }
    for key, expected in identity_fields.items():
        if row[key] != expected:
            raise EdgeError(f"observation.{key} does not match plan cell {cell_id}")

    result: dict[str, Any] = {
        "schema": OBSERVATION_SCHEMA,
        "status": status,
        "plan_id": plan_id,
        "cell_id": cell_id,
        **identity_fields,
        "observed_at": need_text(row["observed_at"], "observation.observed_at", limit=100),
        "hardware_identity": need_text(
            row["hardware_identity"], "observation.hardware_identity", limit=1000
        ),
        "runtime_identity": need_text(
            row["runtime_identity"], "observation.runtime_identity", limit=1000
        ),
        "model_identity": need_text(
            row["model_identity"], "observation.model_identity", limit=1000
        ),
    }
    if status == "unmeasured":
        if row["metrics"] != {} or row["outcomes"] != {} or row["receipts"] != []:
            raise EdgeError("unmeasured observations must not invent metrics, outcomes, or receipts")
        result.update({"metrics": {}, "outcomes": {}, "receipts": []})
        if row.get("error") is not None:
            raise EdgeError("unmeasured observations cannot contain an error")
        return result

    if status == "error":
        error = need_text(row.get("error"), "observation.error", limit=4000)
        if row["metrics"] != {} or row["outcomes"] != {}:
            raise EdgeError("error observations must not masquerade as measurements")
        receipts = []
        for index, item in enumerate(need_array(row["receipts"], "observation.receipts")):
            receipt = need_object(item, f"observation.receipts[{index}]")
            exact_keys(
                receipt,
                {"kind", "sha256", "ref"},
                set(),
                f"observation.receipts[{index}]",
            )
            receipts.append(
                {
                    "kind": safe_id(receipt["kind"], f"observation.receipts[{index}].kind"),
                    "sha256": need_digest(
                        receipt["sha256"], f"observation.receipts[{index}].sha256"
                    ),
                    "ref": need_text(receipt["ref"], f"observation.receipts[{index}].ref", limit=1000),
                }
            )
        result.update({"metrics": {}, "outcomes": {}, "receipts": receipts, "error": error})
        return result

    metrics_raw = need_object(row["metrics"], "observation.metrics")
    exact_keys(metrics_raw, set(required_metrics), set(), "observation.metrics")
    metrics = {
        key: need_integer(metrics_raw[key], f"observation.metrics.{key}")
        for key in required_metrics
    }
    outcomes_raw = need_object(row["outcomes"], "observation.outcomes")
    exact_keys(outcomes_raw, set(MANDATORY_OUTCOMES), {"notes"}, "observation.outcomes")
    outcomes: dict[str, Any] = {
        key: need_boolean(outcomes_raw[key], f"observation.outcomes.{key}")
        for key in MANDATORY_OUTCOMES
    }
    notes = optional_text(outcomes_raw.get("notes"), "observation.outcomes.notes", limit=4000)
    if notes is not None:
        outcomes["notes"] = notes
    receipts = []
    for index, item in enumerate(
        need_array(row["receipts"], "observation.receipts", nonempty=True)
    ):
        receipt = need_object(item, f"observation.receipts[{index}]")
        exact_keys(
            receipt,
            {"kind", "sha256", "ref"},
            set(),
            f"observation.receipts[{index}]",
        )
        receipts.append(
            {
                "kind": safe_id(receipt["kind"], f"observation.receipts[{index}].kind"),
                "sha256": need_digest(
                    receipt["sha256"], f"observation.receipts[{index}].sha256"
                ),
                "ref": need_text(receipt["ref"], f"observation.receipts[{index}].ref", limit=1000),
            }
        )
    result.update({"metrics": metrics, "outcomes": outcomes, "receipts": receipts})
    return result
