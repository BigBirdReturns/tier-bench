"""Universal model-floor computation and Opus/Fable delta analysis."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .model_floor_common import (
    DELTA_REPORT_SCHEMA,
    FLOOR_CONFIG_SCHEMA,
    FLOOR_REPORT_SCHEMA,
    ModelFloorError,
    OBSERVATION_SCHEMA,
    hash_json,
    need_array,
    need_bool,
    need_int,
    need_number,
    need_object,
    need_text,
    now_utc,
    optional_text,
    percentile,
    read_jsonl,
    safe_id,
    write_jsonl,
)
from .model_identity import RegistryIndex, resolve_identity

EVIDENCE_RANK = {
    "speculation": 0,
    "assertion": 1,
    "detailed_report": 2,
    "reproducible_receipt": 3,
    "verified_submission": 4,
    "official_benchmark": 5,
    "internal_receipt": 6,
}
DIRECTIONS = {"higher", "lower"}


def validate_floor_config(raw: Any) -> dict[str, Any]:
    value = need_object(raw, "floor config")
    if value.get("schema") != FLOOR_CONFIG_SCHEMA:
        raise ModelFloorError(f"floor config schema must be {FLOOR_CONFIG_SCHEMA}")
    config_id = safe_id(value.get("id"), "floor config.id")
    minimum_sample_size = need_int(
        value.get("minimum_sample_size", 3),
        "floor config.minimum_sample_size",
        low=1,
        high=1000000,
    )
    minimum_distinct_tasks = need_int(
        value.get("minimum_distinct_tasks", 10),
        "floor config.minimum_distinct_tasks",
        low=1,
        high=1000000,
    )
    external_min_evidence = value.get("external_min_evidence", "detailed_report")
    if external_min_evidence not in EVIDENCE_RANK:
        raise ModelFloorError(
            f"external_min_evidence must be one of {sorted(EVIDENCE_RANK)}"
        )
    objectives = [
        need_text(item, "floor config.objectives[]", limit=100)
        for item in need_array(
            value.get(
                "objectives",
                [
                    "cost_per_verified_success_usd",
                    "attention_per_verified_success",
                    "latency_ms",
                ],
            ),
            "floor config.objectives",
            nonempty=True,
        )
    ]
    allowed_objectives = {
        "cost_per_verified_success_usd",
        "attention_per_verified_success",
        "latency_ms",
        "observed_cost_usd",
    }
    unknown_objectives = set(objectives) - allowed_objectives
    if unknown_objectives:
        raise ModelFloorError(f"unknown floor objectives: {sorted(unknown_objectives)}")
    family_rules = []
    seen = set()
    for index, raw_rule in enumerate(
        need_array(value.get("family_rules", []), "floor config.family_rules")
    ):
        rule = need_object(raw_rule, f"family_rules[{index}]")
        family = safe_id(rule.get("family"), f"family_rules[{index}].family", limit=300)
        if family in seen:
            raise ModelFloorError(f"duplicate family rule: {family}")
        seen.add(family)
        direction = rule.get("direction", "higher")
        if direction not in DIRECTIONS:
            raise ModelFloorError(f"{family}.direction must be higher or lower")
        family_rules.append(
            {
                **rule,
                "family": family,
                "metric": safe_id(
                    rule.get("metric", "accepted"), f"{family}.metric", limit=300
                ),
                "direction": direction,
                "adequacy_threshold": need_number(
                    rule.get("adequacy_threshold", 1.0),
                    f"{family}.adequacy_threshold",
                ),
                "minimum_distinct_tasks": need_int(
                    rule.get("minimum_distinct_tasks", minimum_distinct_tasks),
                    f"{family}.minimum_distinct_tasks",
                    low=1,
                    high=1000000,
                ),
                "require_cost": need_bool(
                    rule.get("require_cost", False), f"{family}.require_cost"
                ),
                "require_attention": need_bool(
                    rule.get("require_attention", False),
                    f"{family}.require_attention",
                ),
                "max_critical_escaped_defects": need_int(
                    rule.get("max_critical_escaped_defects", 0),
                    f"{family}.max_critical_escaped_defects",
                    low=0,
                    high=1000000,
                ),
            }
        )
    return {
        **value,
        "id": config_id,
        "minimum_sample_size": minimum_sample_size,
        "minimum_distinct_tasks": minimum_distinct_tasks,
        "external_min_evidence": external_min_evidence,
        "objectives": objectives,
        "family_rules": family_rules,
        "allow_external_unattested": need_bool(
            value.get("allow_external_unattested", True),
            "floor config.allow_external_unattested",
        ),
        "internal_identity_required": need_bool(
            value.get("internal_identity_required", True),
            "floor config.internal_identity_required",
        ),
    }


def validate_observation(raw: Any) -> dict[str, Any]:
    value = need_object(raw, "observation")
    if value.get("schema") != OBSERVATION_SCHEMA:
        raise ModelFloorError(f"observation schema must be {OBSERVATION_SCHEMA}")
    observation_id = safe_id(value.get("id"), "observation.id", limit=300)
    source = need_object(value.get("source"), f"{observation_id}.source")
    model = need_object(value.get("model"), f"{observation_id}.model")
    benchmark = need_object(value.get("benchmark"), f"{observation_id}.benchmark")
    result = need_object(value.get("result"), f"{observation_id}.result")
    evidence = need_object(value.get("evidence"), f"{observation_id}.evidence")
    direction = benchmark.get("direction", "higher")
    if direction not in DIRECTIONS:
        raise ModelFloorError(f"{observation_id}.benchmark.direction is invalid")
    tier = evidence.get("tier")
    if tier not in EVIDENCE_RANK:
        raise ModelFloorError(
            f"{observation_id}.evidence.tier must be one of {sorted(EVIDENCE_RANK)}"
        )
    normalized_benchmark = {
        **benchmark,
        "id": safe_id(benchmark.get("id"), f"{observation_id}.benchmark.id", limit=300),
        "revision": need_text(
            benchmark.get("revision", "rolling"),
            f"{observation_id}.benchmark.revision",
            limit=300,
        ),
        "task_family": safe_id(
            benchmark.get("task_family", benchmark.get("id")),
            f"{observation_id}.benchmark.task_family",
            limit=300,
        ),
        "metric": safe_id(
            benchmark.get("metric"), f"{observation_id}.benchmark.metric", limit=300
        ),
        "direction": direction,
        "unit": need_text(
            benchmark.get("unit", "score"),
            f"{observation_id}.benchmark.unit",
            limit=100,
        ),
        "scaffold": need_text(
            benchmark.get("scaffold", "unspecified"),
            f"{observation_id}.benchmark.scaffold",
            limit=500,
        ),
        "tools": need_text(
            benchmark.get("tools", "unspecified"),
            f"{observation_id}.benchmark.tools",
            limit=500,
        ),
        "attempts": need_int(
            benchmark.get("attempts", 1),
            f"{observation_id}.benchmark.attempts",
            low=1,
            high=100000,
        ),
        "context_policy": need_text(
            benchmark.get("context_policy", "unspecified"),
            f"{observation_id}.benchmark.context_policy",
            limit=500,
        ),
        "comparison_key": need_text(
            benchmark.get("comparison_key"),
            f"{observation_id}.benchmark.comparison_key",
            limit=128,
        ),
        "adequacy_threshold": need_number(
            benchmark.get("adequacy_threshold"),
            f"{observation_id}.benchmark.adequacy_threshold",
            allow_none=True,
        ),
    }
    normalized_result = {
        **result,
        "value": need_number(result.get("value"), f"{observation_id}.result.value"),
        "sample_size": (
            need_int(
                result.get("sample_size"),
                f"{observation_id}.result.sample_size",
                low=0,
            )
            if result.get("sample_size") is not None
            else None
        ),
    }
    for field in (
        "cost_usd",
        "observed_cost_usd",
        "cost_per_verified_success_usd",
        "attention_minutes",
        "attention_per_verified_success",
        "latency_ms",
        "autonomy_minutes",
    ):
        normalized_result[field] = need_number(
            result.get(field), f"{observation_id}.result.{field}", low=0, allow_none=True
        )
    normalized_result["critical_escaped_defects"] = need_int(
        result.get("critical_escaped_defects", 0),
        f"{observation_id}.result.critical_escaped_defects",
        low=0,
    )
    return {
        **value,
        "id": observation_id,
        "source": {
            **source,
            "id": safe_id(source.get("id"), f"{observation_id}.source.id", limit=300),
            "kind": need_text(
                source.get("kind"), f"{observation_id}.source.kind", limit=100
            ),
        },
        "model": {
            **model,
            "declared_id": need_text(
                model.get("declared_id"),
                f"{observation_id}.model.declared_id",
                limit=300,
            ),
        },
        "benchmark": normalized_benchmark,
        "result": normalized_result,
        "evidence": {
            **evidence,
            "tier": tier,
            "verified": need_bool(
                evidence.get("verified", False),
                f"{observation_id}.evidence.verified",
            ),
        },
    }


def load_observations(paths: Iterable[Path]) -> list[dict[str, Any]]:
    rows = []
    seen: dict[str, str] = {}
    for path in paths:
        for row in read_jsonl(path):
            observation = validate_observation(row)
            digest = observation.get("observation_sha256") or hash_json(
                {
                    key: value
                    for key, value in observation.items()
                    if key != "observation_sha256"
                }
            )
            existing = seen.get(observation["id"])
            if existing and existing != digest:
                raise ModelFloorError(
                    f"observation id {observation['id']} has conflicting bytes"
                )
            seen[observation["id"]] = digest
            rows.append(observation)
    by_id = {row["id"]: row for row in rows}
    return [by_id[key] for key in sorted(by_id)]


def _comparison_key(benchmark: dict[str, Any]) -> str:
    return hash_json(
        {
            key: benchmark.get(key)
            for key in (
                "id",
                "revision",
                "task_family",
                "metric",
                "direction",
                "unit",
                "scaffold",
                "tools",
                "attempts",
                "context_policy",
            )
        }
    )


def observations_from_waterline(
    protocol: dict[str, Any],
    report: dict[str, Any],
) -> list[dict[str, Any]]:
    if report.get("schema") != "tier-bench/model-waterline-report@1":
        raise ModelFloorError("waterline report has the wrong schema")
    protocol_id = need_text(protocol.get("id"), "protocol.id", limit=300)
    if report.get("protocol_id") != protocol_id:
        raise ModelFloorError("waterline report does not bind the supplied protocol")
    protocol_routes = {
        str(route.get("id")): route
        for route in need_array(protocol.get("routes"), "protocol.routes", nonempty=True)
        if isinstance(route, dict)
    }
    observations = []
    for task in need_array(report.get("tasks"), "waterline report.tasks"):
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("task_id") or task.get("campaign_id") or "")
        if not task_id:
            continue
        family = str(task.get("family") or "unclassified")
        audit_by_route = {}
        for audit_key in ("candidate_audit", "reference_audit"):
            audit = task.get(audit_key)
            if isinstance(audit, dict) and isinstance(audit.get("route_id"), str):
                audit_by_route[audit["route_id"]] = audit
        for summary in task.get("route_summaries", []):
            if not isinstance(summary, dict):
                continue
            route_id = str(summary.get("route_id") or "")
            route = protocol_routes.get(route_id)
            if not route:
                continue
            state = summary.get("state")
            if state not in {"clears", "wall", "unstable", "collecting", "unmeasured"}:
                continue
            valid = int(summary.get("valid_decisive", 0) or 0)
            passes = int(summary.get("passes", 0) or 0)
            value = passes / valid if valid else 0.0
            benchmark = {
                "id": f"internal:{protocol_id}:{task_id}",
                "revision": str(report.get("protocol_sha256") or protocol_id),
                "task_family": family,
                "metric": "accepted",
                "direction": "higher",
                "unit": "pass_rate",
                "scaffold": protocol_id,
                "tools": "tier-bench-frozen-task",
                "attempts": int(summary.get("k", 1) or 1),
                "context_policy": "frozen-task-envelope",
                "adequacy_threshold": 1.0,
            }
            benchmark["comparison_key"] = _comparison_key(benchmark)
            audit = audit_by_route.get(route_id) or {}
            observation = {
                "schema": OBSERVATION_SCHEMA,
                "id": (
                    "internal-"
                    + hashlib.sha256(
                        f"{protocol_id}\0{task_id}\0{route_id}".encode("utf-8")
                    ).hexdigest()[:24]
                ),
                "observed_at": report.get("generated_at") or now_utc(),
                "source": {
                    "id": protocol_id,
                    "kind": "internal_waterline",
                    "uri": None,
                    "snapshot_sha256": report.get("protocol_sha256"),
                },
                "model": {
                    "declared_id": str(route.get("model_id")),
                    "runtime_id": str(route.get("model_id")),
                    "surface_id": route.get("identity_surface_id"),
                    "revision": route.get("revision"),
                    "effort": route.get("effort"),
                    "quantization": route.get("quantization"),
                    "hardware": route.get("hardware"),
                },
                "benchmark": benchmark,
                "result": {
                    "value": value,
                    "sample_size": valid,
                    "state": state,
                    "passes": passes,
                    "failures": int(summary.get("failures", 0) or 0),
                    "cost_usd": summary.get("priced_cost_usd"),
                    "observed_cost_usd": summary.get("observed_cost_usd"),
                    "cost_per_verified_success_usd": summary.get(
                        "cost_per_verified_success_usd"
                    ),
                    "attention_minutes": summary.get("attention_minutes"),
                    "attention_per_verified_success": summary.get(
                        "attention_per_verified_success"
                    ),
                    "latency_ms": None,
                    "autonomy_minutes": None,
                    "critical_escaped_defects": int(
                        audit.get("critical_escaped_defects", 0) or 0
                    ),
                },
                "evidence": {
                    "tier": "internal_receipt",
                    "verified": state in {"clears", "wall"},
                    "training_use": "permitted",
                    "tainted": False,
                },
                "metadata": {
                    "protocol_id": protocol_id,
                    "task_id": task_id,
                    "route_id": route_id,
                    "role": route.get("role"),
                    "lane": route.get("lane"),
                    "classification": task.get("classification"),
                    "runtime_attestation_derived": True,
                    "invalid_trials": summary.get("invalid_trials", []),
                },
            }
            observation["observation_sha256"] = hash_json(
                {
                    key: value
                    for key, value in observation.items()
                    if key != "observation_sha256"
                }
            )
            observations.append(observation)
    return observations


def _adequate(value: float, threshold: float, direction: str) -> bool:
    return value >= threshold if direction == "higher" else value <= threshold


def _objective_tuple(row: dict[str, Any], objectives: list[str]) -> tuple[Any, ...]:
    result = row["aggregate"]
    values = []
    for objective in objectives:
        value = result.get(objective)
        values.append(float("inf") if value is None else float(value))
    values.extend(
        [
            -float(result["pass_rate"]),
            row["identity"]["canonical_id"] or row["identity"]["declared_id"],
            row["route_key"],
        ]
    )
    return tuple(values)


def _dominates(a: dict[str, Any], b: dict[str, Any], objectives: list[str]) -> bool:
    better_or_equal = True
    strictly_better = False
    for objective in objectives:
        av = a["aggregate"].get(objective)
        bv = b["aggregate"].get(objective)
        if av is None or bv is None:
            continue
        if av > bv:
            better_or_equal = False
            break
        if av < bv:
            strictly_better = True
    if a["aggregate"]["pass_rate"] < b["aggregate"]["pass_rate"]:
        better_or_equal = False
    elif a["aggregate"]["pass_rate"] > b["aggregate"]["pass_rate"]:
        strictly_better = True
    return better_or_equal and strictly_better


def _rule_for(config: dict[str, Any], family: str, observations: list[dict[str, Any]]) -> dict[str, Any]:
    for rule in config["family_rules"]:
        if rule["family"] == family:
            return rule
    thresholds = [
        row["benchmark"].get("adequacy_threshold")
        for row in observations
        if row["benchmark"].get("adequacy_threshold") is not None
    ]
    direction = observations[0]["benchmark"]["direction"] if observations else "higher"
    metric = observations[0]["benchmark"]["metric"] if observations else "accepted"
    return {
        "family": family,
        "metric": metric,
        "direction": direction,
        "adequacy_threshold": float(thresholds[0]) if thresholds else 1.0,
        "minimum_distinct_tasks": config["minimum_distinct_tasks"],
        "require_cost": False,
        "require_attention": False,
        "max_critical_escaped_defects": 0,
    }


def _route_key(identity: dict[str, Any], model: dict[str, Any]) -> str:
    return "|".join(
        str(value or "")
        for value in (
            identity.get("canonical_id") or identity.get("declared_id"),
            identity.get("surface_id"),
            model.get("effort"),
            model.get("quantization"),
            model.get("hardware"),
        )
    )


def _aggregate_route(
    rows: list[dict[str, Any]],
    identity: dict[str, Any],
    route_key: str,
) -> dict[str, Any]:
    distinct_tasks = {
        str((row.get("metadata") or {}).get("task_id") or row["benchmark"]["id"])
        for row in rows
    }
    passes = sum(1 for row in rows if row["result"].get("state") == "clears")
    walls = sum(1 for row in rows if row["result"].get("state") == "wall")
    decisive = passes + walls
    score_values = [float(row["result"]["value"]) for row in rows]
    costs = [
        float(row["result"]["cost_per_verified_success_usd"])
        for row in rows
        if row["result"].get("cost_per_verified_success_usd") is not None
    ]
    observed_costs = [
        float(row["result"]["observed_cost_usd"])
        for row in rows
        if row["result"].get("observed_cost_usd") is not None
    ]
    attention = [
        float(row["result"]["attention_per_verified_success"])
        for row in rows
        if row["result"].get("attention_per_verified_success") is not None
    ]
    latencies = [
        float(row["result"]["latency_ms"])
        for row in rows
        if row["result"].get("latency_ms") is not None
    ]
    defects = sum(int(row["result"].get("critical_escaped_defects", 0) or 0) for row in rows)
    return {
        "route_key": route_key,
        "identity": identity,
        "model": rows[0]["model"],
        "aggregate": {
            "distinct_tasks": len(distinct_tasks),
            "decisive_tasks": decisive,
            "passes": passes,
            "walls": walls,
            "pass_rate": passes / decisive if decisive else 0.0,
            "mean_score": sum(score_values) / len(score_values) if score_values else None,
            "cost_per_verified_success_usd": (
                sum(costs) / len(costs) if len(costs) == passes and passes else None
            ),
            "observed_cost_usd": sum(observed_costs) if observed_costs else None,
            "attention_per_verified_success": (
                sum(attention) / len(attention) if len(attention) == passes and passes else None
            ),
            "latency_ms": sum(latencies) / len(latencies) if latencies else None,
            "critical_escaped_defects": defects,
        },
        "observation_ids": [row["id"] for row in rows],
    }


def _external_cells(
    observations: list[dict[str, Any]],
    identities: dict[str, dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    minimum_rank = EVIDENCE_RANK[config["external_min_evidence"]]
    for row in observations:
        if row["source"]["kind"] == "internal_waterline":
            continue
        if EVIDENCE_RANK[row["evidence"]["tier"]] < minimum_rank:
            continue
        identity = identities[row["id"]]
        if (
            not config["allow_external_unattested"]
            and identity["identity_status"] != "attested"
        ):
            continue
        groups[row["benchmark"]["comparison_key"]].append(row)
    cells = []
    for key in sorted(groups):
        rows = groups[key]
        scores = [float(row["result"]["value"]) for row in rows]
        direction = rows[0]["benchmark"]["direction"]
        best_value = max(scores) if direction == "higher" else min(scores)
        best_rows = [
            row for row in rows if float(row["result"]["value"]) == best_value
        ]
        cells.append(
            {
                "comparison_key": key,
                "benchmark": rows[0]["benchmark"],
                "count": len(rows),
                "verified_count": sum(1 for row in rows if row["evidence"]["verified"]),
                "distribution": {
                    "minimum": min(scores),
                    "p25": percentile(scores, 0.25),
                    "median": percentile(scores, 0.5),
                    "p75": percentile(scores, 0.75),
                    "maximum": max(scores),
                },
                "best": [
                    {
                        "observation_id": row["id"],
                        "model": identities[row["id"]],
                        "value": row["result"]["value"],
                        "rank": row["result"].get("rank"),
                        "source": row["source"],
                    }
                    for row in best_rows
                ],
                "rows": [
                    {
                        "observation_id": row["id"],
                        "model": identities[row["id"]],
                        "value": row["result"]["value"],
                        "rank": row["result"].get("rank"),
                        "sample_size": row["result"].get("sample_size"),
                        "cost_usd": row["result"].get("cost_usd"),
                        "evidence": row["evidence"],
                        "source": row["source"],
                    }
                    for row in rows
                ],
            }
        )
    return cells


def compute_floor(
    registry: RegistryIndex,
    raw_config: Any,
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    config = validate_floor_config(raw_config)
    observations = [validate_observation(row) for row in observations]
    identities = {
        row["id"]: resolve_identity(row["model"], registry) for row in observations
    }
    internal_by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in observations:
        if row["source"]["kind"] == "internal_waterline":
            internal_by_family[row["benchmark"]["task_family"]].append(row)
    configured_families = {rule["family"] for rule in config["family_rules"]}
    families = sorted(configured_families | set(internal_by_family))
    family_rows = []
    all_model_ids = sorted(registry.models)
    for family in families:
        rows = internal_by_family.get(family, [])
        rule = _rule_for(config, family, rows)
        route_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        route_identities: dict[str, dict[str, Any]] = {}
        excluded = []
        for row in rows:
            identity = identities[row["id"]]
            if config["internal_identity_required"] and identity["identity_status"] != "attested":
                excluded.append(
                    {
                        "observation_id": row["id"],
                        "reason": "identity_not_attested",
                        "identity": identity,
                    }
                )
                continue
            route_key = _route_key(identity, row["model"])
            route_groups[route_key].append(row)
            route_identities[route_key] = identity
        aggregates = [
            _aggregate_route(group, route_identities[key], key)
            for key, group in sorted(route_groups.items())
        ]
        adequate = []
        for row in aggregates:
            aggregate = row["aggregate"]
            reasons = []
            if aggregate["distinct_tasks"] < rule["minimum_distinct_tasks"]:
                reasons.append("insufficient_distinct_tasks")
            if not _adequate(
                aggregate["pass_rate"],
                float(rule["adequacy_threshold"]),
                rule["direction"],
            ):
                reasons.append("capability_below_threshold")
            if aggregate["critical_escaped_defects"] > rule["max_critical_escaped_defects"]:
                reasons.append("critical_escaped_defects")
            if rule["require_cost"] and aggregate["cost_per_verified_success_usd"] is None:
                reasons.append("cost_unmeasured")
            if (
                rule["require_attention"]
                and aggregate["attention_per_verified_success"] is None
            ):
                reasons.append("attention_unmeasured")
            row["adequacy"] = {
                "adequate": not reasons,
                "reasons": reasons,
                "rule": rule,
            }
            if not reasons:
                adequate.append(row)
        pareto = [
            row
            for row in adequate
            if not any(
                other is not row and _dominates(other, row, config["objectives"])
                for other in adequate
            )
        ]
        selected = min(adequate, key=lambda row: _objective_tuple(row, config["objectives"])) if adequate else None
        matrix = {}
        aggregate_by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in aggregates:
            canonical = row["identity"].get("canonical_id")
            if canonical:
                aggregate_by_model[canonical].append(row)
        for model_id in all_model_ids:
            model_rows = aggregate_by_model.get(model_id, [])
            if not model_rows:
                matrix[model_id] = {"status": "unmeasured", "routes": []}
            elif any(row["adequacy"]["adequate"] for row in model_rows):
                matrix[model_id] = {
                    "status": "adequate",
                    "routes": [row["route_key"] for row in model_rows],
                }
            elif all(
                "insufficient_distinct_tasks" in row["adequacy"]["reasons"]
                for row in model_rows
            ):
                matrix[model_id] = {
                    "status": "collecting",
                    "routes": [row["route_key"] for row in model_rows],
                }
            else:
                matrix[model_id] = {
                    "status": "wall",
                    "routes": [row["route_key"] for row in model_rows],
                }
        family_rows.append(
            {
                "family": family,
                "rule": rule,
                "status": (
                    "FLOOR_SETTLED"
                    if selected
                    else "COLLECTING"
                    if aggregates
                    else "UNMEASURED"
                ),
                "selected_floor": (
                    {
                        "route_key": selected["route_key"],
                        "identity": selected["identity"],
                        "model": selected["model"],
                        "aggregate": selected["aggregate"],
                    }
                    if selected
                    else None
                ),
                "pareto_frontier": [
                    {
                        "route_key": row["route_key"],
                        "identity": row["identity"],
                        "model": row["model"],
                        "aggregate": row["aggregate"],
                    }
                    for row in sorted(
                        pareto,
                        key=lambda row: _objective_tuple(row, config["objectives"]),
                    )
                ],
                "routes": aggregates,
                "model_matrix": matrix,
                "excluded": excluded,
            }
        )
    external_cells = _external_cells(observations, identities, config)
    identity_counts: dict[str, int] = {}
    for identity in identities.values():
        status = identity["identity_status"]
        identity_counts[status] = identity_counts.get(status, 0) + 1
    report = {
        "schema": FLOOR_REPORT_SCHEMA,
        "created_at": now_utc(),
        "registry_id": registry.registry["id"],
        "registry_sha256": hash_json(registry.registry),
        "config_id": config["id"],
        "config_sha256": hash_json(config),
        "counts": {
            "observations": len(observations),
            "models_registered": len(registry.models),
            "families": len(family_rows),
            "settled_families": sum(
                1 for row in family_rows if row["status"] == "FLOOR_SETTLED"
            ),
            "external_cells": len(external_cells),
        },
        "identity_counts": identity_counts,
        "families": family_rows,
        "external_baselines": external_cells,
        "laws": [
            "A model floor is bounded to a task family and acceptance contract.",
            "Different benchmark revisions, scaffolds, tool policies, attempts, or context policies are not averaged together.",
            "Runtime and transport failures do not become capability failures.",
            "External community observations can challenge or prioritize internal work but cannot settle the internal floor.",
            "Unmeasured models remain visible in every configured family matrix.",
        ],
    }
    report["report_sha256"] = hash_json(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    return report


def _route_price(protocol: dict[str, Any], route_id: str) -> dict[str, Any] | None:
    for route in protocol.get("routes", []):
        if isinstance(route, dict) and route.get("id") == route_id:
            return route.get("price") if isinstance(route.get("price"), dict) else None
    return None


def _external_pairs(
    observations: list[dict[str, Any]],
    identities: dict[str, dict[str, Any]],
    subject: str,
    reference: str,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: {"subject": [], "reference": []}
    )
    for row in observations:
        canonical = identities[row["id"]].get("canonical_id")
        if canonical == subject:
            grouped[row["benchmark"]["comparison_key"]]["subject"].append(row)
        elif canonical == reference:
            grouped[row["benchmark"]["comparison_key"]]["reference"].append(row)
    pairs = []
    for key, group in sorted(grouped.items()):
        if not group["subject"] or not group["reference"]:
            continue
        for subject_row in group["subject"]:
            for reference_row in group["reference"]:
                if (
                    subject_row["benchmark"]["metric"]
                    != reference_row["benchmark"]["metric"]
                    or subject_row["benchmark"]["direction"]
                    != reference_row["benchmark"]["direction"]
                ):
                    continue
                subject_value = float(subject_row["result"]["value"])
                reference_value = float(reference_row["result"]["value"])
                direction = subject_row["benchmark"]["direction"]
                noninferior = (
                    subject_value >= reference_value
                    if direction == "higher"
                    else subject_value <= reference_value
                )
                pairs.append(
                    {
                        "comparison_key": key,
                        "benchmark": subject_row["benchmark"],
                        "subject_observation": subject_row["id"],
                        "reference_observation": reference_row["id"],
                        "subject_value": subject_value,
                        "reference_value": reference_value,
                        "delta": subject_value - reference_value,
                        "noninferior_directionally": noninferior,
                        "evidence_warning": (
                            "External rows are directional unless the benchmark operator "
                            "confirms identical scaffold, tools, retries, context, and revision."
                        ),
                    }
                )
    return pairs


def compute_delta_report(
    registry: RegistryIndex,
    protocol: dict[str, Any],
    waterline_report: dict[str, Any],
    external_observations: list[dict[str, Any]],
) -> dict[str, Any]:
    protocol_id = need_text(protocol.get("id"), "protocol.id", limit=300)
    if waterline_report.get("protocol_id") != protocol_id:
        raise ModelFloorError("waterline report does not bind the supplied protocol")
    subject_declared = need_text(protocol.get("subject_model"), "protocol.subject_model")
    reference_declared = need_text(protocol.get("reference_model"), "protocol.reference_model")
    subject_resolved = registry.aliases.get(subject_declared.casefold())
    reference_resolved = registry.aliases.get(reference_declared.casefold())
    identity_gaps = []
    if not subject_resolved:
        identity_gaps.append("subject_model_not_in_registry")
    if not reference_resolved:
        identity_gaps.append("reference_model_not_in_registry")
    task_rows = []
    for task in waterline_report.get("tasks", []):
        if not isinstance(task, dict):
            continue
        summaries = {
            row.get("route_id"): row
            for row in task.get("route_summaries", [])
            if isinstance(row, dict)
        }
        candidate_routes = [
            route
            for route in protocol.get("routes", [])
            if isinstance(route, dict)
            and route.get("role") == "candidate"
            and route.get("lane") == "native"
        ]
        reference_routes = [
            route
            for route in protocol.get("routes", [])
            if isinstance(route, dict) and route.get("role") == "reference"
        ]
        candidate_clear = [
            (route, summaries.get(route.get("id"), {}))
            for route in candidate_routes
            if summaries.get(route.get("id"), {}).get("state") == "clears"
        ]
        reference_clear = [
            (route, summaries.get(route.get("id"), {}))
            for route in reference_routes
            if summaries.get(route.get("id"), {}).get("state") == "clears"
        ]
        selected_candidate = candidate_clear[0] if candidate_clear else None
        selected_reference = reference_clear[0] if reference_clear else None
        cost_ratio = None
        attention_ratio = None
        if selected_candidate and selected_reference:
            candidate_cost = selected_candidate[1].get(
                "cost_per_verified_success_usd"
            )
            reference_cost = selected_reference[1].get(
                "cost_per_verified_success_usd"
            )
            if isinstance(candidate_cost, (int, float)) and isinstance(
                reference_cost, (int, float)
            ) and reference_cost:
                cost_ratio = float(candidate_cost) / float(reference_cost)
            candidate_attention = selected_candidate[1].get(
                "attention_per_verified_success"
            )
            reference_attention = selected_reference[1].get(
                "attention_per_verified_success"
            )
            if isinstance(candidate_attention, (int, float)) and isinstance(
                reference_attention, (int, float)
            ) and reference_attention:
                attention_ratio = float(candidate_attention) / float(reference_attention)
        task_rows.append(
            {
                "task_id": task.get("task_id"),
                "family": task.get("family"),
                "classification": task.get("classification"),
                "candidate_route": (
                    selected_candidate[0].get("id") if selected_candidate else None
                ),
                "reference_route": (
                    selected_reference[0].get("id") if selected_reference else None
                ),
                "candidate_effort": (
                    selected_candidate[0].get("effort") if selected_candidate else None
                ),
                "reference_effort": (
                    selected_reference[0].get("effort") if selected_reference else None
                ),
                "cost_ratio": cost_ratio,
                "attention_ratio": attention_ratio,
                "economic_status": task.get("economic_status"),
                "attention_status": task.get("attention_status"),
                "audit_status": task.get("audit_status"),
            }
        )
    native = [row for row in task_rows if row["classification"] == "REPLICATED_NATIVE"]
    augmented = [
        row for row in task_rows if row["classification"] == "REPLICATED_AUGMENTED"
    ]
    residue = [
        row for row in task_rows if row["classification"] == "REFERENCE_RESIDUE"
    ]
    external_observations = [
        validate_observation(row) for row in external_observations
    ]
    external_identities = {
        row["id"]: resolve_identity(row["model"], registry)
        for row in external_observations
    }
    external_pairs = (
        _external_pairs(
            external_observations,
            external_identities,
            subject_resolved,
            reference_resolved,
        )
        if subject_resolved and reference_resolved
        else []
    )
    candidate_prices = [
        route.get("price")
        for route in protocol.get("routes", [])
        if isinstance(route, dict)
        and route.get("role") == "candidate"
        and route.get("lane") == "native"
        and isinstance(route.get("price"), dict)
    ]
    reference_prices = [
        route.get("price")
        for route in protocol.get("routes", [])
        if isinstance(route, dict)
        and route.get("role") == "reference"
        and isinstance(route.get("price"), dict)
    ]
    token_price_ratio = None
    if candidate_prices and reference_prices:
        candidate_input = float(candidate_prices[0].get("input_per_million", 0) or 0)
        reference_input = float(reference_prices[0].get("input_per_million", 0) or 0)
        candidate_output = float(candidate_prices[0].get("output_per_million", 0) or 0)
        reference_output = float(reference_prices[0].get("output_per_million", 0) or 0)
        ratios = []
        if reference_input:
            ratios.append(candidate_input / reference_input)
        if reference_output:
            ratios.append(candidate_output / reference_output)
        if ratios:
            token_price_ratio = sum(ratios) / len(ratios)
    report = {
        "schema": DELTA_REPORT_SCHEMA,
        "created_at": now_utc(),
        "protocol_id": protocol_id,
        "protocol_sha256": hash_json(protocol),
        "waterline_report_sha256": waterline_report.get("report_sha256")
        or hash_json(waterline_report),
        "subject": {
            "declared_id": subject_declared,
            "canonical_id": subject_resolved,
        },
        "reference": {
            "declared_id": reference_declared,
            "canonical_id": reference_resolved,
        },
        "identity_gaps": identity_gaps,
        "internal": {
            "waterline_status": waterline_report.get("waterline_status"),
            "capability_status": waterline_report.get("capability_status"),
            "blocked_reasons": waterline_report.get("blocked_reasons", []),
            "counts": {
                "tasks": len(task_rows),
                "native_replications": len(native),
                "augmented_replications": len(augmented),
                "reference_residue": len(residue),
            },
            "tasks": task_rows,
            "native_waterline_fraction": len(native) / len(task_rows) if task_rows else None,
            "all_replication_fraction": (
                (len(native) + len(augmented)) / len(task_rows) if task_rows else None
            ),
        },
        "economics": {
            "declared_token_price_ratio_subject_to_reference": token_price_ratio,
            "break_even_interpretation": (
                "A lower token price permits more candidate attempts only until total "
                "cost per independently accepted outcome reaches the reference cost."
            ),
            "task_cost_ratios": [
                {
                    "task_id": row["task_id"],
                    "ratio": row["cost_ratio"],
                }
                for row in task_rows
                if row["cost_ratio"] is not None
            ],
        },
        "external": {
            "comparable_pairs": external_pairs,
            "pair_count": len(external_pairs),
            "identity_counts": {
                status: sum(
                    1
                    for identity in external_identities.values()
                    if identity["identity_status"] == status
                )
                for status in {"attested", "unattested", "conflicted", "unknown"}
            },
        },
        "control_questions": [
            "Which distinct task families still produce reference-only accepted outcomes?",
            "Does the subject remain cheaper after every failed attempt, repair, tool call, and operator intervention is counted?",
            "Can any reference-only move be frozen into an advisor packet, verifier, context compiler, or local capture artifact?",
            "Do external claims reproduce under our exact runtime, scaffold, context, tool, retry, and acceptance contracts?",
        ],
    }
    report["report_sha256"] = hash_json(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    return report



def ingest_waterline_tree(
    protocol_root: Path,
    reports_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    protocols: dict[str, tuple[dict[str, Any], Path]] = {}
    for path in sorted(protocol_root.rglob("*.json")):
        if path.stat().st_size > 16 * 1024 * 1024:
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if (
            isinstance(value, dict)
            and value.get("schema") == "tier-bench/model-waterline-protocol@1"
            and isinstance(value.get("id"), str)
        ):
            protocol_id = value["id"]
            existing = protocols.get(protocol_id)
            digest = hash_json(value)
            if existing and hash_json(existing[0]) != digest:
                raise ModelFloorError(
                    f"conflicting waterline protocols share id {protocol_id}: "
                    f"{existing[1]} and {path}"
                )
            protocols[protocol_id] = (value, path)
    observations: list[dict[str, Any]] = []
    reports = []
    unmatched = []
    for path in sorted(reports_root.rglob("*.json")):
        if path.stat().st_size > 64 * 1024 * 1024:
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(value, dict) or value.get("schema") != "tier-bench/model-waterline-report@1":
            continue
        protocol_id = value.get("protocol_id")
        binding = protocols.get(protocol_id)
        if not binding:
            unmatched.append(
                {"report": str(path.resolve()), "protocol_id": protocol_id}
            )
            continue
        rows = observations_from_waterline(binding[0], value)
        observations.extend(rows)
        reports.append(
            {
                "path": str(path.resolve()),
                "sha256": hash_json(value),
                "protocol_id": protocol_id,
                "protocol_path": str(binding[1].resolve()),
                "observations": len(rows),
            }
        )
    by_id: dict[str, dict[str, Any]] = {}
    conflicts = []
    for row in observations:
        existing = by_id.get(row["id"])
        if existing and existing.get("observation_sha256") != row.get("observation_sha256"):
            conflicts.append(row["id"])
            continue
        by_id[row["id"]] = row
    if conflicts:
        raise ModelFloorError(
            "conflicting internal observations were derived for ids: "
            + ", ".join(sorted(set(conflicts))[:20])
        )
    rows = [by_id[key] for key in sorted(by_id)]
    receipt = {
        "schema": "tier-bench/model-floor-internal-ingest@1",
        "created_at": now_utc(),
        "protocol_root": str(protocol_root.resolve()),
        "reports_root": str(reports_root.resolve()),
        "protocols": len(protocols),
        "reports": reports,
        "unmatched_reports": unmatched,
        "observations": len(rows),
    }
    receipt["ingest_sha256"] = hash_json(
        {key: value for key, value in receipt.items() if key != "ingest_sha256"}
    )
    return rows, receipt


def write_observations(path: Path, rows: list[dict[str, Any]]) -> None:
    write_jsonl(path, rows)
