"""Deterministic plan, proof matrix, and observation templates for HALO3 Cell Zero."""
from __future__ import annotations

from typing import Any

from .halo3_cell_common import (
    OBSERVATION_SCHEMA,
    PLAN_SCHEMA,
    PROOF_MATRIX_SCHEMA,
    Halo3Error,
    canonical_bytes,
    hash_json,
)
from .halo3_cell_schema import validate_fingerprint_contract, validate_lab


def _fingerprint_cell(
    *,
    lab: dict[str, Any],
    contract: dict[str, Any],
    model: dict[str, Any],
    family: dict[str, Any],
    condition: dict[str, Any],
) -> dict[str, Any]:
    body = {
        "lab_id": lab["id"],
        "contract_id": contract["id"],
        "model_id": model["id"],
        "identity_mode": model["identity_mode"],
        "family_id": family["id"],
        "condition_id": condition["id"],
        "required_identity_fields": model["required_identity_fields"],
        "model_roles": model["roles"],
        "product": family["product"],
        "hidden_acceptance": family["hidden_acceptance"],
        "negative_controls": family["negative_controls"],
        "minimum_trials": family["minimum_trials"],
        "mutations": condition["mutations"],
        "required_metrics": contract["required_metrics"],
        "authority_ceiling": model["authority_ceiling"],
    }
    return {"cell_id": f"halo3fingerprint1_{hash_json(body)}", **body}


def _stage_cell(
    *,
    lab: dict[str, Any],
    stage: dict[str, Any],
    node_map: dict[str, dict[str, Any]],
    claim_map: dict[str, dict[str, Any]],
    fault_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    body = {
        "lab_id": lab["id"],
        "stage_id": stage["id"],
        "sequence": stage["sequence"],
        "kind": stage["kind"],
        "intervention": stage["intervention"],
        "required_nodes": [node_map[item] for item in stage["required_nodes"]],
        "claims": [claim_map[item] for item in stage["claim_ids"]],
        "faults": [fault_map[item] for item in stage["fault_ids"]],
        "acceptance": stage["acceptance"],
        "required_metrics": lab["required_metrics"],
    }
    return {"cell_id": f"halo3stage1_{hash_json(body)}", **body}


def compile_plan(raw_lab: Any, raw_fingerprint: Any) -> dict[str, Any]:
    contract = validate_fingerprint_contract(raw_fingerprint)
    lab = validate_lab(raw_lab, contract)
    model_map = {item["id"]: item for item in lab["models"]}
    node_map = {item["id"]: item for item in lab["nodes"]}
    claim_map = {item["id"]: item for item in lab["claims"]}
    fault_map = {item["id"]: item for item in lab["faults"]}

    fingerprint_cells = []
    for model_id in sorted(model_map):
        model = model_map[model_id]
        for family in contract["families"]:
            for condition in contract["conditions"]:
                fingerprint_cells.append(
                    _fingerprint_cell(
                        lab=lab,
                        contract=contract,
                        model=model,
                        family=family,
                        condition=condition,
                    )
                )

    stage_cells = [
        _stage_cell(
            lab=lab,
            stage=stage,
            node_map=node_map,
            claim_map=claim_map,
            fault_map=fault_map,
        )
        for stage in lab["stages"]
    ]

    body = {
        "schema": PLAN_SCHEMA,
        "lab_id": lab["id"],
        "lab_sha256": hash_json(lab),
        "fingerprint_contract_id": contract["id"],
        "fingerprint_contract_sha256": hash_json(contract),
        "authority": lab["authority"],
        "model_identity_modes": {
            model["id"]: model["identity_mode"] for model in lab["models"]
        },
        "fingerprint_cells": fingerprint_cells,
        "stage_cells": stage_cells,
        "totals": {
            "models": len(lab["models"]),
            "fingerprint_dimensions": len(contract["dimensions"]),
            "fingerprint_families": len(contract["families"]),
            "fingerprint_conditions": len(contract["conditions"]),
            "fingerprint_cells": len(fingerprint_cells),
            "nodes": len(lab["nodes"]),
            "stages": len(stage_cells),
            "claims": len(lab["claims"]),
            "faults": len(lab["faults"]),
            "cells": len(fingerprint_cells) + len(stage_cells),
        },
        "physical_boundary": lab["physical_boundary"],
        "production_claim": False,
        "promotion_authorized": False,
    }
    return {"plan_id": f"halo3plan1_{hash_json(body)}", **body}


def verify_plan(raw_lab: Any, raw_fingerprint: Any, candidate: Any) -> list[str]:
    expected = compile_plan(raw_lab, raw_fingerprint)
    if not isinstance(candidate, dict):
        return ["HALO3 plan must be an object"]
    if canonical_bytes(expected) == canonical_bytes(candidate):
        return []
    errors = []
    for key in (
        "schema",
        "plan_id",
        "lab_id",
        "lab_sha256",
        "fingerprint_contract_id",
        "fingerprint_contract_sha256",
        "authority",
        "model_identity_modes",
        "fingerprint_cells",
        "stage_cells",
        "totals",
        "physical_boundary",
    ):
        if candidate.get(key) != expected.get(key):
            errors.append(f"plan.{key} differs from deterministic compilation")
    return errors or ["HALO3 plan differs from deterministic compilation"]


def compile_proof_matrix(raw_lab: Any, raw_fingerprint: Any) -> dict[str, Any]:
    contract = validate_fingerprint_contract(raw_fingerprint)
    lab = validate_lab(raw_lab, contract)
    stage_map = {item["id"]: item for item in lab["stages"]}
    node_map = {item["id"]: item for item in lab["nodes"]}
    model_map = {item["id"]: item for item in lab["models"]}

    rows = []
    for claim in lab["claims"]:
        witness_detail = []
        for token in claim["minimal_witnesses"]:
            kind, identifier = token.split(":", 1)
            if kind == "node":
                node = node_map[identifier]
                detail = {
                    "type": kind,
                    "id": identifier,
                    "state": node["state"],
                    "physical_qualification": node["physical_qualification"],
                    "failure_domain": node["failure_domain"],
                }
            elif kind == "model":
                model = model_map[identifier]
                detail = {
                    "type": kind,
                    "id": identifier,
                    "identity_mode": model["identity_mode"],
                    "authority_ceiling": model["authority_ceiling"],
                }
            else:
                detail = {"type": kind, "id": identifier}
            witness_detail.append(detail)
        stage = stage_map[claim["proof_stage"]]
        rows.append(
            {
                "claim_id": claim["id"],
                "title": claim["title"],
                "category": claim["category"],
                "state": claim["state"],
                "proof_stage": stage["id"],
                "stage_sequence": stage["sequence"],
                "minimal_witnesses": claim["minimal_witnesses"],
                "witness_detail": witness_detail,
                "negative_control": claim["negative_control"],
                "subtraction_target": claim["subtraction_target"],
                "required_receipts": claim["required_receipts"],
                "acceptance": claim["acceptance"],
            }
        )

    body = {
        "schema": PROOF_MATRIX_SCHEMA,
        "lab_id": lab["id"],
        "lab_sha256": hash_json(lab),
        "fingerprint_contract_id": contract["id"],
        "fingerprint_contract_sha256": hash_json(contract),
        "claims": rows,
        "totals": {
            "claims": len(rows),
            "declared": sum(item["state"] == "declared" for item in rows),
            "accepted": sum(item["state"] == "accepted" for item in rows),
            "stages": len(lab["stages"]),
            "models": len(lab["models"]),
            "nodes": len(lab["nodes"]),
        },
        "claim_boundary": (
            "This matrix freezes what must be measured. It does not convert declared topology, "
            "fixtures, model output, successful process exit, or generated receipts into physical "
            "qualification or production acceptance."
        ),
        "production_claim": False,
        "promotion_authorized": False,
    }
    return {"matrix_id": f"halo3proof1_{hash_json(body)}", **body}


def verify_proof_matrix(
    raw_lab: Any,
    raw_fingerprint: Any,
    candidate: Any,
) -> list[str]:
    expected = compile_proof_matrix(raw_lab, raw_fingerprint)
    if not isinstance(candidate, dict):
        return ["HALO3 proof matrix must be an object"]
    if canonical_bytes(expected) == canonical_bytes(candidate):
        return []
    errors = []
    for key in (
        "schema",
        "matrix_id",
        "lab_id",
        "lab_sha256",
        "fingerprint_contract_id",
        "fingerprint_contract_sha256",
        "claims",
        "totals",
        "claim_boundary",
    ):
        if candidate.get(key) != expected.get(key):
            errors.append(f"proof_matrix.{key} differs from deterministic compilation")
    return errors or ["HALO3 proof matrix differs from deterministic compilation"]


def render_proof_markdown(matrix: dict[str, Any]) -> str:
    if matrix.get("schema") != PROOF_MATRIX_SCHEMA:
        raise Halo3Error("Markdown rendering requires a HALO3 proof matrix")
    lines = [
        "# HALO3 Cell Zero Proof Matrix",
        "",
        f"Lab: `{matrix['lab_id']}`  ",
        f"Matrix: `{matrix['matrix_id']}`  ",
        f"Fingerprint contract: `{matrix['fingerprint_contract_id']}`",
        "",
        matrix["claim_boundary"],
        "",
        "## Denominator",
        "",
        "| Object | Count |",
        "|---|---:|",
        f"| Claims | {matrix['totals']['claims']} |",
        f"| Declared claims | {matrix['totals']['declared']} |",
        f"| Accepted claims | {matrix['totals']['accepted']} |",
        f"| Stages | {matrix['totals']['stages']} |",
        f"| Models | {matrix['totals']['models']} |",
        f"| Nodes | {matrix['totals']['nodes']} |",
        "",
        "## Claim ledger",
        "",
        "| Claim | Stage | Minimal witnesses | Subtraction | State |",
        "|---|---|---|---|---|",
    ]
    for claim in sorted(matrix["claims"], key=lambda item: item["stage_sequence"]):
        lines.append(
            "| `{}` | `{}` | {} | `{}` | `{}` |".format(
                claim["claim_id"],
                claim["proof_stage"],
                "<br>".join(f"`{item}`" for item in claim["minimal_witnesses"]),
                claim["subtraction_target"],
                claim["state"],
            )
        )
    for claim in sorted(matrix["claims"], key=lambda item: item["stage_sequence"]):
        lines.extend(
            [
                "",
                f"## {claim['stage_sequence']:02d}. {claim['title']}",
                "",
                f"**Claim:** `{claim['claim_id']}`  ",
                f"**Stage:** `{claim['proof_stage']}`  ",
                f"**Category:** `{claim['category']}`  ",
                f"**State:** `{claim['state']}`",
                "",
                "**Minimal witness set**",
                "",
            ]
        )
        lines.extend(f"- `{item}`" for item in claim["minimal_witnesses"])
        lines.extend(
            [
                "",
                f"**Negative control:** {claim['negative_control']}",
                "",
                f"**Subtraction test:** remove `{claim['subtraction_target']}` and require only the "
                "declared capability loss to appear.",
                "",
                f"**Acceptance:** {claim['acceptance']}",
                "",
                "**Required receipts**",
                "",
            ]
        )
        lines.extend(f"- `{item}`" for item in claim["required_receipts"])
    lines.extend(
        [
            "",
            "## Control question",
            "",
            "Can every claimed capability be created by its declared minimal witness set, broken by "
            "its negative control, reduced predictably by subtracting one named witness, and replayed "
            "from independently verified receipts without allowing a model, fixture, or dashboard to "
            "certify itself?",
            "",
        ]
    )
    return "\n".join(lines)


def observation_templates(plan: dict[str, Any]) -> list[dict[str, Any]]:
    if plan.get("schema") != PLAN_SCHEMA:
        raise Halo3Error("observation templates require a compiled HALO3 plan")
    result = []
    for cell in plan["fingerprint_cells"]:
        result.append(
            {
                "schema": OBSERVATION_SCHEMA,
                "status": "unmeasured",
                "plan_id": plan["plan_id"],
                "cell_id": cell["cell_id"],
                "cell_class": "fingerprint",
                "model_id": cell["model_id"],
                "family_id": cell["family_id"],
                "condition_id": cell["condition_id"],
                "stage_id": None,
                "metrics": {},
                "outcomes": {},
                "receipts": [],
            }
        )
    for cell in plan["stage_cells"]:
        result.append(
            {
                "schema": OBSERVATION_SCHEMA,
                "status": "unmeasured",
                "plan_id": plan["plan_id"],
                "cell_id": cell["cell_id"],
                "cell_class": "stage",
                "model_id": None,
                "family_id": None,
                "condition_id": None,
                "stage_id": cell["stage_id"],
                "metrics": {},
                "outcomes": {},
                "receipts": [],
            }
        )
    return result
