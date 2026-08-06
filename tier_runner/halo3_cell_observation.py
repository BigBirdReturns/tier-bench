"""Observation, grading, and ledger contracts for HALO3 Cell Zero activation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Iterable

from .halo3_cell_common import (
    OBSERVATION_SCHEMA,
    PLAN_SCHEMA,
    Halo3Error,
    canonical_bytes,
    exact_keys,
    hash_json,
    need_array,
    need_boolean,
    need_digest,
    need_integer,
    need_number,
    need_object,
    need_text,
    optional_text,
    safe_id,
    write_json,
    load_json,
)

ACTIVATION_SCHEMA = "tier-bench/halo3-cell-zero-activation@1"
CANDIDATE_SCHEMA = "tier-bench/halo3-cell-zero-candidate@1"
GRADE_SCHEMA = "tier-bench/halo3-cell-zero-grade@1"
LEDGER_SCHEMA = "tier-bench/halo3-cell-zero-observation-ledger@1"

STATUSES = {"accepted", "refused"}
PRODUCER_KINDS = {"model", "controller", "human", "system"}
OBSERVER_KINDS = {"controller", "human", "sensor", "system"}
VERDICTS = {"accepted", "refused"}

FINGERPRINT_RECEIPTS = {
    "receipt-model-identity",
    "receipt-cost-runtime",
    "receipt-condition-treatment",
}
HUMAN_RECEIPT_TOKENS = (
    "human",
    "bind-event",
    "role-handoff",
    "custody-transfer",
    "human-decode",
)


def _forbid_score_fields(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower().replace("-", "_")
            if lowered in {"score", "aggregate_score", "overall_score", "leaderboard_score"}:
                raise Halo3Error(f"{path}.{key} is forbidden; HALO3 preserves family evidence")
            _forbid_score_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _forbid_score_fields(child, f"{path}[{index}]")


def _cell(plan: dict[str, Any], cell_id: str) -> tuple[str, dict[str, Any]]:
    if plan.get("schema") != PLAN_SCHEMA:
        raise Halo3Error("activation requires a compiled HALO3 plan")
    matches: list[tuple[str, dict[str, Any]]] = []
    for row in plan.get("fingerprint_cells", []):
        if row.get("cell_id") == cell_id:
            matches.append(("fingerprint", row))
    for row in plan.get("stage_cells", []):
        if row.get("cell_id") == cell_id:
            matches.append(("stage", row))
    if len(matches) != 1:
        raise Halo3Error(f"cell {cell_id} must resolve exactly once")
    return matches[0]


def _stage_receipts(cell: dict[str, Any]) -> list[str]:
    receipts: set[str] = set()
    for claim in cell["claims"]:
        receipts.update(claim["required_receipts"])
    return sorted(receipts)


def compile_activation(plan: dict[str, Any], cell_id: str) -> dict[str, Any]:
    cell_class, cell = _cell(plan, cell_id)
    if cell_class == "fingerprint":
        required_identity_fields = list(cell["required_identity_fields"])
        identity_mode = cell["identity_mode"]
        required_metrics = list(cell["required_metrics"])
        required_receipt_ids = sorted(FINGERPRINT_RECEIPTS)
        minimum_trials = int(cell["minimum_trials"])
        model_id = cell["model_id"]
        family_id = cell["family_id"]
        condition_id = cell["condition_id"]
        stage_id = None
        acceptance_text = cell["hidden_acceptance"]
        negative_controls = cell["negative_controls"]
        physical_outcome_required = False
        independent_evidence_required = True
    else:
        required_identity_fields = []
        identity_mode = None
        required_metrics = list(cell["required_metrics"])
        required_receipt_ids = _stage_receipts(cell)
        minimum_trials = 1
        model_id = None
        family_id = None
        condition_id = None
        stage_id = cell["stage_id"]
        acceptance_text = cell["acceptance"]
        negative_controls = [claim["negative_control"] for claim in cell["claims"]]
        physical_outcome_required = cell["kind"] == "physical"
        independent_evidence_required = True

    body = {
        "schema": ACTIVATION_SCHEMA,
        "plan_id": plan["plan_id"],
        "plan_sha256": hash_json(plan),
        "cell_id": cell_id,
        "cell_class": cell_class,
        "model_id": model_id,
        "family_id": family_id,
        "condition_id": condition_id,
        "stage_id": stage_id,
        "identity_mode": identity_mode,
        "required_identity_fields": required_identity_fields,
        "required_metrics": required_metrics,
        "required_receipt_ids": required_receipt_ids,
        "minimum_trials": minimum_trials,
        "acceptance_contract_sha256": hash_json(acceptance_text),
        "negative_control_sha256s": sorted(hash_json(item) for item in negative_controls),
        "physical_outcome_required": physical_outcome_required,
        "independent_evidence_required": independent_evidence_required,
        "authority": {
            "candidate_ceiling": "candidate_only",
            "acceptance_owner": "deterministic-controller",
            "human_events_remain_human_owned": True,
        },
        "production_claim": False,
        "promotion_authorized": False,
    }
    return {"activation_id": f"halo3activation1_{hash_json(body)}", **body}


def validate_activation(plan: dict[str, Any], candidate: Any) -> dict[str, Any]:
    row = need_object(candidate, "activation")
    cell_id = safe_id(row.get("cell_id"), "activation.cell_id")
    expected = compile_activation(plan, cell_id)
    if canonical_bytes(row) != canonical_bytes(expected):
        raise Halo3Error("activation differs from deterministic compilation")
    return expected


def _identity_value(field: str, value: Any, label: str) -> Any:
    if field == "shard-sha256s":
        rows = need_array(value, label, nonempty=True)
        digests = [need_digest(item, f"{label}[]") for item in rows]
        if len(digests) != len(set(digests)):
            raise Halo3Error(f"{label} contains duplicate shard digests")
        return digests
    if field.endswith("-sha256"):
        return need_digest(value, label)
    if field in {"latency-ms", "observed-cost-usd"}:
        return need_number(value, label, low=0)
    if isinstance(value, bool) or value is None:
        raise Halo3Error(f"{label} must contain a concrete identity value")
    if isinstance(value, str):
        return need_text(value, label, limit=4000)
    if isinstance(value, (int, float)):
        return need_number(value, label, low=0)
    if isinstance(value, list):
        if not value:
            raise Halo3Error(f"{label} must not be empty")
        result = []
        for index, item in enumerate(value):
            if isinstance(item, bool) or item is None:
                raise Halo3Error(f"{label}[{index}] must contain a concrete value")
            if isinstance(item, str):
                result.append(need_text(item, f"{label}[{index}]", limit=4000))
            elif isinstance(item, (int, float)):
                result.append(need_number(item, f"{label}[{index}]", low=0))
            else:
                raise Halo3Error(f"{label}[{index}] has unsupported value type")
        return result
    raise Halo3Error(f"{label} has unsupported identity value type")


def _metrics(value: Any, activation: dict[str, Any]) -> dict[str, float | int]:
    row = need_object(value, "candidate.metrics")
    required = set(activation["required_metrics"])
    if set(row) != required:
        missing = sorted(required - row.keys())
        extra = sorted(row.keys() - required)
        raise Halo3Error(f"candidate.metrics mismatch: missing={missing} extra={extra}")
    result: dict[str, float | int] = {}
    integer_metrics = {
        "accepted",
        "accepted-products",
        "consequential-miss",
        "consequential-misses",
        "critical-escaped-defects",
        "model-calls",
        "operator-interventions",
        "operator-interruptions",
        "manual-translations",
        "role-seconds-served",
    }
    for key in sorted(row):
        if key in integer_metrics:
            result[key] = need_integer(row[key], f"candidate.metrics.{key}", 0)
        else:
            result[key] = need_number(row[key], f"candidate.metrics.{key}", low=0)
    if "accepted" in result and result["accepted"] not in {0, 1}:
        raise Halo3Error("candidate.metrics.accepted must be 0 or 1")
    if "consequential-miss" in result and result["consequential-miss"] not in {0, 1}:
        raise Halo3Error("candidate.metrics.consequential-miss must be 0 or 1")
    return result


def _evidence_item(value: Any, index: int) -> dict[str, Any]:
    row = need_object(value, f"candidate.evidence[{index}]")
    exact_keys(
        row,
        {"id", "kind", "sha256", "observer", "observer_kind", "independent", "uri"},
        set(),
        f"candidate.evidence[{index}]",
    )
    observer_kind = need_text(
        row["observer_kind"], f"candidate.evidence[{index}].observer_kind", limit=80
    )
    if observer_kind not in OBSERVER_KINDS:
        raise Halo3Error(f"candidate.evidence[{index}].observer_kind is invalid")
    return {
        "id": safe_id(row["id"], f"candidate.evidence[{index}].id"),
        "kind": safe_id(row["kind"], f"candidate.evidence[{index}].kind"),
        "sha256": need_digest(row["sha256"], f"candidate.evidence[{index}].sha256"),
        "observer": safe_id(row["observer"], f"candidate.evidence[{index}].observer"),
        "observer_kind": observer_kind,
        "independent": need_boolean(
            row["independent"], f"candidate.evidence[{index}].independent"
        ),
        "uri": optional_text(row["uri"], f"candidate.evidence[{index}].uri", limit=2000),
    }


def _candidate_body(activation: dict[str, Any], raw: Any) -> dict[str, Any]:
    row = need_object(raw, "candidate payload")
    exact_keys(
        row,
        {
            "producer",
            "identity",
            "trial_count",
            "task_input_sha256",
            "candidate_output_sha256",
            "metrics",
            "outcomes",
            "evidence",
            "production_claim",
        },
        set(),
        "candidate payload",
    )
    _forbid_score_fields(row)
    producer = need_object(row["producer"], "candidate.producer")
    exact_keys(
        producer,
        {"id", "kind", "authority"},
        set(),
        "candidate.producer",
    )
    producer_kind = need_text(producer["kind"], "candidate.producer.kind", limit=80)
    if producer_kind not in PRODUCER_KINDS:
        raise Halo3Error("candidate.producer.kind is invalid")
    if producer["authority"] != "candidate_only":
        raise Halo3Error("candidate producer must remain candidate_only")
    normalized_producer = {
        "id": safe_id(producer["id"], "candidate.producer.id"),
        "kind": producer_kind,
        "authority": "candidate_only",
    }
    if activation["cell_class"] == "fingerprint":
        if normalized_producer["id"] != activation["model_id"]:
            raise Halo3Error("fingerprint candidate producer must equal the activated model")
        if activation["model_id"] != "deterministic-control" and producer_kind != "model":
            raise Halo3Error("frontier fingerprint candidates must use producer.kind=model")
        if activation["model_id"] == "deterministic-control" and producer_kind != "controller":
            raise Halo3Error("deterministic control must use producer.kind=controller")

    identity_raw = need_object(row["identity"], "candidate.identity")
    required_identity = set(activation["required_identity_fields"])
    if set(identity_raw) != required_identity:
        missing = sorted(required_identity - identity_raw.keys())
        extra = sorted(identity_raw.keys() - required_identity)
        raise Halo3Error(f"candidate.identity mismatch: missing={missing} extra={extra}")
    identity = {
        key: _identity_value(key, identity_raw[key], f"candidate.identity.{key}")
        for key in sorted(identity_raw)
    }

    evidence_rows = [
        _evidence_item(item, index)
        for index, item in enumerate(need_array(row["evidence"], "candidate.evidence"))
    ]
    evidence_by_id = {item["id"]: item for item in evidence_rows}
    if len(evidence_by_id) != len(evidence_rows):
        raise Halo3Error("candidate.evidence contains duplicate ids")
    missing_receipts = sorted(
        set(activation["required_receipt_ids"]) - evidence_by_id.keys()
    )
    if missing_receipts:
        raise Halo3Error(f"candidate.evidence is missing required receipts: {missing_receipts}")

    outcomes = need_object(row["outcomes"], "candidate.outcomes")
    if not outcomes:
        raise Halo3Error("candidate.outcomes must not be empty")
    _forbid_score_fields(outcomes, "$.candidate.outcomes")

    if need_boolean(row["production_claim"], "candidate.production_claim"):
        raise Halo3Error("candidate may not make a production claim")

    trial_count = need_integer(row["trial_count"], "candidate.trial_count", 1)
    if trial_count < activation["minimum_trials"]:
        raise Halo3Error(
            f"candidate.trial_count must be at least {activation['minimum_trials']}"
        )

    return {
        "schema": CANDIDATE_SCHEMA,
        "activation_id": activation["activation_id"],
        "plan_id": activation["plan_id"],
        "cell_id": activation["cell_id"],
        "producer": normalized_producer,
        "identity": identity,
        "trial_count": trial_count,
        "task_input_sha256": need_digest(
            row["task_input_sha256"], "candidate.task_input_sha256"
        ),
        "candidate_output_sha256": need_digest(
            row["candidate_output_sha256"], "candidate.candidate_output_sha256"
        ),
        "metrics": _metrics(row["metrics"], activation),
        "outcomes": outcomes,
        "evidence": sorted(evidence_rows, key=lambda item: item["id"]),
        "production_claim": False,
    }


def seal_candidate(activation: dict[str, Any], raw: Any) -> dict[str, Any]:
    body = _candidate_body(activation, raw)
    return {"candidate_id": f"halo3candidate1_{hash_json(body)}", **body}


def validate_candidate(activation: dict[str, Any], candidate: Any) -> dict[str, Any]:
    row = need_object(candidate, "candidate")
    exact_keys(
        row,
        {
            "candidate_id",
            "schema",
            "activation_id",
            "plan_id",
            "cell_id",
            "producer",
            "identity",
            "trial_count",
            "task_input_sha256",
            "candidate_output_sha256",
            "metrics",
            "outcomes",
            "evidence",
            "production_claim",
        },
        set(),
        "candidate",
    )
    if row["schema"] != CANDIDATE_SCHEMA:
        raise Halo3Error(f"candidate schema must be {CANDIDATE_SCHEMA}")
    payload = {
        key: row[key]
        for key in (
            "producer",
            "identity",
            "trial_count",
            "task_input_sha256",
            "candidate_output_sha256",
            "metrics",
            "outcomes",
            "evidence",
            "production_claim",
        )
    }
    expected = seal_candidate(activation, payload)
    if canonical_bytes(row) != canonical_bytes(expected):
        raise Halo3Error("candidate differs from deterministic sealing")
    return expected


def _grade_body(
    activation: dict[str, Any],
    candidate: dict[str, Any],
    raw: Any,
) -> dict[str, Any]:
    row = need_object(raw, "grade payload")
    exact_keys(
        row,
        {
            "grader",
            "hidden_fixture_sha256",
            "verdict",
            "reasons",
            "evaluated_receipt_ids",
            "production_claim",
        },
        set(),
        "grade payload",
    )
    _forbid_score_fields(row)
    grader = need_object(row["grader"], "grade.grader")
    exact_keys(
        grader,
        {"id", "kind", "source_sha256", "independent"},
        set(),
        "grade.grader",
    )
    if grader["id"] != "evidence-node":
        raise Halo3Error("grade.grader.id must be evidence-node")
    if grader["kind"] != "controller":
        raise Halo3Error("grade.grader.kind must be controller")
    if not need_boolean(grader["independent"], "grade.grader.independent"):
        raise Halo3Error("hidden grader must be independent")
    verdict = need_text(row["verdict"], "grade.verdict", limit=40)
    if verdict not in VERDICTS:
        raise Halo3Error("grade.verdict is invalid")
    reasons = [
        need_text(item, "grade.reasons[]", limit=2000)
        for item in need_array(row["reasons"], "grade.reasons", nonempty=True)
    ]
    evaluated = sorted(
        {
            safe_id(item, "grade.evaluated_receipt_ids[]")
            for item in need_array(
                row["evaluated_receipt_ids"],
                "grade.evaluated_receipt_ids",
                nonempty=True,
            )
        }
    )
    if not set(activation["required_receipt_ids"]) <= set(evaluated):
        missing = sorted(set(activation["required_receipt_ids"]) - set(evaluated))
        raise Halo3Error(f"grade did not evaluate required receipts: {missing}")
    if need_boolean(row["production_claim"], "grade.production_claim"):
        raise Halo3Error("grade may not make a production claim")
    return {
        "schema": GRADE_SCHEMA,
        "activation_id": activation["activation_id"],
        "plan_id": activation["plan_id"],
        "cell_id": activation["cell_id"],
        "candidate_id": candidate["candidate_id"],
        "candidate_sha256": hash_json(candidate),
        "grader": {
            "id": "evidence-node",
            "kind": "controller",
            "source_sha256": need_digest(
                grader["source_sha256"], "grade.grader.source_sha256"
            ),
            "independent": True,
        },
        "hidden_fixture_sha256": need_digest(
            row["hidden_fixture_sha256"], "grade.hidden_fixture_sha256"
        ),
        "verdict": verdict,
        "reasons": reasons,
        "evaluated_receipt_ids": evaluated,
        "production_claim": False,
    }


def seal_grade(
    activation: dict[str, Any],
    candidate: dict[str, Any],
    raw: Any,
) -> dict[str, Any]:
    validate_candidate(activation, candidate)
    body = _grade_body(activation, candidate, raw)
    return {"grade_id": f"halo3grade1_{hash_json(body)}", **body}


def validate_grade(
    activation: dict[str, Any],
    candidate: dict[str, Any],
    grade: Any,
) -> dict[str, Any]:
    row = need_object(grade, "grade")
    exact_keys(
        row,
        {
            "grade_id",
            "schema",
            "activation_id",
            "plan_id",
            "cell_id",
            "candidate_id",
            "candidate_sha256",
            "grader",
            "hidden_fixture_sha256",
            "verdict",
            "reasons",
            "evaluated_receipt_ids",
            "production_claim",
        },
        set(),
        "grade",
    )
    if row["schema"] != GRADE_SCHEMA:
        raise Halo3Error(f"grade schema must be {GRADE_SCHEMA}")
    payload = {
        key: row[key]
        for key in (
            "grader",
            "hidden_fixture_sha256",
            "verdict",
            "reasons",
            "evaluated_receipt_ids",
            "production_claim",
        )
    }
    expected = seal_grade(activation, candidate, payload)
    if canonical_bytes(row) != canonical_bytes(expected):
        raise Halo3Error("grade differs from deterministic sealing")
    return expected


def _accepted_metrics(activation: dict[str, Any], candidate: dict[str, Any]) -> None:
    metrics = candidate["metrics"]
    if activation["cell_class"] == "fingerprint":
        if metrics["accepted"] != 1:
            raise Halo3Error("accepted fingerprint requires metrics.accepted=1")
        if metrics["consequential-miss"] != 0:
            raise Halo3Error("accepted fingerprint requires no consequential miss")
        if metrics["critical-escaped-defects"] != 0:
            raise Halo3Error("accepted fingerprint requires no critical escaped defects")
    else:
        if metrics["accepted-products"] < 1:
            raise Halo3Error("accepted stage requires at least one accepted product")
        if metrics["consequential-misses"] != 0:
            raise Halo3Error("accepted stage requires no consequential misses")


def _human_receipts(candidate: dict[str, Any], activation: dict[str, Any]) -> None:
    evidence = {item["id"]: item for item in candidate["evidence"]}
    for receipt_id in activation["required_receipt_ids"]:
        if any(token in receipt_id for token in HUMAN_RECEIPT_TOKENS):
            row = evidence[receipt_id]
            if row["observer_kind"] != "human":
                raise Halo3Error(f"{receipt_id} must remain attributed to a human")


def _independent_witness(candidate: dict[str, Any], activation: dict[str, Any]) -> None:
    if not activation["independent_evidence_required"]:
        return
    producer_id = candidate["producer"]["id"]
    if not any(
        item["independent"] and item["observer"] != producer_id
        for item in candidate["evidence"]
    ):
        raise Halo3Error("accepted observation requires independent evidence")
    if activation["physical_outcome_required"]:
        if not any(
            item["independent"]
            and (
                "physical" in item["id"]
                or "outcome" in item["kind"]
                or item["observer_kind"] == "sensor"
            )
            for item in candidate["evidence"]
        ):
            raise Halo3Error("accepted physical stage requires independent physical outcome evidence")


def admit_observation(
    plan: dict[str, Any],
    activation: dict[str, Any],
    candidate: dict[str, Any],
    grade: dict[str, Any],
) -> dict[str, Any]:
    activation = validate_activation(plan, activation)
    candidate = validate_candidate(activation, candidate)
    grade = validate_grade(activation, candidate, grade)
    status = grade["verdict"]
    if status == "accepted":
        _accepted_metrics(activation, candidate)
        _human_receipts(candidate, activation)
        _independent_witness(candidate, activation)
    body = {
        "schema": OBSERVATION_SCHEMA,
        "status": status,
        "plan_id": plan["plan_id"],
        "plan_sha256": hash_json(plan),
        "activation_id": activation["activation_id"],
        "cell_id": activation["cell_id"],
        "cell_class": activation["cell_class"],
        "identity_mode": activation["identity_mode"],
        "model_id": activation["model_id"],
        "family_id": activation["family_id"],
        "condition_id": activation["condition_id"],
        "stage_id": activation["stage_id"],
        "metrics": candidate["metrics"],
        "outcomes": candidate["outcomes"],
        "receipts": candidate["evidence"],
        "candidate": candidate,
        "grade": grade,
        "accepted_by": "deterministic-controller",
        "production_claim": False,
        "promotion_authorized": False,
    }
    return {"observation_id": f"halo3observation1_{hash_json(body)}", **body}


def validate_observation(plan: dict[str, Any], observation: Any) -> dict[str, Any]:
    row = need_object(observation, "observation")
    exact_keys(
        row,
        {
            "observation_id",
            "schema",
            "status",
            "plan_id",
            "plan_sha256",
            "activation_id",
            "cell_id",
            "cell_class",
            "identity_mode",
            "model_id",
            "family_id",
            "condition_id",
            "stage_id",
            "metrics",
            "outcomes",
            "receipts",
            "candidate",
            "grade",
            "accepted_by",
            "production_claim",
            "promotion_authorized",
        },
        set(),
        "observation",
    )
    if row["schema"] != OBSERVATION_SCHEMA:
        raise Halo3Error(f"observation schema must be {OBSERVATION_SCHEMA}")
    if row["status"] not in STATUSES:
        raise Halo3Error("observation.status is invalid")
    activation = compile_activation(plan, safe_id(row["cell_id"], "observation.cell_id"))
    expected = admit_observation(plan, activation, row["candidate"], row["grade"])
    if canonical_bytes(row) != canonical_bytes(expected):
        raise Halo3Error("observation differs from deterministic admission")
    return expected


def compile_ledger(plan: dict[str, Any], observations: Iterable[Any]) -> dict[str, Any]:
    if plan.get("schema") != PLAN_SCHEMA:
        raise Halo3Error("ledger requires a compiled HALO3 plan")
    validated: dict[str, dict[str, Any]] = {}
    for raw in observations:
        row = validate_observation(plan, raw)
        existing = validated.get(row["cell_id"])
        if existing is not None and canonical_bytes(existing) != canonical_bytes(row):
            raise Halo3Error(f"conflicting observations for cell {row['cell_id']}")
        validated[row["cell_id"]] = row

    all_cells = {
        row["cell_id"]: ("fingerprint", row)
        for row in plan["fingerprint_cells"]
    }
    all_cells.update(
        {row["cell_id"]: ("stage", row) for row in plan["stage_cells"]}
    )
    unknown = sorted(set(validated) - set(all_cells))
    if unknown:
        raise Halo3Error(f"observations reference unknown cells: {unknown}")

    missing = sorted(set(all_cells) - set(validated))
    accepted = sum(row["status"] == "accepted" for row in validated.values())
    refused = sum(row["status"] == "refused" for row in validated.values())
    fingerprint_rows = [
        row for row in validated.values() if row["cell_class"] == "fingerprint"
    ]
    stage_rows = [row for row in validated.values() if row["cell_class"] == "stage"]
    body = {
        "schema": LEDGER_SCHEMA,
        "plan_id": plan["plan_id"],
        "plan_sha256": hash_json(plan),
        "observations": [validated[key] for key in sorted(validated)],
        "coverage": {
            "total_cells": len(all_cells),
            "measured_cells": len(validated),
            "accepted_cells": accepted,
            "refused_cells": refused,
            "unmeasured_cells": len(missing),
            "fingerprint_measured": len(fingerprint_rows),
            "stage_measured": len(stage_rows),
        },
        "missing_cell_ids": missing,
        "complete": not missing,
        "production_claim": False,
        "promotion_authorized": False,
    }
    _forbid_score_fields(body)
    return {"ledger_id": f"halo3ledger1_{hash_json(body)}", **body}


def _load_observations(paths: list[Path]) -> list[Any]:
    result: list[Any] = []
    for path in paths:
        value = load_json(path)
        if isinstance(value, list):
            result.extend(value)
        else:
            result.append(value)
    return result


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="tierhalo3obs",
        description=(
            "Freeze HALO3 cell activations, seal candidate and hidden-grade receipts, "
            "admit accepted or refused observations, and compile a no-leaderboard ledger."
        ),
    )
    commands = root.add_subparsers(dest="command", required=True)

    activate = commands.add_parser("activate")
    activate.add_argument("--plan", type=Path, required=True)
    activate.add_argument("--cell-id", required=True)
    activate.add_argument("--out", type=Path)

    seal_candidate_command = commands.add_parser("seal-candidate")
    seal_candidate_command.add_argument("--activation", type=Path, required=True)
    seal_candidate_command.add_argument("--payload", type=Path, required=True)
    seal_candidate_command.add_argument("--out", type=Path)

    seal_grade_command = commands.add_parser("seal-grade")
    seal_grade_command.add_argument("--activation", type=Path, required=True)
    seal_grade_command.add_argument("--candidate", type=Path, required=True)
    seal_grade_command.add_argument("--payload", type=Path, required=True)
    seal_grade_command.add_argument("--out", type=Path)

    admit = commands.add_parser("admit")
    admit.add_argument("--plan", type=Path, required=True)
    admit.add_argument("--activation", type=Path, required=True)
    admit.add_argument("--candidate", type=Path, required=True)
    admit.add_argument("--grade", type=Path, required=True)
    admit.add_argument("--out", type=Path)

    verify = commands.add_parser("verify-observation")
    verify.add_argument("--plan", type=Path, required=True)
    verify.add_argument("--observation", type=Path, required=True)

    ledger = commands.add_parser("ledger")
    ledger.add_argument("--plan", type=Path, required=True)
    ledger.add_argument("--observation", type=Path, action="append", default=[])
    ledger.add_argument("--out", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "activate":
            write_json(args.out, compile_activation(load_json(args.plan), args.cell_id))
            return 0
        if args.command == "seal-candidate":
            write_json(
                args.out,
                seal_candidate(load_json(args.activation), load_json(args.payload)),
            )
            return 0
        if args.command == "seal-grade":
            write_json(
                args.out,
                seal_grade(
                    load_json(args.activation),
                    load_json(args.candidate),
                    load_json(args.payload),
                ),
            )
            return 0
        if args.command == "admit":
            write_json(
                args.out,
                admit_observation(
                    load_json(args.plan),
                    load_json(args.activation),
                    load_json(args.candidate),
                    load_json(args.grade),
                ),
            )
            return 0
        if args.command == "verify-observation":
            observation = validate_observation(
                load_json(args.plan), load_json(args.observation)
            )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "observation_id": observation["observation_id"],
                        "cell_id": observation["cell_id"],
                        "status": observation["status"],
                        "production_claim": False,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "ledger":
            write_json(
                args.out,
                compile_ledger(
                    load_json(args.plan), _load_observations(args.observation)
                ),
            )
            return 0
    except (Halo3Error, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"tierhalo3obs: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
