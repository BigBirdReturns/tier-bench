"""Deterministic connectivity, fault, and treatment planning for MENACE edge."""
from __future__ import annotations

import copy
from typing import Any

from .menace_edge_common import (
    OBSERVATION_SCHEMA,
    PLAN_SCHEMA,
    EdgeError,
    canonical_bytes,
    hash_json,
)
from .menace_edge_schema import validate_manifest


def _route(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    profiles = manifest["connectivity_profiles"]
    stream_map = {row["id"]: row for row in manifest["stream_families"]}
    cumulative_streams = sorted(
        row["id"] for row in manifest["stream_families"] if row["local_at_c0"]
    )
    cumulative_outputs: list[str] = []
    route: list[dict[str, Any]] = []

    for profile in profiles:
        if profile["rank"]:
            cumulative_streams = sorted(set(cumulative_streams) | set(profile["adds_streams"]))
            cumulative_outputs = sorted(set(cumulative_outputs) | set(profile["adds_outputs"]))
        route.append(
            {
                "sequence": len(route),
                "direction": "ascent",
                "profile_id": profile["id"],
                "profile_rank": profile["rank"],
                "available_streams": cumulative_streams.copy(),
                "available_outputs": cumulative_outputs.copy(),
                "required_local_capabilities": profile["required_local_capabilities"],
            }
        )

    active_streams = set(cumulative_streams)
    active_outputs = set(cumulative_outputs)
    for profile in reversed(profiles[:-1]):
        removed_profile = profiles[profile["rank"] + 1]
        active_streams -= set(removed_profile["adds_streams"])
        active_outputs -= set(removed_profile["adds_outputs"])
        route.append(
            {
                "sequence": len(route),
                "direction": "descent",
                "profile_id": profile["id"],
                "profile_rank": profile["rank"],
                "available_streams": sorted(active_streams),
                "available_outputs": sorted(active_outputs),
                "required_local_capabilities": profile["required_local_capabilities"],
            }
        )

    # Defensive reference check after expansion.
    unknown = sorted(
        {
            stream
            for step in route
            for stream in step["available_streams"]
            if stream not in stream_map
        }
    )
    if unknown:
        raise EdgeError(f"connectivity route contains unknown streams: {unknown}")
    return route


def _faults_for_step(manifest: dict[str, Any], step: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for fault in manifest["faults"]:
        if fault["profile_id"] != step["profile_id"]:
            continue
        if fault["stage"] not in {"either", step["direction"]}:
            continue
        result.append(fault)
    return sorted(result, key=lambda item: item["id"])


def _cell(
    manifest: dict[str, Any],
    treatment: dict[str, Any],
    workload: dict[str, Any],
    step: dict[str, Any],
    hardware: dict[str, Any],
) -> dict[str, Any]:
    faults = _faults_for_step(manifest, step)
    available = set(step["available_streams"])
    missing_workload_streams = sorted(set(workload["streams"]) - available)
    body = {
        "campaign_id": manifest["id"],
        "treatment_id": treatment["id"],
        "treatment_claim_class": treatment["claim_class"],
        "workload_id": workload["id"],
        "hardware_profile": hardware["id"],
        "connectivity_profile": step["profile_id"],
        "sequence": step["sequence"],
        "direction": step["direction"],
        "comparison_key": (
            f"{workload['id']}:{step['sequence']}:{step['profile_id']}:{step['direction']}"
        ),
        "available_streams": step["available_streams"],
        "available_outputs": step["available_outputs"],
        "missing_workload_streams": missing_workload_streams,
        "degraded_input_expected": bool(missing_workload_streams),
        "required_local_capabilities": step["required_local_capabilities"],
        "survival_floor_capabilities": manifest["survival_floor"]["required_capabilities"],
        "faults": [
            {
                "id": fault["id"],
                "kind": fault["kind"],
                "human_disposition_required": fault["human_disposition_required"],
                "forbidden_outcomes": fault["forbidden_outcomes"],
            }
            for fault in faults
        ],
        "required_metrics": manifest["required_metrics"],
        "authority_expectation": {
            "model_role": manifest["authority"]["model_role"],
            "action_authority": manifest["authority"]["action_authority"],
            "history_rule": manifest["authority"]["history_rule"],
        },
        "hardware": {
            "burst_gpu": hardware["burst_gpu"],
            "gpu_memory_mib": hardware["gpu_memory_mib"],
            "power_limit_w": hardware["power_limit_w"],
            "thunderbolt": hardware["thunderbolt"],
            "memory_pooling": hardware["memory_pooling"],
        },
        "treatment": {
            "axm_state": treatment["axm_state"],
            "local_model": treatment["local_model"],
            "reachback": treatment["reachback"],
            "role_apertures": treatment["role_apertures"],
            "authority_gate": treatment["authority_gate"],
            "evidence_custody": treatment["evidence_custody"],
        },
        "workload_acceptance_contract": workload["acceptance_contract"],
    }
    return {"cell_id": f"menacecell1_{hash_json(body)}", **body}


def compile_plan(raw: Any) -> dict[str, Any]:
    manifest = validate_manifest(raw)
    route = _route(manifest)
    hardware = {row["id"]: row for row in manifest["hardware_profiles"]}
    cells = []
    for treatment in manifest["treatments"]:
        profile = hardware[treatment["hardware_profile"]]
        for workload in manifest["workloads"]:
            for step in route:
                cells.append(_cell(manifest, treatment, workload, step, profile))
    body = {
        "schema": PLAN_SCHEMA,
        "campaign_id": manifest["id"],
        "manifest_sha256": hash_json(manifest),
        "authority": manifest["authority"],
        "survival_floor": manifest["survival_floor"],
        "route": route,
        "cells": cells,
        "totals": {
            "connectivity_steps": len(route),
            "workloads": len(manifest["workloads"]),
            "treatments": len(manifest["treatments"]),
            "hardware_profiles": len(manifest["hardware_profiles"]),
            "faults": len(manifest["faults"]),
            "cells": len(cells),
            "fault_cells": sum(bool(cell["faults"]) for cell in cells),
            "degraded_input_cells": sum(cell["degraded_input_expected"] for cell in cells),
        },
    }
    return {"plan_id": f"menaceplan1_{hash_json(body)}", **body}


def verify_plan(raw: Any, candidate: Any) -> list[str]:
    expected = compile_plan(raw)
    if not isinstance(candidate, dict):
        return ["plan must be an object"]
    if canonical_bytes(expected) == canonical_bytes(candidate):
        return []
    errors = []
    for key in ("schema", "plan_id", "campaign_id", "manifest_sha256", "route", "cells", "totals"):
        if candidate.get(key) != expected.get(key):
            errors.append(f"plan.{key} differs from deterministic compilation")
    return errors or ["plan differs from deterministic compilation"]


def observation_templates(plan: dict[str, Any]) -> list[dict[str, Any]]:
    if plan.get("schema") != PLAN_SCHEMA or not isinstance(plan.get("cells"), list):
        raise EdgeError("observation templates require a compiled MENACE plan")
    result = []
    for cell in plan["cells"]:
        result.append(
            {
                "schema": OBSERVATION_SCHEMA,
                "status": "unmeasured",
                "plan_id": plan["plan_id"],
                "cell_id": cell["cell_id"],
                "treatment_id": cell["treatment_id"],
                "workload_id": cell["workload_id"],
                "hardware_profile": cell["hardware_profile"],
                "connectivity_profile": cell["connectivity_profile"],
                "sequence": cell["sequence"],
                "direction": cell["direction"],
                "observed_at": "UNMEASURED",
                "hardware_identity": "UNMEASURED",
                "runtime_identity": "UNMEASURED",
                "model_identity": "UNMEASURED",
                "metrics": {},
                "outcomes": {},
                "receipts": [],
            }
        )
    return result
