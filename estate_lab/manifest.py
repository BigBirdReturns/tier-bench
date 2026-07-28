"""Manifest and scenario loading with fail-closed semantic validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .canonical import load_json
from .errors import ManifestError, ScenarioError
from .model import (
    EVIDENCE_RANK,
    AdapterSpec,
    AuthorityClaim,
    EstateManifest,
    FaultTrial,
    OrganSpec,
    ProbeSpec,
    RouteMetrics,
    RouteSpec,
    RoutingPolicy,
    RoutingTrial,
    ScenarioSpec,
    SemanticAction,
)


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _require_int(value: Any, label: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be >= {minimum}")
    return value


def _text_tuple(value: Any, label: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    items = _require_list(value, label)
    result = tuple(_require_text(item, f"{label}[]") for item in items)
    if not allow_empty and not result:
        raise ValueError(f"{label} must contain at least one item")
    if len(result) != len(set(result)):
        raise ValueError(f"{label} contains duplicate values")
    return result


def _unknown_keys(obj: dict[str, Any], allowed: Iterable[str], label: str) -> None:
    extras = sorted(set(obj) - set(allowed))
    if extras:
        raise ValueError(f"{label} contains unknown keys: {extras}")


def _parse_probe(raw: Any, label: str) -> ProbeSpec:
    obj = _require_mapping(raw, label)
    _unknown_keys(
        obj,
        {
            "id",
            "profile",
            "command",
            "timeout_seconds",
            "expected_exit_codes",
            "evidence_class",
            "required_paths",
        },
        label,
    )
    command = _text_tuple(obj.get("command", []), f"{label}.command", allow_empty=False)
    evidence_class = obj.get("evidence_class", "measured")
    if evidence_class not in EVIDENCE_RANK:
        raise ValueError(f"{label}.evidence_class is unknown: {evidence_class!r}")
    exit_codes_raw = _require_list(obj.get("expected_exit_codes", [0]), f"{label}.expected_exit_codes")
    exit_codes = tuple(_require_int(v, f"{label}.expected_exit_codes[]") for v in exit_codes_raw)
    if not exit_codes:
        raise ValueError(f"{label}.expected_exit_codes must not be empty")
    return ProbeSpec(
        probe_id=_require_text(obj.get("id"), f"{label}.id"),
        profile=_require_text(obj.get("profile", "smoke"), f"{label}.profile"),
        command=command,
        timeout_seconds=_require_int(obj.get("timeout_seconds", 120), f"{label}.timeout_seconds", minimum=1),
        expected_exit_codes=exit_codes,
        evidence_class=evidence_class,
        required_paths=_text_tuple(obj.get("required_paths", []), f"{label}.required_paths"),
    )


def _parse_organ(raw: Any, label: str) -> OrganSpec:
    obj = _require_mapping(raw, label)
    _unknown_keys(
        obj,
        {
            "id",
            "repository",
            "local_names",
            "function",
            "owns",
            "refuses",
            "capabilities",
            "probes",
        },
        label,
    )
    probes = tuple(
        _parse_probe(item, f"{label}.probes[{index}]")
        for index, item in enumerate(_require_list(obj.get("probes", []), f"{label}.probes"))
    )
    if len({probe.probe_id for probe in probes}) != len(probes):
        raise ValueError(f"{label}.probes contains duplicate ids")
    return OrganSpec(
        organ_id=_require_text(obj.get("id"), f"{label}.id"),
        repository=_require_text(obj.get("repository"), f"{label}.repository"),
        local_names=_text_tuple(obj.get("local_names", []), f"{label}.local_names", allow_empty=False),
        function=_require_text(obj.get("function"), f"{label}.function"),
        owns=_text_tuple(obj.get("owns", []), f"{label}.owns"),
        refuses=_text_tuple(obj.get("refuses", []), f"{label}.refuses"),
        capabilities=_text_tuple(obj.get("capabilities", []), f"{label}.capabilities", allow_empty=False),
        probes=probes,
    )


def _parse_adapter(raw: Any, label: str) -> AdapterSpec:
    obj = _require_mapping(raw, label)
    _unknown_keys(
        obj,
        {
            "id",
            "organ_id",
            "kind",
            "mode",
            "capabilities",
            "local_only",
            "deterministic",
            "replayable",
            "evidence_class",
            "default_status",
            "command",
            "timeout_seconds",
            "notes",
        },
        label,
    )
    mode = obj.get("mode", "synthetic")
    if mode not in {"synthetic", "command", "artifact", "human"}:
        raise ValueError(f"{label}.mode is unknown: {mode!r}")
    evidence_class = obj.get("evidence_class", "derived")
    if evidence_class not in EVIDENCE_RANK:
        raise ValueError(f"{label}.evidence_class is unknown: {evidence_class!r}")
    status = obj.get("default_status", "available")
    if status not in {"available", "degraded", "unavailable"}:
        raise ValueError(f"{label}.default_status is unknown: {status!r}")
    command = _text_tuple(obj.get("command", []), f"{label}.command")
    if mode == "command" and not command:
        raise ValueError(f"{label}.command is required for command adapters")
    return AdapterSpec(
        adapter_id=_require_text(obj.get("id"), f"{label}.id"),
        organ_id=_require_text(obj.get("organ_id"), f"{label}.organ_id"),
        kind=_require_text(obj.get("kind"), f"{label}.kind"),
        mode=mode,
        capabilities=_text_tuple(obj.get("capabilities", []), f"{label}.capabilities", allow_empty=False),
        local_only=bool(obj.get("local_only", True)),
        deterministic=bool(obj.get("deterministic", True)),
        replayable=bool(obj.get("replayable", True)),
        evidence_class=evidence_class,
        default_status=status,
        command=command,
        timeout_seconds=_require_int(obj.get("timeout_seconds", 30), f"{label}.timeout_seconds", minimum=1),
        notes=str(obj.get("notes", "")),
    )


def _parse_metrics(raw: Any, label: str) -> RouteMetrics:
    obj = _require_mapping(raw, label)
    allowed = {
        "evidence",
        "determinism",
        "replayability",
        "locality",
        "latency_ms",
        "cost_microunits",
        "fragility",
        "authority_risk",
    }
    _unknown_keys(obj, allowed, label)
    missing = sorted(allowed - set(obj))
    if missing:
        raise ValueError(f"{label} is missing metrics: {missing}")
    bounded = {}
    for key in ("evidence", "determinism", "replayability", "locality", "fragility", "authority_risk"):
        number = _require_int(obj[key], f"{label}.{key}", minimum=0)
        if number > 5:
            raise ValueError(f"{label}.{key} must be <= 5")
        bounded[key] = number
    return RouteMetrics(
        evidence=bounded["evidence"],
        determinism=bounded["determinism"],
        replayability=bounded["replayability"],
        locality=bounded["locality"],
        latency_ms=_require_int(obj["latency_ms"], f"{label}.latency_ms", minimum=0),
        cost_microunits=_require_int(obj["cost_microunits"], f"{label}.cost_microunits", minimum=0),
        fragility=bounded["fragility"],
        authority_risk=bounded["authority_risk"],
    )


def _parse_route(raw: Any, label: str) -> RouteSpec:
    obj = _require_mapping(raw, label)
    _unknown_keys(
        obj,
        {
            "id",
            "source_adapter",
            "target_adapter",
            "action_prefixes",
            "required_role",
            "required_mandate",
            "tags",
            "metrics",
            "fallback_route_ids",
            "notes",
        },
        label,
    )
    return RouteSpec(
        route_id=_require_text(obj.get("id"), f"{label}.id"),
        source_adapter=_require_text(obj.get("source_adapter"), f"{label}.source_adapter"),
        target_adapter=_require_text(obj.get("target_adapter"), f"{label}.target_adapter"),
        action_prefixes=_text_tuple(obj.get("action_prefixes", []), f"{label}.action_prefixes", allow_empty=False),
        required_role=_require_text(obj.get("required_role"), f"{label}.required_role"),
        required_mandate=_require_text(obj.get("required_mandate"), f"{label}.required_mandate"),
        tags=_text_tuple(obj.get("tags", []), f"{label}.tags"),
        metrics=_parse_metrics(obj.get("metrics"), f"{label}.metrics"),
        fallback_route_ids=_text_tuple(obj.get("fallback_route_ids", []), f"{label}.fallback_route_ids"),
        notes=str(obj.get("notes", "")),
    )


def _parse_policy(raw: Any) -> RoutingPolicy:
    obj = _require_mapping(raw, "policy")
    _unknown_keys(
        obj,
        {"minimum_evidence", "require_determinism", "require_replayability", "prefer_local", "weights"},
        "policy",
    )
    weights_obj = _require_mapping(obj.get("weights", {}), "policy.weights")
    default_weights = RoutingPolicy().weights
    unknown = sorted(set(weights_obj) - set(default_weights))
    if unknown:
        raise ValueError(f"policy.weights contains unknown keys: {unknown}")
    weights = dict(default_weights)
    for key, value in weights_obj.items():
        weights[key] = _require_int(value, f"policy.weights.{key}")
    minimum_evidence = _require_int(obj.get("minimum_evidence", 2), "policy.minimum_evidence", minimum=0)
    if minimum_evidence > 5:
        raise ValueError("policy.minimum_evidence must be <= 5")
    return RoutingPolicy(
        minimum_evidence=minimum_evidence,
        require_determinism=bool(obj.get("require_determinism", True)),
        require_replayability=bool(obj.get("require_replayability", True)),
        prefer_local=bool(obj.get("prefer_local", True)),
        weights=weights,
    )


def load_manifest(path: Path) -> EstateManifest:
    try:
        raw = _require_mapping(load_json(path), "manifest")
        _unknown_keys(raw, {"format", "estate_id", "policy", "organs", "adapters", "routes"}, "manifest")
        if raw.get("format") != "axm-estate-lab/1":
            raise ValueError("manifest.format must be axm-estate-lab/1")

        organs_list = _require_list(raw.get("organs"), "manifest.organs")
        adapters_list = _require_list(raw.get("adapters"), "manifest.adapters")
        routes_list = _require_list(raw.get("routes"), "manifest.routes")

        organs = {
            organ.organ_id: organ
            for index, item in enumerate(organs_list)
            for organ in (_parse_organ(item, f"manifest.organs[{index}]"),)
        }
        adapters = {
            adapter.adapter_id: adapter
            for index, item in enumerate(adapters_list)
            for adapter in (_parse_adapter(item, f"manifest.adapters[{index}]"),)
        }
        routes = {
            route.route_id: route
            for index, item in enumerate(routes_list)
            for route in (_parse_route(item, f"manifest.routes[{index}]"),)
        }
        if len(organs) != len(organs_list):
            raise ValueError("manifest.organs contains duplicate ids")
        if len(adapters) != len(adapters_list):
            raise ValueError("manifest.adapters contains duplicate ids")
        if len(routes) != len(routes_list):
            raise ValueError("manifest.routes contains duplicate ids")

        for adapter in adapters.values():
            if adapter.organ_id not in organs:
                raise ValueError(f"adapter {adapter.adapter_id} references unknown organ {adapter.organ_id}")
        for route in routes.values():
            if route.source_adapter not in adapters:
                raise ValueError(f"route {route.route_id} references unknown source adapter")
            if route.target_adapter not in adapters:
                raise ValueError(f"route {route.route_id} references unknown target adapter")
            for fallback in route.fallback_route_ids:
                if fallback not in routes:
                    raise ValueError(f"route {route.route_id} references unknown fallback route {fallback}")
                if fallback == route.route_id:
                    raise ValueError(f"route {route.route_id} cannot fall back to itself")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit_fallbacks(route_id: str) -> None:
            if route_id in visiting:
                raise ValueError(f"route fallback cycle includes {route_id}")
            if route_id in visited:
                return
            visiting.add(route_id)
            for fallback_id in routes[route_id].fallback_route_ids:
                visit_fallbacks(fallback_id)
            visiting.remove(route_id)
            visited.add(route_id)

        for route_id in sorted(routes):
            visit_fallbacks(route_id)

        return EstateManifest(
            format=raw["format"],
            estate_id=_require_text(raw.get("estate_id"), "manifest.estate_id"),
            organs=organs,
            adapters=adapters,
            routes=routes,
            policy=_parse_policy(raw.get("policy", {})),
            source_path=path.resolve(),
            raw=raw,
        )
    except (OSError, ValueError, TypeError) as exc:
        raise ManifestError(f"invalid estate manifest {path}: {exc}") from exc


def _parse_authority(raw: Any, label: str) -> AuthorityClaim:
    obj = _require_mapping(raw, label)
    _unknown_keys(obj, {"actor", "role", "mandate", "ownership_epoch"}, label)
    return AuthorityClaim(
        actor=_require_text(obj.get("actor"), f"{label}.actor"),
        role=_require_text(obj.get("role"), f"{label}.role"),
        mandate=_require_text(obj.get("mandate"), f"{label}.mandate"),
        ownership_epoch=_require_int(obj.get("ownership_epoch"), f"{label}.ownership_epoch", minimum=0),
    )


def _parse_action(raw: Any, label: str) -> SemanticAction:
    obj = _require_mapping(raw, label)
    _unknown_keys(
        obj,
        {
            "step_id",
            "semantic_id",
            "subject",
            "operation",
            "state_path",
            "value",
            "required_role",
            "required_mandate",
            "authority",
            "route_ids",
            "route_query",
            "expected",
            "projection",
        },
        label,
    )
    operation = obj.get("operation")
    if operation not in {"set", "increment", "append", "remove", "toggle"}:
        raise ValueError(f"{label}.operation is unknown: {operation!r}")
    state_path = _require_text(obj.get("state_path"), f"{label}.state_path")
    if not state_path.startswith("/") or state_path == "/":
        raise ValueError(f"{label}.state_path must be a non-root JSON pointer")
    return SemanticAction(
        step_id=_require_text(obj.get("step_id"), f"{label}.step_id"),
        semantic_id=_require_text(obj.get("semantic_id"), f"{label}.semantic_id"),
        subject=_require_text(obj.get("subject"), f"{label}.subject"),
        operation=operation,
        state_path=state_path,
        value=obj.get("value"),
        required_role=_require_text(obj.get("required_role"), f"{label}.required_role"),
        required_mandate=_require_text(obj.get("required_mandate"), f"{label}.required_mandate"),
        authority=_parse_authority(obj.get("authority"), f"{label}.authority"),
        route_ids=_text_tuple(obj.get("route_ids", []), f"{label}.route_ids"),
        route_query=_require_mapping(obj.get("route_query", {}), f"{label}.route_query"),
        expected=_require_mapping(obj.get("expected", {}), f"{label}.expected"),
        projection=_require_mapping(obj.get("projection", {}), f"{label}.projection"),
    )


def _parse_routing_trial(raw: Any, label: str) -> RoutingTrial:
    obj = _require_mapping(raw, label)
    _unknown_keys(
        obj,
        {
            "id",
            "action_prefix",
            "candidate_route_ids",
            "unavailable_route_ids",
            "constraints",
            "expected_route_id",
            "expected_outcome",
        },
        label,
    )
    expected_route = obj.get("expected_route_id")
    if expected_route is not None:
        expected_route = _require_text(expected_route, f"{label}.expected_route_id")
    expected_outcome = obj.get("expected_outcome", "selected")
    if expected_outcome not in {"selected", "refused"}:
        raise ValueError(f"{label}.expected_outcome must be selected or refused")
    return RoutingTrial(
        trial_id=_require_text(obj.get("id"), f"{label}.id"),
        action_prefix=_require_text(obj.get("action_prefix"), f"{label}.action_prefix"),
        candidate_route_ids=_text_tuple(obj.get("candidate_route_ids", []), f"{label}.candidate_route_ids"),
        unavailable_route_ids=_text_tuple(obj.get("unavailable_route_ids", []), f"{label}.unavailable_route_ids"),
        constraints=_require_mapping(obj.get("constraints", {}), f"{label}.constraints"),
        expected_route_id=expected_route,
        expected_outcome=expected_outcome,
    )


def _parse_fault_trial(raw: Any, label: str) -> FaultTrial:
    obj = _require_mapping(raw, label)
    _unknown_keys(obj, {"id", "fault", "route_id", "expected_outcome", "parameters"}, label)
    route_id = obj.get("route_id")
    if route_id is not None:
        route_id = _require_text(route_id, f"{label}.route_id")
    return FaultTrial(
        trial_id=_require_text(obj.get("id"), f"{label}.id"),
        fault=_require_text(obj.get("fault"), f"{label}.fault"),
        route_id=route_id,
        expected_outcome=_require_text(obj.get("expected_outcome"), f"{label}.expected_outcome"),
        parameters=_require_mapping(obj.get("parameters", {}), f"{label}.parameters"),
    )


def load_scenario(path: Path, manifest: EstateManifest) -> ScenarioSpec:
    try:
        raw = _require_mapping(load_json(path), "scenario")
        _unknown_keys(
            raw,
            {
                "format",
                "id",
                "title",
                "kind",
                "objective",
                "initial_state",
                "actions",
                "equivalence_route_ids",
                "expected_final_state",
                "routing_trials",
                "fault_trials",
                "invariants",
            },
            "scenario",
        )
        if raw.get("format") != "axm-estate-scenario/1":
            raise ValueError("scenario.format must be axm-estate-scenario/1")
        kind = raw.get("kind")
        if kind not in {"equivalence", "sequence"}:
            raise ValueError("scenario.kind must be equivalence or sequence")
        actions = tuple(
            _parse_action(item, f"scenario.actions[{index}]")
            for index, item in enumerate(_require_list(raw.get("actions"), "scenario.actions"))
        )
        if not actions:
            raise ValueError("scenario.actions must not be empty")
        if len({action.step_id for action in actions}) != len(actions):
            raise ValueError("scenario.actions contains duplicate step ids")

        equivalence_routes = _text_tuple(raw.get("equivalence_route_ids", []), "scenario.equivalence_route_ids")
        if kind == "equivalence" and not equivalence_routes:
            raise ValueError("equivalence scenarios require equivalence_route_ids")
        if kind == "equivalence" and len(actions) != 1:
            raise ValueError("equivalence scenarios require exactly one semantic action")

        routing_trials = tuple(
            _parse_routing_trial(item, f"scenario.routing_trials[{index}]")
            for index, item in enumerate(_require_list(raw.get("routing_trials", []), "scenario.routing_trials"))
        )
        fault_trials = tuple(
            _parse_fault_trial(item, f"scenario.fault_trials[{index}]")
            for index, item in enumerate(_require_list(raw.get("fault_trials", []), "scenario.fault_trials"))
        )

        referenced_routes = set(equivalence_routes)
        for action in actions:
            referenced_routes.update(action.route_ids)
        for trial in routing_trials:
            referenced_routes.update(trial.candidate_route_ids)
            referenced_routes.update(trial.unavailable_route_ids)
            if trial.expected_route_id:
                referenced_routes.add(trial.expected_route_id)
        for trial in fault_trials:
            if trial.route_id:
                referenced_routes.add(trial.route_id)
        unknown_routes = sorted(referenced_routes - set(manifest.routes))
        if unknown_routes:
            raise ValueError(f"scenario references unknown routes: {unknown_routes}")

        for action in actions:
            if action.required_role != action.authority.role:
                raise ValueError(
                    f"action {action.step_id} authority role {action.authority.role!r} "
                    f"does not match required role {action.required_role!r}"
                )
            if action.required_mandate != action.authority.mandate:
                raise ValueError(
                    f"action {action.step_id} authority mandate does not match required mandate"
                )

        return ScenarioSpec(
            format=raw["format"],
            scenario_id=_require_text(raw.get("id"), "scenario.id"),
            title=_require_text(raw.get("title"), "scenario.title"),
            kind=kind,
            objective=_require_text(raw.get("objective"), "scenario.objective"),
            initial_state=_require_mapping(raw.get("initial_state"), "scenario.initial_state"),
            actions=actions,
            equivalence_route_ids=equivalence_routes,
            expected_final_state=_require_mapping(raw.get("expected_final_state", {}), "scenario.expected_final_state"),
            routing_trials=routing_trials,
            fault_trials=fault_trials,
            invariants=_text_tuple(raw.get("invariants", []), "scenario.invariants"),
            source_path=path.resolve(),
            raw=raw,
        )
    except (OSError, ValueError, TypeError) as exc:
        raise ScenarioError(f"invalid scenario {path}: {exc}") from exc
