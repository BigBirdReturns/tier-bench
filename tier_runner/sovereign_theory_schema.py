"""Validation for the Sovereign Theory Lab."""
from __future__ import annotations

from typing import Any

from .sovereign_common import (
    PlaneError,
    need_array,
    need_boolean,
    need_digest,
    need_integer,
    need_number,
    need_object,
    need_text,
    safe_id,
)
from .sovereign_theory_common import (
    ACCEPTANCE_CLASSES,
    AGGREGATES,
    ARM_ROLES,
    DIRECTIONS,
    LAB_SCHEMA,
    METRIC_KINDS,
    PREDICATE_OPS,
    TASK_STATUSES,
    THEORY_STATUSES,
    normalized_settings,
    required_metric_name,
    required_text_list,
)


def _metric(raw: Any, index: int) -> dict[str, Any]:
    row = need_object(raw, f"metrics[{index}]")
    identifier = required_metric_name(row.get("id"), f"metrics[{index}].id")
    kind = row.get("kind")
    direction = row.get("direction")
    if kind not in METRIC_KINDS:
        raise PlaneError(f"metric {identifier}.kind must be one of {sorted(METRIC_KINDS)}")
    if direction not in DIRECTIONS:
        raise PlaneError(f"metric {identifier}.direction must be one of {sorted(DIRECTIONS)}")
    required = row.get("required", False)
    need_boolean(required, f"metric {identifier}.required")
    unit = need_text(row.get("unit", "unitless"), f"metric {identifier}.unit", limit=80)
    description = need_text(
        row.get("description", identifier), f"metric {identifier}.description", limit=1000
    )
    return {
        "id": identifier,
        "kind": kind,
        "direction": direction,
        "required": required,
        "unit": unit,
        "description": description,
    }


def _task(raw: Any, index: int) -> dict[str, Any]:
    row = need_object(raw, f"tasks[{index}]")
    identifier = safe_id(row.get("id"), f"tasks[{index}].id", limit=100)
    family = safe_id(row.get("family"), f"task {identifier}.family", limit=100)
    status = row.get("status")
    if status not in TASK_STATUSES:
        raise PlaneError(f"task {identifier}.status must be one of {sorted(TASK_STATUSES)}")
    acceptance = row.get("acceptance_class")
    if acceptance not in ACCEPTANCE_CLASSES:
        raise PlaneError(
            f"task {identifier}.acceptance_class must be one of {sorted(ACCEPTANCE_CLASSES)}"
        )
    source = need_text(row.get("source"), f"task {identifier}.source", limit=500)
    return {
        "id": identifier,
        "title": need_text(row.get("title"), f"task {identifier}.title", limit=200),
        "family": family,
        "status": status,
        "acceptance_class": acceptance,
        "source": source,
        "selection_contract": need_text(
            row.get("selection_contract", "prospectively frozen"),
            f"task {identifier}.selection_contract",
            limit=1500,
        ),
        "tags": sorted(
            set(required_text_list(row.get("tags", []), f"task {identifier}.tags", allow_empty=True))
        ),
    }


def _arm(raw: Any, theory_id: str, index: int) -> dict[str, Any]:
    row = need_object(raw, f"theory {theory_id}.arms[{index}]")
    identifier = safe_id(row.get("id"), f"theory {theory_id}.arms[{index}].id", limit=80)
    role = row.get("role")
    if role not in ARM_ROLES:
        raise PlaneError(f"theory {theory_id} arm {identifier}.role must be one of {sorted(ARM_ROLES)}")
    return {
        "id": identifier,
        "label": need_text(
            row.get("label", identifier), f"theory {theory_id} arm {identifier}.label", limit=200
        ),
        "role": role,
        "settings": normalized_settings(row.get("settings", {})),
        "resource_hints": sorted(
            set(
                required_text_list(
                    row.get("resource_hints", []),
                    f"theory {theory_id} arm {identifier}.resource_hints",
                    allow_empty=True,
                )
            )
        ),
    }


def _predicate(
    raw: Any,
    label: str,
    metrics: set[str],
    treatment_ids: set[str],
) -> dict[str, Any]:
    row = need_object(raw, label)
    metric = required_metric_name(row.get("metric"), f"{label}.metric")
    if metric != "pass_rate" and metric not in metrics:
        raise PlaneError(f"{label}.metric references unknown metric {metric}")
    aggregate_kind = row.get("aggregate", "rate" if metric == "pass_rate" else "median")
    if aggregate_kind not in AGGREGATES:
        raise PlaneError(f"{label}.aggregate must be one of {sorted(AGGREGATES)}")
    op = row.get("op")
    if op not in PREDICATE_OPS:
        raise PlaneError(f"{label}.op must be one of {sorted(PREDICATE_OPS)}")
    value = row.get("value")
    if op in {"gte", "lte", "gt", "lt", "eq", "ratio_gte_control", "ratio_lte_control",
              "delta_gte_control", "delta_lte_control"}:
        value = need_number(value, f"{label}.value", -10**12, 10**12)
    elif value is not None:
        raise PlaneError(f"{label}.value is only allowed for absolute, ratio, or delta operators")
    arm = row.get("arm")
    if arm is not None:
        arm = safe_id(arm, f"{label}.arm", limit=80)
        if arm not in treatment_ids:
            raise PlaneError(f"{label}.arm references unknown treatment {arm}")
    return {
        "metric": metric,
        "aggregate": aggregate_kind,
        "op": op,
        "value": value,
        "arm": arm,
        "note": need_text(row.get("note", f"{metric} {op}"), f"{label}.note", limit=500),
    }


def _theory(raw: Any, index: int, metric_ids: set[str], task_families: set[str]) -> dict[str, Any]:
    row = need_object(raw, f"theories[{index}]")
    identifier = safe_id(row.get("id"), f"theories[{index}].id", limit=100)
    status = row.get("status", "hypothesis")
    if status not in THEORY_STATUSES:
        raise PlaneError(f"theory {identifier}.status must be one of {sorted(THEORY_STATUSES)}")
    arms = [_arm(value, identifier, i) for i, value in enumerate(
        need_array(row.get("arms"), f"theory {identifier}.arms", nonempty=True)
    )]
    arm_ids = [arm["id"] for arm in arms]
    if len(set(arm_ids)) != len(arm_ids):
        raise PlaneError(f"theory {identifier} has duplicate arm ids")
    controls = [arm for arm in arms if arm["role"] == "control"]
    treatments = [arm for arm in arms if arm["role"] == "treatment"]
    if len(controls) != 1:
        raise PlaneError(f"theory {identifier} must have exactly one control arm")
    if not treatments:
        raise PlaneError(f"theory {identifier} must have at least one treatment arm")
    control_id = controls[0]["id"]
    treatment_ids = {arm["id"] for arm in treatments}

    families = sorted(
        set(required_text_list(row.get("task_families"), f"theory {identifier}.task_families"))
    )
    missing = set(families) - task_families
    if missing:
        raise PlaneError(f"theory {identifier} references unknown task families: {sorted(missing)}")

    support = [
        _predicate(value, f"theory {identifier}.support[{i}]", metric_ids, treatment_ids)
        for i, value in enumerate(
            need_array(row.get("support"), f"theory {identifier}.support", nonempty=True)
        )
    ]
    falsify = [
        _predicate(value, f"theory {identifier}.falsify[{i}]", metric_ids, treatment_ids)
        for i, value in enumerate(
            need_array(row.get("falsify"), f"theory {identifier}.falsify", nonempty=True)
        )
    ]
    replicates = need_integer(
        row.get("replicates_per_cell", 3),
        f"theory {identifier}.replicates_per_cell",
        1,
        20,
    )
    minimum_tasks = need_integer(
        row.get("minimum_distinct_tasks", 3),
        f"theory {identifier}.minimum_distinct_tasks",
        1,
        1000,
    )
    return {
        "id": identifier,
        "title": need_text(row.get("title"), f"theory {identifier}.title", limit=250),
        "status": status,
        "priority": need_integer(row.get("priority", 50), f"theory {identifier}.priority", 0, 100),
        "claim": need_text(row.get("claim"), f"theory {identifier}.claim", limit=2500),
        "mechanism": need_text(row.get("mechanism"), f"theory {identifier}.mechanism", limit=3500),
        "prediction": need_text(row.get("prediction"), f"theory {identifier}.prediction", limit=2000),
        "control_arm": control_id,
        "arms": arms,
        "task_families": families,
        "minimum_distinct_tasks": minimum_tasks,
        "replicates_per_cell": replicates,
        "support": support,
        "falsify": falsify,
        "confounds": required_text_list(
            row.get("confounds"), f"theory {identifier}.confounds"
        ),
        "falsifier": need_text(
            row.get("falsifier"), f"theory {identifier}.falsifier", limit=1500
        ),
        "failure_default": need_text(
            row.get("failure_default", "PARTIAL; preserve the open question."),
            f"theory {identifier}.failure_default",
            limit=1000,
        ),
    }


def validate_lab(raw: Any) -> dict[str, Any]:
    lab = need_object(raw, "theory lab")
    if lab.get("schema") != LAB_SCHEMA:
        raise PlaneError(f"theory lab schema must be {LAB_SCHEMA}")
    metrics = [_metric(value, index) for index, value in enumerate(
        need_array(lab.get("metrics"), "metrics", nonempty=True)
    )]
    metric_ids = [row["id"] for row in metrics]
    if len(set(metric_ids)) != len(metric_ids):
        raise PlaneError("duplicate metric id")
    tasks = [_task(value, index) for index, value in enumerate(
        need_array(lab.get("tasks"), "tasks", nonempty=True)
    )]
    task_ids = [row["id"] for row in tasks]
    if len(set(task_ids)) != len(task_ids):
        raise PlaneError("duplicate task id")
    families = {row["family"] for row in tasks}
    theories = [_theory(value, index, set(metric_ids), families) for index, value in enumerate(
        need_array(lab.get("theories"), "theories", nonempty=True)
    )]
    theory_ids = [row["id"] for row in theories]
    if len(set(theory_ids)) != len(theory_ids):
        raise PlaneError("duplicate theory id")
    laws = required_text_list(lab.get("laws"), "laws")
    return {
        "schema": LAB_SCHEMA,
        "id": safe_id(lab.get("id"), "lab.id", limit=100),
        "title": need_text(lab.get("title"), "lab.title", limit=250),
        "objective": need_text(lab.get("objective"), "lab.objective", limit=2000),
        "laws": laws,
        "metrics": metrics,
        "tasks": tasks,
        "theories": sorted(theories, key=lambda row: (-row["priority"], row["id"])),
    }


def validate_observation(raw: Any, lab: dict[str, Any]) -> dict[str, Any]:
    row = need_object(raw, "observation")
    if row.get("schema") != "tier-bench/sovereign-theory-observation@1":
        raise PlaneError("observation schema mismatch")
    theories = {value["id"]: value for value in lab["theories"]}
    theory_id = safe_id(row.get("theory_id"), "observation.theory_id", limit=100)
    if theory_id not in theories:
        raise PlaneError(f"observation references unknown theory {theory_id}")
    theory = theories[theory_id]
    arms = {value["id"] for value in theory["arms"]}
    arm_id = safe_id(row.get("arm_id"), "observation.arm_id", limit=80)
    if arm_id not in arms:
        raise PlaneError(f"observation references unknown arm {arm_id}")
    tasks = {value["id"]: value for value in lab["tasks"]}
    task_id = safe_id(row.get("task_id"), "observation.task_id", limit=100)
    if task_id not in tasks:
        raise PlaneError(f"observation references unknown task {task_id}")
    if tasks[task_id]["family"] not in theory["task_families"]:
        raise PlaneError(f"task {task_id} is outside theory {theory_id}'s families")
    outcome = row.get("outcome")
    if outcome not in {"pass", "fail", "error", "partial"}:
        raise PlaneError("observation.outcome must be pass, fail, error, or partial")
    runtime = need_object(row.get("runtime"), "observation.runtime")
    attested = need_boolean(runtime.get("attested"), "observation.runtime.attested")
    requested = need_text(runtime.get("requested"), "observation.runtime.requested", limit=200)
    observed = need_text(runtime.get("observed"), "observation.runtime.observed", limit=200)
    metrics = need_object(row.get("metrics"), "observation.metrics")
    metric_defs = {value["id"]: value for value in lab["metrics"]}
    unknown = set(metrics) - set(metric_defs)
    if unknown:
        raise PlaneError(f"observation has unknown metrics: {sorted(unknown)}")
    normalized_metrics: dict[str, float] = {}
    for identifier, value in metrics.items():
        kind = metric_defs[identifier]["kind"]
        if kind == "boolean":
            normalized_metrics[identifier] = 1.0 if need_boolean(
                value, f"observation.metrics.{identifier}"
            ) else 0.0
        elif kind == "count":
            normalized_metrics[identifier] = float(
                need_integer(value, f"observation.metrics.{identifier}", 0, 10**15)
            )
        else:
            normalized_metrics[identifier] = need_number(
                value, f"observation.metrics.{identifier}", -10**15, 10**15
            )
    if outcome in {"pass", "fail"}:
        for metric in lab["metrics"]:
            if metric["required"] and metric["id"] not in normalized_metrics:
                raise PlaneError(
                    f"decisive observation is missing required metric {metric['id']}"
                )
    return {
        "schema": "tier-bench/sovereign-theory-observation@1",
        "theory_id": theory_id,
        "run_id": safe_id(row.get("run_id"), "observation.run_id", limit=160),
        "task_id": task_id,
        "arm_id": arm_id,
        "replicate": need_integer(row.get("replicate"), "observation.replicate", 1, 1000),
        "outcome": outcome,
        "runtime": {
            "requested": requested,
            "observed": observed,
            "attested": attested,
            "telemetry_complete": need_boolean(
                runtime.get("telemetry_complete"),
                "observation.runtime.telemetry_complete",
            ),
        },
        "metrics": normalized_metrics,
        "receipt_sha256": need_digest(
            row.get("receipt_sha256"), "observation.receipt_sha256"
        ),
        "notes": need_text(row.get("notes", "none"), "observation.notes", limit=2000),
    }
