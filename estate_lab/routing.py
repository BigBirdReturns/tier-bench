"""Transparent route evaluation for Estate Lab scenarios.

The router is intentionally arithmetic rather than model-driven. Every route is
first admitted or refused by hard constraints. Eligible routes are then scored
from declared evidence, determinism, replayability, locality, latency, cost,
fragility, and authority risk. The complete evaluation table is retained in the
run receipt.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable

from .errors import RouteRefused
from .model import EstateManifest, RouteDecision, RouteEvaluation, RouteSpec, RoutingPolicy


def _matches_prefix(action_id: str, prefixes: tuple[str, ...]) -> bool:
    return any(action_id == prefix or action_id.startswith(prefix + ".") for prefix in prefixes)


def _constraint_bool(constraints: dict[str, Any], key: str, default: bool) -> bool:
    value = constraints.get(key, default)
    if not isinstance(value, bool):
        raise RouteRefused("invalid_route_constraint", {"constraint": key, "value": value})
    return value


def _constraint_int(constraints: dict[str, Any], key: str, default: int) -> int:
    value = constraints.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RouteRefused("invalid_route_constraint", {"constraint": key, "value": value})
    return value


def _constraint_strings(constraints: dict[str, Any], key: str) -> tuple[str, ...]:
    value = constraints.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise RouteRefused("invalid_route_constraint", {"constraint": key, "value": value})
    return tuple(value)


def score_route(route: RouteSpec, policy: RoutingPolicy) -> int:
    metrics = asdict(route.metrics)
    return sum(policy.weights[name] * metrics[name] for name in policy.weights)


def evaluate_route(
    manifest: EstateManifest,
    route: RouteSpec,
    *,
    action_id: str,
    required_role: str,
    required_mandate: str,
    constraints: dict[str, Any] | None = None,
    unavailable_route_ids: Iterable[str] = (),
    adapter_status: dict[str, str] | None = None,
) -> RouteEvaluation:
    constraints = constraints or {}
    unavailable = set(unavailable_route_ids)
    status = adapter_status or {}
    reasons: list[str] = []

    source = manifest.adapters[route.source_adapter]
    target = manifest.adapters[route.target_adapter]

    if route.route_id in unavailable:
        reasons.append("route_injected_unavailable")
    if status.get(source.adapter_id, source.default_status) == "unavailable":
        reasons.append("source_adapter_unavailable")
    if status.get(target.adapter_id, target.default_status) == "unavailable":
        reasons.append("target_adapter_unavailable")
    if not _matches_prefix(action_id, route.action_prefixes):
        reasons.append("action_prefix_mismatch")
    if route.required_role != required_role:
        reasons.append("role_mismatch")
    if route.required_mandate != required_mandate:
        reasons.append("mandate_mismatch")

    minimum_evidence = _constraint_int(
        constraints,
        "minimum_evidence",
        manifest.policy.minimum_evidence,
    )
    if route.metrics.evidence < minimum_evidence:
        reasons.append("evidence_below_floor")

    require_determinism = _constraint_bool(
        constraints,
        "require_determinism",
        manifest.policy.require_determinism,
    )
    if require_determinism and route.metrics.determinism < 4:
        reasons.append("determinism_below_floor")

    require_replayability = _constraint_bool(
        constraints,
        "require_replayability",
        manifest.policy.require_replayability,
    )
    if require_replayability and route.metrics.replayability < 4:
        reasons.append("replayability_below_floor")

    if _constraint_bool(constraints, "require_local", False) and route.metrics.locality < 4:
        reasons.append("locality_below_floor")

    max_latency = _constraint_int(constraints, "max_latency_ms", 2**31 - 1)
    if route.metrics.latency_ms > max_latency:
        reasons.append("latency_above_ceiling")

    max_cost = _constraint_int(constraints, "max_cost_microunits", 2**31 - 1)
    if route.metrics.cost_microunits > max_cost:
        reasons.append("cost_above_ceiling")

    required_tags = set(_constraint_strings(constraints, "require_tags"))
    if not required_tags.issubset(route.tags):
        reasons.append("required_tag_missing")

    forbidden_tags = set(_constraint_strings(constraints, "forbid_tags"))
    if forbidden_tags.intersection(route.tags):
        reasons.append("forbidden_tag_present")

    required_source_kinds = set(_constraint_strings(constraints, "source_kinds"))
    if required_source_kinds and source.kind not in required_source_kinds:
        reasons.append("source_kind_mismatch")

    required_target_organs = set(_constraint_strings(constraints, "target_organs"))
    if required_target_organs and target.organ_id not in required_target_organs:
        reasons.append("target_organ_mismatch")

    eligible = not reasons
    return RouteEvaluation(
        route_id=route.route_id,
        eligible=eligible,
        score=score_route(route, manifest.policy) if eligible else None,
        refusal_reasons=tuple(reasons),
        metrics=route.metrics,
    )


def choose_route(
    manifest: EstateManifest,
    *,
    action_id: str,
    required_role: str,
    required_mandate: str,
    candidate_route_ids: Iterable[str] | None = None,
    constraints: dict[str, Any] | None = None,
    unavailable_route_ids: Iterable[str] = (),
    adapter_status: dict[str, str] | None = None,
) -> RouteDecision:
    seed_candidates = tuple(candidate_route_ids or manifest.routes.keys())
    unknown = sorted(set(seed_candidates) - set(manifest.routes))
    if unknown:
        raise RouteRefused("unknown_route_candidate", {"route_ids": unknown})
    if not seed_candidates:
        raise RouteRefused("no_route_candidates")

    expanded: list[str] = []
    fallback_depth: dict[str, int] = {}
    queue: list[tuple[str, int]] = [(route_id, 0) for route_id in seed_candidates]
    cursor = 0
    while cursor < len(queue):
        route_id, depth = queue[cursor]
        cursor += 1
        known_depth = fallback_depth.get(route_id)
        if known_depth is not None and known_depth <= depth:
            continue
        fallback_depth[route_id] = depth
        if route_id not in expanded:
            expanded.append(route_id)
        for fallback_id in manifest.routes[route_id].fallback_route_ids:
            queue.append((fallback_id, depth + 1))
    candidates = tuple(expanded)

    evaluations = tuple(
        evaluate_route(
            manifest,
            manifest.routes[route_id],
            action_id=action_id,
            required_role=required_role,
            required_mandate=required_mandate,
            constraints=constraints,
            unavailable_route_ids=unavailable_route_ids,
            adapter_status=adapter_status,
        )
        for route_id in candidates
    )
    eligible = [evaluation for evaluation in evaluations if evaluation.eligible]
    if not eligible:
        raise RouteRefused(
            "no_admissible_route",
            {
                "action_id": action_id,
                "evaluations": [
                    {
                        "route_id": evaluation.route_id,
                        "refusal_reasons": list(evaluation.refusal_reasons),
                    }
                    for evaluation in evaluations
                ],
            },
        )

    # A declared fallback is considered only when no route at the earlier tier is
    # admissible. Within one tier, higher score wins and route id is the stable
    # exact-tie breaker. This prevents a high-scoring fallback from silently
    # replacing a healthy primary route.
    winning_depth = min(fallback_depth[item.route_id] for item in eligible)
    tier_eligible = [item for item in eligible if fallback_depth[item.route_id] == winning_depth]
    winner = sorted(tier_eligible, key=lambda item: (-int(item.score or 0), item.route_id))[0]
    return RouteDecision(
        route_id=winner.route_id,
        score=int(winner.score or 0),
        evaluations=evaluations,
    )
