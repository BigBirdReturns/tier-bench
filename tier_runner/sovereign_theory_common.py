"""Shared contracts for the Sovereign Theory Lab."""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from typing import Any, Iterable

from .sovereign_common import PlaneError, canonical_bytes, hash_json, need_number, need_text, safe_id

LAB_SCHEMA = "tier-bench/sovereign-theory-lab@1"
PLAN_SCHEMA = "tier-bench/sovereign-theory-plan@1"
OBSERVATION_SCHEMA = "tier-bench/sovereign-theory-observation@1"
REPORT_SCHEMA = "tier-bench/sovereign-theory-report@1"

THEORY_STATUSES = {"hypothesis", "calibrating", "measured", "retired"}
TASK_STATUSES = {"ready", "operator_task_required", "blocked"}
ACCEPTANCE_CLASSES = {"deterministic", "hidden_grade", "mixed", "blinded_human"}
ARM_ROLES = {"control", "treatment", "reference"}
METRIC_KINDS = {"number", "count", "boolean", "rate"}
DIRECTIONS = {"minimize", "maximize", "descriptive"}
AGGREGATES = {"mean", "median", "sum", "min", "max", "p95", "rate"}
OUTCOMES = {"pass", "fail", "error", "partial"}
PREDICATE_OPS = {
    "gte",
    "lte",
    "gt",
    "lt",
    "eq",
    "gte_control",
    "lte_control",
    "gt_control",
    "lt_control",
    "ratio_gte_control",
    "ratio_lte_control",
    "delta_gte_control",
    "delta_lte_control",
}
VERDICTS = {"SUPPORTED", "FALSIFIED", "INCONCLUSIVE", "PARTIAL", "UNMEASURED"}


def stable_label(*parts: str, prefix: str = "blind") -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[:12]}"


def percentile(values: list[float], q: float) -> float:
    if not values:
        raise PlaneError("cannot compute percentile of an empty sequence")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def aggregate(values: Iterable[float], kind: str) -> float:
    rows = [float(value) for value in values]
    if not rows:
        raise PlaneError("cannot aggregate an empty sequence")
    if kind == "mean":
        return statistics.fmean(rows)
    if kind == "median":
        return statistics.median(rows)
    if kind == "sum":
        return sum(rows)
    if kind == "min":
        return min(rows)
    if kind == "max":
        return max(rows)
    if kind == "p95":
        return percentile(rows, 0.95)
    if kind == "rate":
        return statistics.fmean(rows)
    raise PlaneError(f"unsupported aggregate: {kind}")


def metric_key(metric: str, aggregate_kind: str) -> str:
    return f"{metric}.{aggregate_kind}"


def normalized_settings(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise PlaneError("arm.settings must be an object")
    # Round-trip through canonical JSON to reject unserializable runtime objects.
    return json.loads(canonical_bytes(value))


def required_ratio(value: Any, label: str) -> float:
    return need_number(value, label, 0.0, 1000.0)


def required_metric_name(value: Any, label: str) -> str:
    return safe_id(value, label, limit=80)


def required_text_list(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise PlaneError(f"{label} must be {'an ' if allow_empty else 'a non-empty '}array")
    result: list[str] = []
    for index, row in enumerate(value):
        result.append(need_text(row, f"{label}[{index}]", limit=1000))
    return result


def fingerprint(value: Any) -> str:
    return hash_json(value)
