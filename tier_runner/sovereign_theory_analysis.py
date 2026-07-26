"""Analyze sealed Sovereign Theory Lab observations."""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from typing import Any, Iterable

from .sovereign_common import PlaneError, hash_json, now
from .sovereign_theory_common import REPORT_SCHEMA, aggregate, metric_key
from .sovereign_theory_schema import validate_lab, validate_observation


def load_observations(path: Path) -> list[Any]:
    rows: list[Any] = []
    try:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise PlaneError(f"invalid JSONL at {path}:{number}: {exc}") from exc
    except OSError as exc:
        raise PlaneError(f"cannot read observations from {path}: {exc}") from exc
    return rows


def _decisive(row: dict[str, Any]) -> bool:
    runtime = row["runtime"]
    return bool(
        row["outcome"] in {"pass", "fail"}
        and runtime["attested"]
        and runtime["telemetry_complete"]
        and runtime["requested"] == runtime["observed"]
    )


def _arm_summary(
    rows: list[dict[str, Any]], metric_defs: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    decisive = [row for row in rows if _decisive(row)]
    passes = sum(row["outcome"] == "pass" for row in decisive)
    failures = sum(row["outcome"] == "fail" for row in decisive)
    contaminated = [row for row in rows if not _decisive(row)]
    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in decisive:
        by_task[row["task_id"]].append(row)
    metrics: dict[str, float] = {
        metric_key("pass_rate", "rate"): passes / len(decisive) if decisive else 0.0
    }
    metric_coverage: dict[str, int] = {}
    for metric_id in metric_defs:
        values = [
            row["metrics"][metric_id]
            for row in decisive
            if metric_id in row["metrics"]
        ]
        metric_coverage[metric_id] = len(values)
        if not values:
            continue
        for kind in ("mean", "median", "sum", "min", "max", "p95"):
            metrics[metric_key(metric_id, kind)] = aggregate(values, kind)
        if metric_defs[metric_id]["kind"] in {"boolean", "rate"}:
            metrics[metric_key(metric_id, "rate")] = aggregate(values, "rate")
    return {
        "observations": len(rows),
        "decisive": len(decisive),
        "passes": passes,
        "failures": failures,
        "contaminated": len(contaminated),
        "distinct_tasks": len(by_task),
        "task_replicates": {
            task_id: len(task_rows) for task_id, task_rows in sorted(by_task.items())
        },
        "metrics": metrics,
        "metric_coverage": metric_coverage,
        "contamination": [
            {
                "run_id": row["run_id"],
                "task_id": row["task_id"],
                "outcome": row["outcome"],
                "requested": row["runtime"]["requested"],
                "observed": row["runtime"]["observed"],
                "attested": row["runtime"]["attested"],
                "telemetry_complete": row["runtime"]["telemetry_complete"],
            }
            for row in contaminated
        ],
    }


def _value(summary: dict[str, Any], metric: str, aggregate_kind: str) -> float | None:
    return summary["metrics"].get(metric_key(metric, aggregate_kind))


def _predicate_result(
    predicate: dict[str, Any],
    treatment: dict[str, Any],
    control: dict[str, Any],
) -> dict[str, Any]:
    metric = predicate["metric"]
    aggregate_kind = predicate["aggregate"]
    left = _value(treatment, metric, aggregate_kind)
    right = _value(control, metric, aggregate_kind)
    op = predicate["op"]
    threshold = predicate.get("value")
    if left is None:
        return {
            "ok": None,
            "metric": metric,
            "aggregate": aggregate_kind,
            "op": op,
            "left": None,
            "right": right,
            "threshold": threshold,
            "note": predicate["note"],
            "reason": "treatment metric missing",
        }
    if "control" in op and right is None:
        return {
            "ok": None,
            "metric": metric,
            "aggregate": aggregate_kind,
            "op": op,
            "left": left,
            "right": None,
            "threshold": threshold,
            "note": predicate["note"],
            "reason": "control metric missing",
        }

    if op == "gte":
        ok = left >= float(threshold)
    elif op == "lte":
        ok = left <= float(threshold)
    elif op == "gt":
        ok = left > float(threshold)
    elif op == "lt":
        ok = left < float(threshold)
    elif op == "eq":
        ok = left == float(threshold)
    elif op == "gte_control":
        ok = left >= float(right)
    elif op == "lte_control":
        ok = left <= float(right)
    elif op == "gt_control":
        ok = left > float(right)
    elif op == "lt_control":
        ok = left < float(right)
    elif op == "ratio_gte_control":
        ok = False if right == 0 else left / float(right) >= float(threshold)
    elif op == "ratio_lte_control":
        ok = left <= 0 if right == 0 else left / float(right) <= float(threshold)
    elif op == "delta_gte_control":
        ok = left - float(right) >= float(threshold)
    elif op == "delta_lte_control":
        ok = left - float(right) <= float(threshold)
    else:
        raise PlaneError(f"unsupported predicate operator {op}")
    return {
        "ok": ok,
        "metric": metric,
        "aggregate": aggregate_kind,
        "op": op,
        "left": left,
        "right": right,
        "threshold": threshold,
        "note": predicate["note"],
        "reason": None,
    }


def _sufficient(
    summary: dict[str, Any],
    task_ids: set[str],
    minimum_tasks: int,
    replicates: int,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if summary["distinct_tasks"] < minimum_tasks:
        reasons.append(
            f"{summary['distinct_tasks']} distinct decisive tasks < required {minimum_tasks}"
        )
    for task_id in sorted(task_ids):
        count = summary["task_replicates"].get(task_id, 0)
        if count < replicates:
            reasons.append(
                f"task {task_id} has {count} decisive replicates < required {replicates}"
            )
    return not reasons, reasons


def _treatment_verdict(
    theory: dict[str, Any],
    treatment_id: str,
    treatment: dict[str, Any],
    control: dict[str, Any],
    eligible_tasks: set[str],
) -> dict[str, Any]:
    control_ok, control_reasons = _sufficient(
        control,
        eligible_tasks,
        theory["minimum_distinct_tasks"],
        theory["replicates_per_cell"],
    )
    treatment_ok, treatment_reasons = _sufficient(
        treatment,
        eligible_tasks,
        theory["minimum_distinct_tasks"],
        theory["replicates_per_cell"],
    )
    if not control_ok or not treatment_ok:
        return {
            "arm_id": treatment_id,
            "verdict": "PARTIAL",
            "support": [],
            "falsify": [],
            "reasons": [*control_reasons, *treatment_reasons],
        }
    support_specs = [
        predicate
        for predicate in theory["support"]
        if predicate.get("arm") in (None, treatment_id)
    ]
    falsify_specs = [
        predicate
        for predicate in theory["falsify"]
        if predicate.get("arm") in (None, treatment_id)
    ]
    support = [_predicate_result(row, treatment, control) for row in support_specs]
    falsify = [_predicate_result(row, treatment, control) for row in falsify_specs]
    missing = [row for row in [*support, *falsify] if row["ok"] is None]
    if missing:
        verdict = "PARTIAL"
        reasons = [row["reason"] for row in missing if row["reason"]]
    elif any(row["ok"] for row in falsify):
        verdict = "FALSIFIED"
        reasons = ["one or more predeclared falsifiers cleared"]
    elif support and all(row["ok"] for row in support):
        verdict = "SUPPORTED"
        reasons = ["all predeclared support predicates cleared and no falsifier cleared"]
    else:
        verdict = "INCONCLUSIVE"
        reasons = ["evidence threshold cleared but support and falsification rules did not decide"]
    return {
        "arm_id": treatment_id,
        "verdict": verdict,
        "support": support,
        "falsify": falsify,
        "reasons": reasons,
    }


def analyze(raw_lab: Any, raw_observations: Iterable[Any]) -> dict[str, Any]:
    lab = validate_lab(raw_lab)
    observations = [validate_observation(row, lab) for row in raw_observations]
    seen_runs: set[str] = set()
    for row in observations:
        if row["run_id"] in seen_runs:
            raise PlaneError(f"duplicate observation run_id: {row['run_id']}")
        seen_runs.add(row["run_id"])

    metric_defs = {row["id"]: row for row in lab["metrics"]}
    by_theory: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in observations:
        by_theory[row["theory_id"]].append(row)

    theory_reports: list[dict[str, Any]] = []
    counts = defaultdict(int)
    for theory in lab["theories"]:
        rows = by_theory.get(theory["id"], [])
        by_arm: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_arm[row["arm_id"]].append(row)
        summaries = {
            arm["id"]: _arm_summary(by_arm.get(arm["id"], []), metric_defs)
            for arm in theory["arms"]
        }
        control = summaries[theory["control_arm"]]
        task_ids = {
            task["id"]
            for task in lab["tasks"]
            if task["status"] == "ready" and task["family"] in theory["task_families"]
        }
        treatments = [
            arm for arm in theory["arms"] if arm["role"] == "treatment"
        ]
        treatment_results = [
            _treatment_verdict(
                theory,
                arm["id"],
                summaries[arm["id"]],
                control,
                task_ids,
            )
            for arm in treatments
        ]
        treatment_verdicts = [row["verdict"] for row in treatment_results]
        if not rows:
            overall = "UNMEASURED"
        elif "SUPPORTED" in treatment_verdicts:
            overall = "SUPPORTED"
        elif treatment_verdicts and all(value == "FALSIFIED" for value in treatment_verdicts):
            overall = "FALSIFIED"
        elif "PARTIAL" in treatment_verdicts:
            overall = "PARTIAL"
        else:
            overall = "INCONCLUSIVE"
        counts[overall] += 1
        theory_reports.append(
            {
                "theory_id": theory["id"],
                "title": theory["title"],
                "claim": theory["claim"],
                "prediction": theory["prediction"],
                "falsifier": theory["falsifier"],
                "verdict": overall,
                "control_arm": theory["control_arm"],
                "ready_task_ids": sorted(task_ids),
                "arm_summaries": summaries,
                "treatments": treatment_results,
                "confounds": theory["confounds"],
                "failure_default": theory["failure_default"],
            }
        )

    return {
        "schema": REPORT_SCHEMA,
        "lab_id": lab["id"],
        "lab_sha256": hash_json(lab),
        "generated_at": now(),
        "observation_count": len(observations),
        "authority": {
            "decisive": "pass/fail with requested==observed runtime, attestation, and complete telemetry",
            "errors": "non-decisive",
            "support": "all predeclared support predicates and no predeclared falsifier",
            "falsification": "any predeclared falsifier after evidence sufficiency",
            "failure_default": "PARTIAL or UNMEASURED",
        },
        "counts": dict(sorted(counts.items())),
        "theories": theory_reports,
    }
