"""Vendor-neutral contracts for the Task Floor interoperability and evidence layer.

Task Floor does not replace MCP, A2A, AG-UI, browser runtimes, policy engines, or
telemetry. It defines the minimum state, effect, authority, acceptance, and evidence
contracts that remain stable when those backends are exchanged.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any
from urllib.parse import urlparse

from .playwright_computer_common import (
    PlaywrightComputerError,
    hash_json,
    safe_id,
    without_hash,
)

MANIFEST_SCHEMA = "task-floor/capability-manifest@1"
CARTRIDGE_SCHEMA = "task-floor/cartridge@1"
STATE_SCHEMA = "task-floor/state@1"
ACTION_SCHEMA = "task-floor/action@1"
ACTION_RECEIPT_SCHEMA = "task-floor/action-receipt@1"
TRAJECTORY_SCHEMA = "task-floor/trajectory@1"
BUNDLE_SCHEMA = "task-floor/interop-bundle@1"
CONFORMANCE_SCHEMA = "task-floor/conformance-report@1"
DRIVER_REQUEST_SCHEMA = "task-floor/driver-request@1"
DRIVER_RESPONSE_SCHEMA = "task-floor/driver-response@1"
REGISTRY_SCHEMA = "task-floor/oss-registry@1"
APPROVAL_SCHEMA = "task-floor/approval@1"
ACCEPTANCE_SCHEMA = "task-floor/acceptance-result@1"
CLAIM_ATTESTATION_SCHEMA = "task-floor/claim-attestation@1"
SKILL_SCHEMA = "task-floor/skill-package@1"
REPLAY_PLAN_SCHEMA = "task-floor/replay-plan@1"

HASH_ALGORITHMS = {"sha256"}
INTERFACE_PROTOCOLS = {
    "native-json",
    "mcp",
    "a2a",
    "ag-ui",
    "browsergym",
    "cua",
    "opentelemetry",
    "in-toto",
    "opa",
    "cloudevents",
    "agentrx",
    "spiffe",
    "cedar",
    "langgraph",
}
TRANSPORTS = {
    "stdio",
    "http-json",
    "json-rpc",
    "streamable-http",
    "sse",
    "websocket",
    "shared-filesystem",
    "in-process",
}
SURFACES = {
    "browser.semantic",
    "browser.visual",
    "desktop.accessibility",
    "desktop.visual",
    "workspace",
    "terminal",
    "api",
    "human",
}
EFFECTS = {
    "read",
    "interactive",
    "local_write",
    "external_write",
    "destructive",
    "financial",
    "identity",
    "sensitive",
    "privileged",
}
AUTHORITIES = {
    "observer",
    "planner",
    "critic",
    "policy",
    "executor",
    "acceptor",
    "credential_custodian",
    "artifact_custodian",
    "human",
}
DRIVER_OPS = {
    "describe",
    "reset",
    "observe",
    "act",
    "takeover",
    "release",
    "accept",
    "close",
}

PROFILE_ORDER = ("TF0", "TF1", "TF2", "TF3", "TF4", "TF5", "TF6", "TF7")
PROFILE_TITLES = {
    "TF0": "Discoverable transport",
    "TF1": "State-bound execution",
    "TF2": "Governed effects",
    "TF3": "External acceptance and evidence",
    "TF4": "Human and credential resilience",
    "TF5": "Protocol, telemetry, and provenance portability",
    "TF6": "Adversarial replay and recovery",
    "TF7": "Evidence-backed production claim",
}
PROFILE_REQUIREMENTS = {
    "TF0": (
        "manifest.valid",
        "interface.declared",
        "evidence.sha256",
    ),
    "TF1": (
        "state.content_addressed",
        "state.action_binding",
        "evidence.action_receipts",
        "execution.optimistic_concurrency",
    ),
    "TF2": (
        "effects.declared",
        "effects.enforced",
        "effects.approval",
        "authority.executor_separated",
        "execution.idempotency",
    ),
    "TF3": (
        "acceptance.external_verifier",
        "acceptance.project_handoff",
        "acceptance.postconditions",
        "evidence.artifact_hashes",
    ),
    "TF4": (
        "lifecycle.human_takeover",
        "lifecycle.resume",
        "security.secrets_isolated",
        "security.credential_lease",
        "security.network_policy",
        "identity.delegation",
    ),
    "TF5": (
        "interop.mcp",
        "interop.a2a",
        "interop.ag-ui",
        "interop.opentelemetry",
        "interop.in-toto",
        "interop.opa",
        "interop.cloudevents",
    ),
    "TF6": (
        "resilience.mutation_suite",
        "resilience.prompt_injection_tests",
        "diagnostics.failure_taxonomy",
        "diagnostics.counterfactual_replay",
        "execution.compensation",
        "privacy.redaction",
    ),
    "TF7": (
        "conformance.claim_verification",
        "identity.workload_attestation",
        "evidence.signatures",
        "supply_chain.reproducible_environment",
        "privacy.retention",
        "versioning.negotiation",
        "production.qualified",
    ),
}



def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlaywrightComputerError(f"{label} must be an object")
    return value


def _array(value: Any, label: str, *, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        suffix = " and non-empty" if nonempty else ""
        raise PlaywrightComputerError(f"{label} must be an array{suffix}")
    return value


def _text(
    value: Any,
    label: str,
    *,
    limit: int = 4000,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise PlaywrightComputerError(f"{label} must be a string of at most {limit} chars")
    if not allow_empty and not value.strip():
        raise PlaywrightComputerError(f"{label} must be non-empty")
    return value if allow_empty else value.strip()


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise PlaywrightComputerError(f"{label} must be boolean")
    return value


def _integer(value: Any, label: str, *, low: int = 0, high: int = 2**63 - 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise PlaywrightComputerError(f"{label} must be an integer between {low} and {high}")
    return value


def _choice(value: Any, label: str, allowed: set[str]) -> str:
    result = _text(value, label, limit=120)
    if result not in allowed:
        raise PlaywrightComputerError(f"{label} must be one of {sorted(allowed)}")
    return result


def _string_list(
    value: Any,
    label: str,
    *,
    allowed: set[str] | None = None,
    nonempty: bool = False,
) -> list[str]:
    result: list[str] = []
    for index, raw in enumerate(_array(value, label, nonempty=nonempty)):
        item = _text(raw, f"{label}[{index}]", limit=300)
        if allowed is not None and item not in allowed:
            raise PlaywrightComputerError(
                f"{label}[{index}] must be one of {sorted(allowed)}"
            )
        if item not in result:
            result.append(item)
    return result


def _url(value: Any, label: str, *, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    result = _text(value, label, limit=4000)
    parsed = urlparse(result)
    if parsed.scheme not in {"http", "https", "urn"}:
        raise PlaywrightComputerError(f"{label} must use http, https, or urn")
    return result


def _bool_section(
    value: Any,
    label: str,
    fields: tuple[str, ...],
    *,
    defaults: dict[str, bool] | None = None,
) -> dict[str, bool]:
    row = _object(value, label)
    unknown = set(row) - set(fields)
    if unknown:
        raise PlaywrightComputerError(f"{label} has unknown fields: {sorted(unknown)}")
    defaults = defaults or {}
    return {
        field: _boolean(row.get(field, defaults.get(field, False)), f"{label}.{field}")
        for field in fields
    }


def _interface(raw: Any, index: int) -> dict[str, Any]:
    label = f"manifest.interfaces[{index}]"
    row = _object(raw, label)
    protocol = _choice(row.get("protocol"), f"{label}.protocol", INTERFACE_PROTOCOLS)
    transport = _choice(row.get("transport"), f"{label}.transport", TRANSPORTS)
    endpoint = row.get("endpoint")
    if endpoint is not None:
        endpoint = _text(endpoint, f"{label}.endpoint", limit=4000)
    return {
        "protocol": protocol,
        "version": _text(row.get("version", "unspecified"), f"{label}.version", limit=120),
        "role": _text(row.get("role", "server"), f"{label}.role", limit=80),
        "transport": transport,
        "endpoint": endpoint,
        "extensions": sorted(
            set(_string_list(row.get("extensions", []), f"{label}.extensions"))
        ),
    }


def _surface(raw: Any, index: int) -> dict[str, Any]:
    label = f"manifest.surfaces[{index}]"
    row = _object(raw, label)
    return {
        "id": safe_id(row.get("id"), f"{label}.id"),
        "kind": _choice(row.get("kind"), f"{label}.kind", SURFACES),
        "observe": _boolean(row.get("observe", True), f"{label}.observe"),
        "act": _boolean(row.get("act", False), f"{label}.act"),
        "state_bound": _boolean(row.get("state_bound", False), f"{label}.state_bound"),
        "supports_artifacts": _boolean(
            row.get("supports_artifacts", False), f"{label}.supports_artifacts"
        ),
        "operations": sorted(
            set(_string_list(row.get("operations", []), f"{label}.operations"))
        ),
    }


def _authority(value: Any) -> dict[str, list[str]]:
    row = _object(value, "manifest.authority")
    result: dict[str, list[str]] = {}
    for key, raw in row.items():
        if key not in AUTHORITIES:
            raise PlaywrightComputerError(
                f"manifest.authority has unknown authority {key!r}"
            )
        result[key] = sorted(
            set(_string_list(raw, f"manifest.authority.{key}", nonempty=True))
        )
    required = {"executor", "acceptor", "artifact_custodian"}
    missing = required - set(result)
    if missing:
        raise PlaywrightComputerError(
            f"manifest.authority is missing required roles: {sorted(missing)}"
        )
    return result


def validate_manifest(raw: Any) -> dict[str, Any]:
    row = _object(raw, "manifest")
    if row.get("schema") != MANIFEST_SCHEMA:
        raise PlaywrightComputerError(f"manifest.schema must be {MANIFEST_SCHEMA}")
    provider = _object(row.get("provider", {}), "manifest.provider")
    interfaces = [
        _interface(value, index)
        for index, value in enumerate(
            _array(row.get("interfaces"), "manifest.interfaces", nonempty=True)
        )
    ]
    surfaces = [
        _surface(value, index)
        for index, value in enumerate(
            _array(row.get("surfaces"), "manifest.surfaces", nonempty=True)
        )
    ]
    surface_ids = [surface["id"] for surface in surfaces]
    if len(surface_ids) != len(set(surface_ids)):
        raise PlaywrightComputerError("manifest.surfaces ids must be unique")
    lifecycle = _bool_section(
        row.get("lifecycle", {}),
        "manifest.lifecycle",
        (
            "persistent_state",
            "streaming",
            "async_tasks",
            "cancel",
            "resume",
            "human_takeover",
        ),
    )
    state = _bool_section(
        row.get("state", {}),
        "manifest.state",
        (
            "content_addressed",
            "exact_action_binding",
            "replay",
            "snapshots",
            "conflict_detection",
        ),
    )
    effects_row = _object(row.get("effects", {}), "manifest.effects")
    taxonomy = _string_list(
        effects_row.get("taxonomy", sorted(EFFECTS)),
        "manifest.effects.taxonomy",
        allowed=EFFECTS,
        nonempty=True,
    )
    effects = {
        "taxonomy": taxonomy,
        "declared": _boolean(
            effects_row.get("declared", False), "manifest.effects.declared"
        ),
        "argument_scoped": _boolean(
            effects_row.get("argument_scoped", False),
            "manifest.effects.argument_scoped",
        ),
        "enforced": _boolean(
            effects_row.get("enforced", False), "manifest.effects.enforced"
        ),
        "approval": _boolean(
            effects_row.get("approval", False), "manifest.effects.approval"
        ),
        "postconditions": _boolean(
            effects_row.get("postconditions", False),
            "manifest.effects.postconditions",
        ),
        "default": _choice(
            effects_row.get("default", "privileged"),
            "manifest.effects.default",
            EFFECTS,
        ),
    }
    evidence = _bool_section(
        row.get("evidence", {}),
        "manifest.evidence",
        (
            "content_addressed",
            "event_chain",
            "action_receipts",
            "artifact_hashes",
            "trajectory_export",
            "signatures",
        ),
    )
    acceptance = _bool_section(
        row.get("acceptance", {}),
        "manifest.acceptance",
        (
            "external_verifier",
            "hidden_state",
            "postconditions",
            "project_handoff",
            "mutation_suite",
        ),
    )
    security = _bool_section(
        row.get("security", {}),
        "manifest.security",
        (
            "authentication",
            "authorization",
            "secrets_isolated",
            "credential_lease",
            "network_policy",
            "sandbox",
            "prompt_injection_boundary",
        ),
    )
    observability = _bool_section(
        row.get("observability", {}),
        "manifest.observability",
        (
            "trace_context",
            "opentelemetry",
            "token_usage",
            "cost",
            "human_time",
            "evaluation_events",
        ),
    )
    identity = _bool_section(
        row.get("identity", {}),
        "manifest.identity",
        (
            "workload_identity",
            "agent_delegation",
            "runtime_attestation",
            "signed_messages",
        ),
    )
    execution = _bool_section(
        row.get("execution", {}),
        "manifest.execution",
        (
            "optimistic_concurrency",
            "idempotency_keys",
            "transactions",
            "compensation",
            "rollback",
        ),
    )
    privacy = _bool_section(
        row.get("privacy", {}),
        "manifest.privacy",
        (
            "redaction",
            "retention",
            "data_classification",
            "deletion_receipts",
            "secret_exclusion",
        ),
    )
    supply_chain = _bool_section(
        row.get("supply_chain", {}),
        "manifest.supply_chain",
        (
            "dependency_inventory",
            "signed_skills",
            "reproducible_environment",
            "model_runtime_identity",
            "build_provenance",
        ),
    )
    versioning = _bool_section(
        row.get("versioning", {}),
        "manifest.versioning",
        (
            "schema_negotiation",
            "backward_compatibility",
            "deprecation_policy",
        ),
    )
    diagnostics = _bool_section(
        row.get("diagnostics", {}),
        "manifest.diagnostics",
        (
            "failure_taxonomy",
            "counterfactual_replay",
            "invariant_checks",
            "claim_verification",
        ),
    )
    resilience = _bool_section(
        row.get("resilience", {}),
        "manifest.resilience",
        (
            "mutation_suite",
            "prompt_injection_tests",
            "recovery",
            "role_reversal",
        ),
    )
    interop = _bool_section(
        row.get("interop", {}),
        "manifest.interop",
        (
            "mcp",
            "a2a",
            "ag-ui",
            "opentelemetry",
            "in-toto",
            "opa",
            "browsergym",
            "cloudevents",
            "agentrx",
            "cua",
            "spiffe",
            "cedar",
            "langgraph",
        ),
    )
    conformance_row = _object(row.get("conformance", {}), "manifest.conformance")
    profiles_claimed = _string_list(
        conformance_row.get("profiles_claimed", []),
        "manifest.conformance.profiles_claimed",
        allowed=set(PROFILE_ORDER),
    )
    claim_scope = _text(
        conformance_row.get("claim_scope", "unqualified"),
        "manifest.conformance.claim_scope",
        limit=1000,
    )
    production_qualified = _boolean(
        conformance_row.get("production_qualified", False),
        "manifest.conformance.production_qualified",
    )
    normalized: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "id": safe_id(row.get("id"), "manifest.id"),
        "name": _text(row.get("name"), "manifest.name", limit=300),
        "version": _text(row.get("version"), "manifest.version", limit=120),
        "description": _text(
            row.get("description", ""),
            "manifest.description",
            limit=4000,
            allow_empty=True,
        ),
        "documentation_url": _url(
            row.get("documentation_url"), "manifest.documentation_url"
        ),
        "provider": {
            "name": _text(
                provider.get("name", "unknown"), "manifest.provider.name", limit=300
            ),
            "url": _url(provider.get("url"), "manifest.provider.url"),
        },
        "license": _text(
            row.get("license", "unspecified"), "manifest.license", limit=200
        ),
        "interfaces": sorted(
            interfaces,
            key=lambda value: (
                value["protocol"],
                value["transport"],
                value.get("endpoint") or "",
            ),
        ),
        "surfaces": sorted(surfaces, key=lambda value: value["id"]),
        "lifecycle": lifecycle,
        "state": state,
        "authority": _authority(row.get("authority", {})),
        "effects": effects,
        "evidence": evidence,
        "acceptance": acceptance,
        "security": security,
        "observability": observability,
        "identity": identity,
        "execution": execution,
        "privacy": privacy,
        "supply_chain": supply_chain,
        "versioning": versioning,
        "diagnostics": diagnostics,
        "resilience": resilience,
        "interop": interop,
        "conformance": {
            "profiles_claimed": profiles_claimed,
            "claim_scope": claim_scope,
            "production_qualified": production_qualified,
            "evidence": deepcopy(conformance_row.get("evidence", [])),
        },
    }
    expected_manifest_sha256 = hash_json(normalized)
    observed_manifest_sha256 = row.get("manifest_sha256")
    if (
        observed_manifest_sha256 is not None
        and observed_manifest_sha256 != expected_manifest_sha256
    ):
        raise PlaywrightComputerError(
            "manifest.manifest_sha256 does not match canonical content"
        )
    normalized["manifest_sha256"] = expected_manifest_sha256
    return normalized


def verify_manifest(raw: Any) -> list[str]:
    try:
        normalized = validate_manifest(raw)
    except PlaywrightComputerError as exc:
        return [str(exc)]
    errors: list[str] = []
    observed = raw.get("manifest_sha256") if isinstance(raw, dict) else None
    if observed is not None and observed != normalized["manifest_sha256"]:
        errors.append("manifest.manifest_sha256 does not match canonical content")
    return errors


def _effect_policy(raw: Any, label: str) -> dict[str, Any]:
    row = _object(raw, label)
    preauthorized = _string_list(
        row.get("preauthorized_effects", ["read", "interactive"]),
        f"{label}.preauthorized_effects",
        allowed=EFFECTS,
    )
    approval_required = _string_list(
        row.get(
            "approval_effects",
            [
                "external_write",
                "destructive",
                "financial",
                "identity",
                "sensitive",
                "privileged",
            ],
        ),
        f"{label}.approval_effects",
        allowed=EFFECTS,
    )
    overlap = set(preauthorized) & set(approval_required)
    if overlap:
        raise PlaywrightComputerError(
            f"{label} effects cannot be both preauthorized and approval-governed: {sorted(overlap)}"
        )
    return {
        "preauthorized_effects": preauthorized,
        "approval_effects": approval_required,
        "default": _choice(
            row.get("default", "deny"),
            f"{label}.default",
            {"deny", "approval"},
        ),
    }


def validate_cartridge(raw: Any) -> dict[str, Any]:
    row = _object(raw, "cartridge")
    schema = row.get("schema")
    if schema == "tier-bench/task-computer-scenario@1":
        surfaces = row.get("surface_order", [])
        normalized_surfaces = []
        mapping = {
            "playwright": "browser.semantic",
            "screen_ghost": "browser.visual",
            "workspace": "workspace",
            "human": "human",
        }
        for surface in surfaces:
            if surface not in mapping:
                raise PlaywrightComputerError(
                    f"task-computer scenario uses unsupported surface {surface!r}"
                )
            normalized_surfaces.append(mapping[surface])
        effects = sorted(
            {
                step.get("effect", "read")
                for step in row.get("reference_plan", [])
                if isinstance(step, dict)
            }
        )
        acceptance = deepcopy(row.get("acceptance", []))
        handoff = deepcopy(row.get("handoff", {}))
        variants = list(row.get("variants", ["base"]))
        result = {
            "schema": CARTRIDGE_SCHEMA,
            "id": safe_id(row.get("id"), "cartridge.id"),
            "version": "1",
            "project": safe_id(row.get("project"), "cartridge.project"),
            "title": _text(row.get("title", row.get("id")), "cartridge.title", limit=300),
            "goal": _text(row.get("goal"), "cartridge.goal", limit=12000),
            "surfaces": normalized_surfaces,
            "effects": effects,
            "effect_policy": _effect_policy(
                row.get("policy", {}), "cartridge.effect_policy"
            ),
            "acceptance": acceptance,
            "acceptance_authority": deepcopy(
                row.get("acceptance_authority", {"kind": "external_hidden_state"})
            ),
            "handoff": handoff,
            "failure_default": _choice(
                row.get("failure_default", "hold"),
                "cartridge.failure_default",
                {"hold", "deny", "rollback"},
            ),
            "invariants": deepcopy(row.get("invariants", [])),
            "environment": deepcopy(row.get("environment", {})),
            "variants": variants,
            "mutation_dimensions": [
                value
                for value in variants
                if value not in {"base", "default"}
            ],
            "source_schema": schema,
        }
    elif schema == CARTRIDGE_SCHEMA:
        result = {
            "schema": CARTRIDGE_SCHEMA,
            "id": safe_id(row.get("id"), "cartridge.id"),
            "version": _text(row.get("version", "1"), "cartridge.version", limit=120),
            "project": safe_id(row.get("project"), "cartridge.project"),
            "title": _text(row.get("title", row.get("id")), "cartridge.title", limit=300),
            "goal": _text(row.get("goal"), "cartridge.goal", limit=12000),
            "surfaces": _string_list(
                row.get("surfaces"),
                "cartridge.surfaces",
                allowed=SURFACES,
                nonempty=True,
            ),
            "effects": _string_list(
                row.get("effects", []),
                "cartridge.effects",
                allowed=EFFECTS,
            ),
            "effect_policy": _effect_policy(
                row.get("effect_policy", {}), "cartridge.effect_policy"
            ),
            "acceptance": deepcopy(
                _array(row.get("acceptance"), "cartridge.acceptance", nonempty=True)
            ),
            "acceptance_authority": deepcopy(
                row.get("acceptance_authority", {"kind": "external"})
            ),
            "handoff": deepcopy(_object(row.get("handoff", {}), "cartridge.handoff")),
            "failure_default": _choice(
                row.get("failure_default", "hold"),
                "cartridge.failure_default",
                {"hold", "deny", "rollback"},
            ),
            "invariants": deepcopy(
                _array(row.get("invariants", []), "cartridge.invariants")
            ),
            "environment": deepcopy(
                _object(row.get("environment", {}), "cartridge.environment")
            ),
            "variants": _string_list(
                row.get("variants", ["base"]), "cartridge.variants", nonempty=True
            ),
            "mutation_dimensions": _string_list(
                row.get("mutation_dimensions", []),
                "cartridge.mutation_dimensions",
            ),
            "source_schema": _text(
                row.get("source_schema", CARTRIDGE_SCHEMA),
                "cartridge.source_schema",
                limit=300,
            ),
        }
    else:
        raise PlaywrightComputerError(
            f"cartridge.schema must be {CARTRIDGE_SCHEMA} or tier-bench/task-computer-scenario@1"
        )
    unknown_effects = set(result["effects"]) - EFFECTS
    if unknown_effects:
        raise PlaywrightComputerError(
            f"cartridge.effects has unknown values: {sorted(unknown_effects)}"
        )
    expected_cartridge_sha256 = hash_json(result)
    observed_cartridge_sha256 = row.get("cartridge_sha256")
    if (
        observed_cartridge_sha256 is not None
        and observed_cartridge_sha256 != expected_cartridge_sha256
    ):
        raise PlaywrightComputerError(
            "cartridge.cartridge_sha256 does not match canonical content"
        )
    result["cartridge_sha256"] = expected_cartridge_sha256
    return result


def validate_state(raw: Any) -> dict[str, Any]:
    row = _object(raw, "state")
    if row.get("schema", STATE_SCHEMA) != STATE_SCHEMA:
        raise PlaywrightComputerError(f"state.schema must be {STATE_SCHEMA}")
    artifacts = deepcopy(_array(row.get("artifacts", []), "state.artifacts"))
    previous_state_id = row.get("previous_state_id")
    if previous_state_id is not None:
        previous_state_id = _text(
            previous_state_id, "state.previous_state_id", limit=64
        )
        if len(previous_state_id) != 64:
            raise PlaywrightComputerError("state.previous_state_id must be SHA-256")
    value = {
        "schema": STATE_SCHEMA,
        "task_id": safe_id(row.get("task_id"), "state.task_id"),
        "revision": _integer(row.get("revision", 0), "state.revision"),
        "observed_at": _text(row.get("observed_at"), "state.observed_at", limit=100),
        "previous_state_id": previous_state_id,
        "surfaces": deepcopy(_object(row.get("surfaces", {}), "state.surfaces")),
        "artifacts": artifacts,
        "data": deepcopy(_object(row.get("data", {}), "state.data")),
    }
    expected = hash_json(value)
    observed = row.get("state_id")
    if observed != expected:
        raise PlaywrightComputerError("state.state_id does not match canonical content")
    return {**value, "state_id": expected}


def seal_state(raw: dict[str, Any]) -> dict[str, Any]:
    value = dict(raw)
    value.setdefault("schema", STATE_SCHEMA)
    value.pop("state_id", None)
    previous_state_id = value.get("previous_state_id")
    if previous_state_id is not None:
        previous_state_id = _text(
            previous_state_id, "state.previous_state_id", limit=64
        )
        if len(previous_state_id) != 64:
            raise PlaywrightComputerError("state.previous_state_id must be SHA-256")
    validated_base = {
        "schema": STATE_SCHEMA,
        "task_id": safe_id(value.get("task_id"), "state.task_id"),
        "revision": _integer(value.get("revision", 0), "state.revision"),
        "observed_at": _text(value.get("observed_at"), "state.observed_at", limit=100),
        "previous_state_id": previous_state_id,
        "surfaces": deepcopy(_object(value.get("surfaces", {}), "state.surfaces")),
        "artifacts": deepcopy(_array(value.get("artifacts", []), "state.artifacts")),
        "data": deepcopy(_object(value.get("data", {}), "state.data")),
    }
    return {**validated_base, "state_id": hash_json(validated_base)}


def validate_action(raw: Any) -> dict[str, Any]:
    row = _object(raw, "action")
    if row.get("schema") != ACTION_SCHEMA:
        raise PlaywrightComputerError(f"action.schema must be {ACTION_SCHEMA}")
    expected_state_id = _text(
        row.get("expected_state_id"), "action.expected_state_id", limit=64
    )
    if len(expected_state_id) != 64:
        raise PlaywrightComputerError("action.expected_state_id must be SHA-256")
    action_id = safe_id(row.get("action_id"), "action.action_id")
    data_classification = _string_list(
        row.get("data_classification", []),
        "action.data_classification",
    )
    value = {
        "schema": ACTION_SCHEMA,
        "action_id": action_id,
        "task_id": safe_id(row.get("task_id"), "action.task_id"),
        "expected_state_id": expected_state_id,
        "surface": _choice(row.get("surface"), "action.surface", SURFACES),
        "operation": _text(row.get("operation"), "action.operation", limit=120),
        "effect": _choice(row.get("effect"), "action.effect", EFFECTS),
        "arguments": deepcopy(_object(row.get("arguments", {}), "action.arguments")),
        "intent": _text(
            row.get("intent", row.get("operation")), "action.intent", limit=4000
        ),
        "idempotency_key": _text(
            row.get("idempotency_key", action_id),
            "action.idempotency_key",
            limit=300,
        ),
        "principal": deepcopy(row.get("principal")),
        "on_behalf_of": deepcopy(row.get("on_behalf_of")),
        "resource": deepcopy(row.get("resource")),
        "preconditions": deepcopy(
            _array(row.get("preconditions", []), "action.preconditions")
        ),
        "expected_postconditions": deepcopy(
            _array(
                row.get("expected_postconditions", []),
                "action.expected_postconditions",
            )
        ),
        "data_classification": data_classification,
        "compensation": deepcopy(row.get("compensation")),
        "approval": deepcopy(row.get("approval")),
        "trace_context": deepcopy(row.get("trace_context")),
    }
    expected_hash = hash_json(value)
    observed = row.get("action_sha256")
    if observed is not None and observed != expected_hash:
        raise PlaywrightComputerError(
            "action.action_sha256 does not match canonical content"
        )
    return {**value, "action_sha256": expected_hash}


def seal_action(raw: dict[str, Any]) -> dict[str, Any]:
    value = dict(raw)
    value.setdefault("schema", ACTION_SCHEMA)
    value.pop("action_sha256", None)
    return validate_action(value)


def validate_approval(raw: Any) -> dict[str, Any]:
    row = _object(raw, "approval")
    if row.get("schema") != APPROVAL_SCHEMA:
        raise PlaywrightComputerError(f"approval.schema must be {APPROVAL_SCHEMA}")
    decision = _choice(
        row.get("decision"),
        "approval.decision",
        {"approve", "edit", "reject"},
    )
    state_id = _text(row.get("state_id"), "approval.state_id", limit=64)
    action_sha256 = _text(
        row.get("action_sha256"), "approval.action_sha256", limit=64
    )
    if len(state_id) != 64 or len(action_sha256) != 64:
        raise PlaywrightComputerError(
            "approval state_id and action_sha256 must be SHA-256"
        )
    value = {
        "schema": APPROVAL_SCHEMA,
        "approval_id": safe_id(row.get("approval_id"), "approval.approval_id"),
        "task_id": safe_id(row.get("task_id"), "approval.task_id"),
        "state_id": state_id,
        "action_sha256": action_sha256,
        "effect": _choice(row.get("effect"), "approval.effect", EFFECTS),
        "decision": decision,
        "authority": deepcopy(_object(row.get("authority"), "approval.authority")),
        "issued_at": _text(row.get("issued_at"), "approval.issued_at", limit=100),
        "expires_at": row.get("expires_at"),
        "scope": deepcopy(_object(row.get("scope", {}), "approval.scope")),
        "constraints": deepcopy(
            _array(row.get("constraints", []), "approval.constraints")
        ),
        "reason": _text(
            row.get("reason", ""),
            "approval.reason",
            limit=4000,
            allow_empty=True,
        ),
    }
    expected = hash_json(value)
    observed = row.get("approval_sha256")
    if observed != expected:
        raise PlaywrightComputerError(
            "approval.approval_sha256 does not match canonical content"
        )
    return {**value, "approval_sha256": expected}


def seal_approval(raw: dict[str, Any]) -> dict[str, Any]:
    value = dict(raw)
    value.setdefault("schema", APPROVAL_SCHEMA)
    value.pop("approval_sha256", None)
    base = {
        "schema": APPROVAL_SCHEMA,
        "approval_id": safe_id(value.get("approval_id"), "approval.approval_id"),
        "task_id": safe_id(value.get("task_id"), "approval.task_id"),
        "state_id": _text(value.get("state_id"), "approval.state_id", limit=64),
        "action_sha256": _text(
            value.get("action_sha256"), "approval.action_sha256", limit=64
        ),
        "effect": _choice(value.get("effect"), "approval.effect", EFFECTS),
        "decision": _choice(
            value.get("decision"),
            "approval.decision",
            {"approve", "edit", "reject"},
        ),
        "authority": deepcopy(
            _object(value.get("authority"), "approval.authority")
        ),
        "issued_at": _text(value.get("issued_at"), "approval.issued_at", limit=100),
        "expires_at": value.get("expires_at"),
        "scope": deepcopy(_object(value.get("scope", {}), "approval.scope")),
        "constraints": deepcopy(
            _array(value.get("constraints", []), "approval.constraints")
        ),
        "reason": _text(
            value.get("reason", ""),
            "approval.reason",
            limit=4000,
            allow_empty=True,
        ),
    }
    if len(base["state_id"]) != 64 or len(base["action_sha256"]) != 64:
        raise PlaywrightComputerError(
            "approval state_id and action_sha256 must be SHA-256"
        )
    return {**base, "approval_sha256": hash_json(base)}


def validate_action_receipt(raw: Any) -> dict[str, Any]:
    row = _object(raw, "action_receipt")
    if row.get("schema") != ACTION_RECEIPT_SCHEMA:
        raise PlaywrightComputerError(
            f"action_receipt.schema must be {ACTION_RECEIPT_SCHEMA}"
        )
    value = without_hash(row, "receipt_sha256")
    if row.get("receipt_sha256") != hash_json(value):
        raise PlaywrightComputerError(
            "action_receipt.receipt_sha256 does not match canonical content"
        )
    return deepcopy(row)


def validate_driver_request(raw: Any) -> dict[str, Any]:
    row = _object(raw, "driver_request")
    if row.get("schema") != DRIVER_REQUEST_SCHEMA:
        raise PlaywrightComputerError(
            f"driver_request.schema must be {DRIVER_REQUEST_SCHEMA}"
        )
    op = _choice(row.get("op"), "driver_request.op", DRIVER_OPS)
    value = {
        "schema": DRIVER_REQUEST_SCHEMA,
        "request_id": safe_id(row.get("request_id"), "driver_request.request_id"),
        "op": op,
        "task": deepcopy(row.get("task")),
        "state_id": row.get("state_id"),
        "action": deepcopy(row.get("action")),
        "approval": deepcopy(row.get("approval")),
        "lease_id": row.get("lease_id"),
        "trace_context": deepcopy(row.get("trace_context")),
    }
    if value["state_id"] is not None:
        value["state_id"] = _text(
            value["state_id"], "driver_request.state_id", limit=64
        )
        if len(value["state_id"]) != 64:
            raise PlaywrightComputerError("driver_request.state_id must be SHA-256")
    if op == "act":
        value["action"] = validate_action(row.get("action"))
    expected_hash = hash_json(value)
    observed = row.get("request_sha256")
    if observed is not None and observed != expected_hash:
        raise PlaywrightComputerError(
            "driver_request.request_sha256 does not match canonical content"
        )
    return {**value, "request_sha256": expected_hash}


def validate_driver_response(raw: Any, request: dict[str, Any]) -> dict[str, Any]:
    row = _object(raw, "driver_response")
    if row.get("schema") != DRIVER_RESPONSE_SCHEMA:
        raise PlaywrightComputerError(
            f"driver_response.schema must be {DRIVER_RESPONSE_SCHEMA}"
        )
    if row.get("request_id") != request["request_id"]:
        raise PlaywrightComputerError("driver response belongs to another request")
    if row.get("request_sha256") != request["request_sha256"]:
        raise PlaywrightComputerError("driver response binds another request identity")
    ok = _boolean(row.get("ok"), "driver_response.ok")
    value = without_hash(row, "response_sha256")
    if row.get("response_sha256") != hash_json(value):
        raise PlaywrightComputerError(
            "driver_response.response_sha256 does not match canonical content"
        )
    if ok and row.get("error") is not None:
        raise PlaywrightComputerError("successful driver response cannot contain error")
    return deepcopy(row)


def make_driver_request(
    request_id: str,
    op: str,
    **payload: Any,
) -> dict[str, Any]:
    value = {
        "schema": DRIVER_REQUEST_SCHEMA,
        "request_id": safe_id(request_id, "request_id"),
        "op": _choice(op, "op", DRIVER_OPS),
        "task": payload.get("task"),
        "state_id": payload.get("state_id"),
        "action": payload.get("action"),
        "approval": payload.get("approval"),
        "lease_id": payload.get("lease_id"),
        "trace_context": payload.get("trace_context"),
    }
    return validate_driver_request(value)


def seal_record(value: dict[str, Any], field: str) -> dict[str, Any]:
    result = dict(value)
    result.pop(field, None)
    result[field] = hash_json(result)
    return result


def verify_record(value: Any, field: str) -> bool:
    return isinstance(value, dict) and value.get(field) == hash_json(
        without_hash(value, field)
    )


def validate_skill_package(raw: Any) -> dict[str, Any]:
    row = _object(raw, "skill")
    if row.get("schema") != SKILL_SCHEMA:
        raise PlaywrightComputerError(f"skill.schema must be {SKILL_SCHEMA}")
    source = _object(row.get("source"), "skill.source")
    source_bundle = _text(
        source.get("bundle_sha256"), "skill.source.bundle_sha256", limit=64
    )
    source_trajectory = _text(
        source.get("trajectory_sha256"),
        "skill.source.trajectory_sha256",
        limit=64,
    )
    if len(source_bundle) != 64 or len(source_trajectory) != 64:
        raise PlaywrightComputerError(
            "skill source bundle and trajectory identities must be SHA-256"
        )
    artifacts = deepcopy(_array(row.get("artifacts"), "skill.artifacts", nonempty=True))
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            raise PlaywrightComputerError(f"skill.artifacts[{index}] must be an object")
        digest = artifact.get("digest", {}).get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise PlaywrightComputerError(
                f"skill.artifacts[{index}].digest.sha256 must be SHA-256"
            )
    value = {
        "schema": SKILL_SCHEMA,
        "id": safe_id(row.get("id"), "skill.id"),
        "version": _text(row.get("version"), "skill.version", limit=120),
        "name": _text(row.get("name"), "skill.name", limit=300),
        "description": _text(
            row.get("description", ""),
            "skill.description",
            limit=4000,
            allow_empty=True,
        ),
        "source": {
            "bundle_sha256": source_bundle,
            "trajectory_sha256": source_trajectory,
            "run_id": source.get("run_id"),
            "acceptance_sha256": source.get("acceptance_sha256"),
        },
        "entrypoint": _text(row.get("entrypoint"), "skill.entrypoint", limit=2000),
        "runtime": deepcopy(_object(row.get("runtime"), "skill.runtime")),
        "inputs": deepcopy(_object(row.get("inputs", {}), "skill.inputs")),
        "outputs": deepcopy(_object(row.get("outputs", {}), "skill.outputs")),
        "effects": _string_list(
            row.get("effects", []), "skill.effects", allowed=EFFECTS
        ),
        "supported_cartridges": _string_list(
            row.get("supported_cartridges", []),
            "skill.supported_cartridges",
            nonempty=True,
        ),
        "compatibility": deepcopy(
            _object(row.get("compatibility", {}), "skill.compatibility")
        ),
        "tests": deepcopy(_array(row.get("tests", []), "skill.tests")),
        "review": deepcopy(_object(row.get("review", {}), "skill.review")),
        "rollback": deepcopy(_object(row.get("rollback", {}), "skill.rollback")),
        "artifacts": artifacts,
        "signatures": deepcopy(_array(row.get("signatures", []), "skill.signatures")),
        "production_authorized": _boolean(
            row.get("production_authorized", False),
            "skill.production_authorized",
        ),
    }
    expected = hash_json(value)
    observed = row.get("skill_sha256")
    if observed is not None and observed != expected:
        raise PlaywrightComputerError(
            "skill.skill_sha256 does not match canonical content"
        )
    return {**value, "skill_sha256": expected}


def seal_skill_package(raw: dict[str, Any]) -> dict[str, Any]:
    value = dict(raw)
    value.setdefault("schema", SKILL_SCHEMA)
    value.pop("skill_sha256", None)
    return validate_skill_package(value)


def profile_requirement_map() -> dict[str, dict[str, Any]]:
    return {
        profile: {
            "title": PROFILE_TITLES[profile],
            "requirements": list(PROFILE_REQUIREMENTS[profile]),
        }
        for profile in PROFILE_ORDER
    }
