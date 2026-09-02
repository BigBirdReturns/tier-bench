"""Public interaction-floor protocol, conformance, starter, and registry tools.

Estate Lab's internal manifest is deliberately rich because it models the AXM
project estate.  The public floor is narrower.  An external project needs only
an adapter declaration, the request/response envelopes, the canonical test
vectors, and an independently verifiable conformance submission.  No adopter
has to import AXM game law, repository topology, routing policy, or custody
machinery.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .canonical import canonical_json_bytes, load_json, sha256_hex, stable_id, write_json
from .errors import FloorProtocolError

FLOOR_FORMAT = "axm-interaction-floor/1"
ADAPTER_FORMAT = "axm-interaction-adapter/1"
REQUEST_FORMAT = "axm-interaction-request/1"
RESPONSE_FORMAT = "axm-interaction-response/1"
EVENT_FORMAT = "axm-semantic-event/1"
SUBMISSION_FORMAT = "axm-interaction-conformance/1"
REGISTRY_FORMAT = "axm-interaction-registry/1"
SNAPSHOT_FORMAT = "axm-interaction-snapshot/1"

KINDS = frozenset({"describe", "health", "execute", "snapshot", "reset"})
PHASES = frozenset({"source", "target"})
SEMANTIC_OPERATIONS = frozenset({"set", "increment", "append", "remove", "toggle"})
HEALTH_STATES = frozenset({"ready", "degraded", "unavailable"})
PRIVACY_CLASSES = frozenset({"public", "internal", "confidential", "restricted"})
PROFILE_ORDER = (
    "core@1",
    "replay@1",
    "lifecycle@1",
    "observability@1",
    "supply@1",
    "privacy@1",
    "accessibility@1",
    "agent-delegation@1",
)
TIER_ORDER = ("declared", "bronze", "silver", "gold", "platinum")

ADAPTER_ID_RE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)+$")
SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:[-+][0-9A-Za-z.-]+)?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TRACEPARENT_RE = re.compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")


@dataclass(frozen=True)
class FloorSpec:
    floor_id: str
    floor_version: str
    title: str
    raw: dict[str, Any]
    source_path: Path


@dataclass(frozen=True)
class FloorAdapter:
    descriptor_id: str
    adapter_id: str
    adapter_version: str
    name: str
    profiles: tuple[str, ...]
    command: tuple[str, ...]
    timeout_seconds: int
    deterministic: bool
    replayable: bool
    raw: dict[str, Any]
    source_path: Path


@dataclass(frozen=True)
class FloorSubmission:
    submission_id: str
    floor_id: str
    adapter_id: str
    adapter_version: str
    descriptor_id: str
    result: str
    tier: str
    verified_profiles: tuple[str, ...]
    raw: dict[str, Any]
    source_path: Path | None = None


@dataclass(frozen=True)
class VectorResult:
    vector_id: str
    profile: str
    status: str
    reason: str | None
    request_id: str | None
    response_id: str | None
    response_sha256: str | None
    repeats: int


def _require_object(raw: Mapping[str, Any], key: str, *, where: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise FloorProtocolError(f"{where}.{key} must be an object")
    return dict(value)


def _optional_object(raw: Mapping[str, Any], key: str, *, where: str) -> dict[str, Any] | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise FloorProtocolError(f"{where}.{key} must be null or an object")
    return dict(value)


def _require_string(raw: Mapping[str, Any], key: str, *, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise FloorProtocolError(f"{where}.{key} must be a non-empty string")
    return value.strip()


def _optional_string(raw: Mapping[str, Any], key: str, *, where: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise FloorProtocolError(f"{where}.{key} must be null or a non-empty string")
    return value.strip()


def _require_bool(raw: Mapping[str, Any], key: str, *, where: str) -> bool:
    value = raw.get(key)
    if not isinstance(value, bool):
        raise FloorProtocolError(f"{where}.{key} must be boolean")
    return value


def _require_int(
    raw: Mapping[str, Any],
    key: str,
    *,
    where: str,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise FloorProtocolError(f"{where}.{key} must be an integer")
    if minimum is not None and value < minimum:
        raise FloorProtocolError(f"{where}.{key} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise FloorProtocolError(f"{where}.{key} must be <= {maximum}")
    return value


def _require_string_list(
    raw: Mapping[str, Any],
    key: str,
    *,
    where: str,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    value = raw.get(key)
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = "an array" if allow_empty else "a non-empty array"
        raise FloorProtocolError(f"{where}.{key} must be {qualifier}")
    normalized: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise FloorProtocolError(f"{where}.{key}[{index}] must be a non-empty string")
        normalized.append(item.strip())
    if len(normalized) != len(set(normalized)):
        raise FloorProtocolError(f"{where}.{key} contains duplicates")
    return tuple(normalized)


def _validate_semver(value: str, *, where: str) -> None:
    if SEMVER_RE.fullmatch(value) is None:
        raise FloorProtocolError(f"{where} must be semantic version text")


def _validate_sha256(value: str, *, where: str) -> None:
    if SHA256_RE.fullmatch(value) is None:
        raise FloorProtocolError(f"{where} must be a lowercase SHA-256 hex digest")


def _major(version: str) -> int:
    _validate_semver(version, where="version")
    return int(version.split(".", 1)[0])


def floor_identity_projection(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {key: raw.get(key) for key in raw if key != "floor_id"}


def derived_floor_id(raw: Mapping[str, Any]) -> str:
    return stable_id("floor1", floor_identity_projection(raw), length=32)


def adapter_identity_projection(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {key: raw.get(key) for key in raw if key != "descriptor_id"}


def derived_adapter_descriptor_id(raw: Mapping[str, Any]) -> str:
    return stable_id("flooradapter1", adapter_identity_projection(raw), length=32)


def submission_identity_projection(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: raw.get(key)
        for key in raw
        if key not in {"submission_id", "environment", "generated_at"}
    }


def derived_submission_id(raw: Mapping[str, Any]) -> str:
    return stable_id("floorconf1", submission_identity_projection(raw), length=32)


def registry_identity_projection(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {key: raw.get(key) for key in raw if key not in {"registry_id", "generated_at"}}


def derived_registry_id(raw: Mapping[str, Any]) -> str:
    return stable_id("floorregistry1", registry_identity_projection(raw), length=32)


def event_semantic_projection(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "semantic_id": event.get("semantic_id"),
        "subject": event.get("subject"),
        "operation": event.get("operation"),
        "state_path": event.get("state_path"),
        "value": event.get("value"),
        "authority": event.get("authority"),
    }


def event_identity_projection(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "format": event.get("format"),
        **event_semantic_projection(event),
        "causality": event.get("causality", {}),
    }


def derived_event_id(event: Mapping[str, Any]) -> str:
    return stable_id("floorevent1", event_identity_projection(event), length=32)


def request_identity_projection(request: Mapping[str, Any]) -> dict[str, Any]:
    return {key: request.get(key) for key in request if key != "request_id"}


def derived_request_id(request: Mapping[str, Any]) -> str:
    return stable_id("floorreq1", request_identity_projection(request), length=32)


def response_identity_projection(response: Mapping[str, Any]) -> dict[str, Any]:
    return {key: response.get(key) for key in response if key != "response_id"}


def derived_response_id(response: Mapping[str, Any]) -> str:
    return stable_id("floorres1", response_identity_projection(response), length=32)


def load_floor_spec(path: Path) -> FloorSpec:
    try:
        raw = load_json(path)
    except (OSError, ValueError) as exc:
        raise FloorProtocolError(f"cannot load floor specification {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise FloorProtocolError("floor specification root must be an object")
    if raw.get("format") != FLOOR_FORMAT:
        raise FloorProtocolError(f"floor format must be {FLOOR_FORMAT!r}")
    floor_version = _require_string(raw, "floor_version", where="floor")
    _validate_semver(floor_version, where="floor.floor_version")
    floor_id = _require_string(raw, "floor_id", where="floor")
    expected_id = derived_floor_id(raw)
    if floor_id != expected_id:
        raise FloorProtocolError(
            f"floor_id mismatch: declared {floor_id!r}, expected {expected_id!r}"
        )
    title = _require_string(raw, "title", where="floor")

    authority = _require_object(raw, "authority_boundary", where="floor")
    _require_string_list(authority, "owns", where="floor.authority_boundary")
    _require_string_list(authority, "refuses", where="floor.authority_boundary")

    canonical = _require_object(raw, "canonicalization", where="floor")
    if _require_string(canonical, "algorithm", where="floor.canonicalization") != "utf8-sorted-json-sha256-v1":
        raise FloorProtocolError("unsupported floor canonicalization algorithm")

    profiles = _require_object(raw, "profiles", where="floor")
    if not profiles:
        raise FloorProtocolError("floor.profiles must not be empty")
    for profile_id, profile in profiles.items():
        if profile_id not in PROFILE_ORDER:
            raise FloorProtocolError(f"unknown floor profile: {profile_id}")
        if not isinstance(profile, dict):
            raise FloorProtocolError(f"floor.profiles.{profile_id} must be an object")
        _require_string(profile, "purpose", where=f"floor.profiles.{profile_id}")
        required_profiles = _require_string_list(
            profile,
            "requires",
            where=f"floor.profiles.{profile_id}",
            allow_empty=True,
        )
        unknown_required = set(required_profiles) - set(profiles)
        if unknown_required:
            raise FloorProtocolError(
                f"profile {profile_id} requires unknown profiles: {sorted(unknown_required)}"
            )

    visiting_profiles: set[str] = set()
    visited_profiles: set[str] = set()

    def visit_profile(profile_id: str) -> None:
        if profile_id in visited_profiles:
            return
        if profile_id in visiting_profiles:
            raise FloorProtocolError(f"profile dependency cycle contains {profile_id}")
        visiting_profiles.add(profile_id)
        for dependency in profiles[profile_id].get("requires", []):
            visit_profile(dependency)
        visiting_profiles.remove(profile_id)
        visited_profiles.add(profile_id)

    for profile_id in profiles:
        visit_profile(profile_id)

    tiers = _require_object(raw, "quality_tiers", where="floor")
    if set(tiers) != set(TIER_ORDER):
        raise FloorProtocolError(
            f"floor.quality_tiers must contain exactly {list(TIER_ORDER)}"
        )
    for tier, definition in tiers.items():
        if not isinstance(definition, dict):
            raise FloorProtocolError(f"floor.quality_tiers.{tier} must be an object")
        required = _require_string_list(
            definition,
            "profiles",
            where=f"floor.quality_tiers.{tier}",
            allow_empty=True,
        )
        unknown = set(required) - set(profiles)
        if unknown:
            raise FloorProtocolError(f"tier {tier} references unknown profiles: {sorted(unknown)}")

    bindings = raw.get("bindings")
    if not isinstance(bindings, list) or not bindings:
        raise FloorProtocolError("floor.bindings must be a non-empty array")
    seen_bindings: set[str] = set()
    for index, binding in enumerate(bindings):
        where = f"floor.bindings[{index}]"
        if not isinstance(binding, dict):
            raise FloorProtocolError(f"{where} must be an object")
        binding_id = _require_string(binding, "id", where=where)
        if binding_id in seen_bindings:
            raise FloorProtocolError(f"duplicate binding id: {binding_id}")
        seen_bindings.add(binding_id)
        _require_string(binding, "status", where=where)
        _require_string(binding, "mechanism", where=where)

    vectors = raw.get("vectors")
    if not isinstance(vectors, list) or not vectors:
        raise FloorProtocolError("floor.vectors must be a non-empty array")
    seen_vectors: set[str] = set()
    for index, vector in enumerate(vectors):
        where = f"floor.vectors[{index}]"
        if not isinstance(vector, dict):
            raise FloorProtocolError(f"{where} must be an object")
        vector_id = _require_string(vector, "id", where=where)
        if vector_id in seen_vectors:
            raise FloorProtocolError(f"duplicate vector id: {vector_id}")
        seen_vectors.add(vector_id)
        profile = _require_string(vector, "profile", where=where)
        if profile not in profiles:
            raise FloorProtocolError(f"{where}.profile references unknown profile {profile!r}")
        request = _require_object(vector, "request", where=where)
        kind = _require_string(request, "kind", where=f"{where}.request")
        if kind not in KINDS and kind != "unsupported-kind":
            raise FloorProtocolError(f"{where}.request.kind is unsupported")
        repeats = vector.get("repeats", 1)
        if not isinstance(repeats, int) or repeats < 1 or repeats > 4:
            raise FloorProtocolError(f"{where}.repeats must be 1 through 4")
        _require_object(vector, "expect", where=where)

    return FloorSpec(
        floor_id=floor_id,
        floor_version=floor_version,
        title=title,
        raw=raw,
        source_path=path.resolve(),
    )


def _resolve_artifact_path(adapter_path: Path, relative: str) -> Path:
    candidate = (adapter_path.parent / relative).resolve()
    try:
        candidate.relative_to(adapter_path.parent.resolve())
    except ValueError as exc:
        raise FloorProtocolError(f"supply artifact escapes adapter directory: {relative}") from exc
    return candidate


def load_floor_adapter(path: Path, spec: FloorSpec | None = None) -> FloorAdapter:
    try:
        raw = load_json(path)
    except (OSError, ValueError) as exc:
        raise FloorProtocolError(f"cannot load adapter declaration {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise FloorProtocolError("adapter declaration root must be an object")
    if raw.get("format") != ADAPTER_FORMAT:
        raise FloorProtocolError(f"adapter format must be {ADAPTER_FORMAT!r}")
    adapter_id = _require_string(raw, "adapter_id", where="adapter")
    if ADAPTER_ID_RE.fullmatch(adapter_id) is None:
        raise FloorProtocolError("adapter.adapter_id must be a reverse-domain-like lowercase identifier")
    adapter_version = _require_string(raw, "adapter_version", where="adapter")
    _validate_semver(adapter_version, where="adapter.adapter_version")
    descriptor_id = _require_string(raw, "descriptor_id", where="adapter")
    expected_id = derived_adapter_descriptor_id(raw)
    if descriptor_id != expected_id:
        raise FloorProtocolError(
            f"descriptor_id mismatch: declared {descriptor_id!r}, expected {expected_id!r}"
        )
    name = _require_string(raw, "name", where="adapter")
    floor = _require_object(raw, "floor", where="adapter")
    versions = _require_string_list(floor, "versions", where="adapter.floor")
    for version in versions:
        _validate_semver(version, where="adapter.floor.versions[]")
    profiles = _require_string_list(floor, "profiles", where="adapter.floor")
    if spec is not None:
        if not any(_major(version) == _major(spec.floor_version) for version in versions):
            raise FloorProtocolError(
                f"adapter does not declare a compatible floor major for {spec.floor_version}"
            )
        unknown_profiles = set(profiles) - set(spec.raw["profiles"])
        if unknown_profiles:
            raise FloorProtocolError(
                f"adapter declares unknown profiles: {sorted(unknown_profiles)}"
            )

    bindings = _require_string_list(raw, "bindings", where="adapter")
    if "command-json@1" not in bindings:
        raise FloorProtocolError("the reference conformance runner requires command-json@1")
    command_value = raw.get("command")
    if not isinstance(command_value, list) or not command_value:
        raise FloorProtocolError("adapter.command must be a non-empty argv array")
    command: list[str] = []
    for index, token in enumerate(command_value):
        if not isinstance(token, str) or not token:
            raise FloorProtocolError(f"adapter.command[{index}] must be a non-empty string")
        command.append(token)
    if not any("{request}" in token for token in command):
        raise FloorProtocolError("adapter.command must include {request}")

    timeout_seconds = _require_int(raw, "timeout_seconds", where="adapter", minimum=1, maximum=300)
    deterministic = _require_bool(raw, "deterministic", where="adapter")
    replayable = _require_bool(raw, "replayable", where="adapter")
    local_only = _require_bool(raw, "local_only", where="adapter")
    network_required = _require_bool(raw, "network_required", where="adapter")
    if local_only and network_required:
        raise FloorProtocolError("adapter cannot be local_only and network_required")

    authority = _require_object(raw, "authority", where="adapter")
    consumes = set(_require_string_list(authority, "consumes", where="adapter.authority"))
    required_authority = {"actor", "role", "mandate", "ownership_epoch"}
    if not required_authority.issubset(consumes):
        raise FloorProtocolError(
            f"adapter.authority.consumes must include {sorted(required_authority)}"
        )
    if _require_bool(authority, "may_grant", where="adapter.authority"):
        raise FloorProtocolError("a floor adapter may not grant authority")
    if _require_bool(authority, "may_rewrite_semantics", where="adapter.authority"):
        raise FloorProtocolError("a floor adapter may not rewrite semantics")

    capabilities = _require_object(raw, "capabilities", where="adapter")
    directions = set(_require_string_list(capabilities, "directions", where="adapter.capabilities"))
    if not directions.issubset(PHASES) or not directions:
        raise FloorProtocolError("adapter.capabilities.directions must contain source and/or target")
    operations = set(_require_string_list(capabilities, "operations", where="adapter.capabilities"))
    if not operations.issubset(SEMANTIC_OPERATIONS):
        raise FloorProtocolError("adapter.capabilities.operations contains unsupported values")

    if "replay@1" in profiles and (not deterministic or not replayable):
        raise FloorProtocolError("replay@1 requires deterministic=true and replayable=true")

    lifecycle = _require_object(raw, "lifecycle", where="adapter")
    states = set(_require_string_list(lifecycle, "health_states", where="adapter.lifecycle"))
    if not states.issubset(HEALTH_STATES) or "ready" not in states:
        raise FloorProtocolError("adapter.lifecycle.health_states must include ready")
    _require_bool(lifecycle, "supports_snapshot", where="adapter.lifecycle")
    _require_bool(lifecycle, "supports_reset", where="adapter.lifecycle")

    observability = _require_object(raw, "observability", where="adapter")
    _require_string(observability, "trace_context", where="adapter.observability")
    _require_bool(observability, "structured_logs", where="adapter.observability")

    privacy = _require_object(raw, "privacy", where="adapter")
    classes = set(_require_string_list(privacy, "classes", where="adapter.privacy"))
    if not classes.issubset(PRIVACY_CLASSES):
        raise FloorProtocolError("adapter.privacy.classes contains an unknown class")
    _require_string(privacy, "retention", where="adapter.privacy")

    accessibility = _require_object(raw, "accessibility", where="adapter")
    _require_string_list(accessibility, "input_modalities", where="adapter.accessibility")
    _require_string_list(accessibility, "output_modalities", where="adapter.accessibility")
    _require_string_list(accessibility, "fallbacks", where="adapter.accessibility")

    delegation = _require_object(raw, "delegation", where="adapter")
    _require_bool(delegation, "accepts_human", where="adapter.delegation")
    _require_bool(delegation, "accepts_agent", where="adapter.delegation")
    if _require_bool(delegation, "may_escalate_authority", where="adapter.delegation"):
        raise FloorProtocolError("a floor adapter may not escalate authority")

    supply = _require_object(raw, "supply", where="adapter")
    _require_string(supply, "license_expression", where="adapter.supply")
    artifacts = supply.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise FloorProtocolError("adapter.supply.artifacts must be a non-empty array")
    for index, artifact in enumerate(artifacts):
        where = f"adapter.supply.artifacts[{index}]"
        if not isinstance(artifact, dict):
            raise FloorProtocolError(f"{where} must be an object")
        relative = _require_string(artifact, "path", where=where)
        digest = _require_string(artifact, "sha256", where=where)
        _validate_sha256(digest, where=f"{where}.sha256")
        artifact_path = _resolve_artifact_path(path.resolve(), relative)
        if not artifact_path.is_file():
            raise FloorProtocolError(f"{where} artifact is missing: {relative}")
        actual = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if actual != digest:
            raise FloorProtocolError(
                f"{where} digest mismatch: declared {digest}, actual {actual}"
            )

    return FloorAdapter(
        descriptor_id=descriptor_id,
        adapter_id=adapter_id,
        adapter_version=adapter_version,
        name=name,
        profiles=profiles,
        command=tuple(command),
        timeout_seconds=timeout_seconds,
        deterministic=deterministic,
        replayable=replayable,
        raw=raw,
        source_path=path.resolve(),
    )


def _base_context(*, trace: bool = False, delegation: bool = False) -> dict[str, Any]:
    context: dict[str, Any] = {
        "privacy_class": "internal",
        "deadline_unix_ms": 4102444800000,
        "correlation_id": "floor-conformance-correlation",
    }
    if trace:
        context["traceparent"] = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    if delegation:
        context["delegation"] = {
            "delegation_id": "delegation-floor-test-001",
            "principal": "human:conformance-operator",
            "delegate": "agent:reference-test",
            "scope": "fixture.control",
            "may_escalate": False,
        }
    return context


def materialize_request(
    spec: FloorSpec,
    adapter: FloorAdapter,
    vector: Mapping[str, Any],
) -> dict[str, Any]:
    request_template = _require_object(vector, "request", where=f"vector.{vector.get('id', '?')}")
    request = copy.deepcopy(request_template)
    request.setdefault("format", REQUEST_FORMAT)
    request.setdefault("floor_version", spec.floor_version)
    request["target_adapter_id"] = (
        adapter.adapter_id
        if request.get("target_adapter_id") in {None, "$ADAPTER_ID"}
        else request["target_adapter_id"]
    )
    request.setdefault("phase", "source")
    request.setdefault("sequence", 1)
    request.setdefault("context", _base_context())

    event = request.get("event")
    if isinstance(event, dict):
        event.setdefault("format", EVENT_FORMAT)
        event.setdefault(
            "causality",
            {
                "run_id": "floor-conformance-run",
                "correlation_id": "floor-conformance-correlation",
                "parent_event_ids": [],
            },
        )
        event["semantic_digest"] = sha256_hex(event_semantic_projection(event))
        event["event_id"] = derived_event_id(event)

    mutate = vector.get("mutate", {})
    if mutate is None:
        mutate = {}
    if not isinstance(mutate, dict):
        raise FloorProtocolError(f"vector {vector.get('id')} mutate must be an object")
    if "request_format" in mutate:
        request["format"] = mutate["request_format"]
    if "target_adapter_id" in mutate:
        request["target_adapter_id"] = mutate["target_adapter_id"]
    if "kind" in mutate:
        request["kind"] = mutate["kind"]
    if mutate.get("expire_deadline"):
        request.setdefault("context", {})["deadline_unix_ms"] = 0
    if mutate.get("semantic_digest") == "zero" and isinstance(event, dict):
        event["semantic_digest"] = "0" * 64
    authority_remove = mutate.get("authority_remove")
    if isinstance(authority_remove, str) and isinstance(event, dict):
        authority = event.get("authority")
        if isinstance(authority, dict):
            authority.pop(authority_remove, None)
    if mutate.get("request_id") == "zero":
        request["request_id"] = "floorreq1_" + "0" * 32
    else:
        request["request_id"] = derived_request_id(request)
    return request


def _response_from_failure(
    *,
    request: Mapping[str, Any],
    adapter_id: str,
    reason: str,
    kind: str | None = None,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "format": RESPONSE_FORMAT,
        "request_id": request.get("request_id", "unresolved"),
        "adapter_id": adapter_id,
        "kind": kind or str(request.get("kind") or "unknown"),
        "accepted": False,
        "reason": reason,
        "outcome": "refused",
        "semantic_digest": None,
        "observations": {},
    }
    response["response_id"] = derived_response_id(response)
    return response


def _resolve_command(adapter: FloorAdapter, request_path: Path, response_path: Path) -> list[str]:
    adapter_dir = adapter.source_path.parent
    argv: list[str] = []
    for token in adapter.command:
        value = (
            token.replace("{python}", sys.executable)
            .replace("{adapter_dir}", str(adapter_dir))
            .replace("{descriptor}", str(adapter.source_path))
            .replace("{request}", str(request_path))
            .replace("{response}", str(response_path))
        )
        if not os.path.isabs(value) and value.endswith(".py"):
            candidate = (adapter_dir / value).resolve()
            if candidate.is_file():
                value = str(candidate)
        argv.append(value)
    return argv


def invoke_floor_adapter(adapter: FloorAdapter, request: Mapping[str, Any]) -> dict[str, Any]:
    """Invoke a command-json adapter with no shell and return its response object."""

    with tempfile.TemporaryDirectory(prefix="axm-floor-adapter-") as temp_dir:
        temp = Path(temp_dir)
        request_path = temp / "request.json"
        response_path = temp / "response.json"
        write_json(request_path, dict(request))
        argv = _resolve_command(adapter, request_path, response_path)
        if not argv:
            raise FloorProtocolError("adapter command resolved to an empty argv")
        executable = argv[0]
        if not os.path.isabs(executable) and shutil.which(executable) is None:
            raise FloorProtocolError(f"adapter executable is unavailable: {executable}")
        try:
            completed = subprocess.run(
                argv,
                cwd=adapter.source_path.parent,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=adapter.timeout_seconds,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise FloorProtocolError(
                f"adapter timed out after {adapter.timeout_seconds}s"
            ) from exc
        if completed.returncode != 0:
            raise FloorProtocolError(
                "adapter exited nonzero: "
                f"exit={completed.returncode} stdout={sha256_hex(completed.stdout.encode())} "
                f"stderr={sha256_hex(completed.stderr.encode())}"
            )
        try:
            if response_path.is_file():
                response = load_json(response_path)
            else:
                response = json.loads(completed.stdout)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise FloorProtocolError("adapter emitted malformed JSON") from exc
        if not isinstance(response, dict):
            raise FloorProtocolError("adapter response must be an object")
        return dict(response)


def _validate_response_identity(response: Mapping[str, Any]) -> None:
    response_id = response.get("response_id")
    if not isinstance(response_id, str):
        raise FloorProtocolError("response.response_id must be a string")
    expected = derived_response_id(response)
    if response_id != expected:
        raise FloorProtocolError(
            f"response_id mismatch: declared {response_id!r}, expected {expected!r}"
        )


def validate_floor_response(
    adapter: FloorAdapter,
    request: Mapping[str, Any],
    response: Mapping[str, Any],
    expectation: Mapping[str, Any],
) -> None:
    if response.get("format") != RESPONSE_FORMAT:
        raise FloorProtocolError("adapter response format mismatch")
    if response.get("request_id") != request.get("request_id"):
        raise FloorProtocolError("adapter response request identity mismatch")
    if response.get("adapter_id") != adapter.adapter_id:
        raise FloorProtocolError("adapter response adapter identity mismatch")
    if response.get("kind") != request.get("kind"):
        raise FloorProtocolError("adapter response kind mismatch")
    _validate_response_identity(response)

    expected_accepted = expectation.get("accepted")
    if not isinstance(expected_accepted, bool):
        raise FloorProtocolError("vector expectation.accepted must be boolean")
    if response.get("accepted") is not expected_accepted:
        raise FloorProtocolError(
            f"accepted mismatch: expected {expected_accepted}, got {response.get('accepted')}"
        )
    expected_reason = expectation.get("reason")
    if expected_reason is not None and response.get("reason") != expected_reason:
        raise FloorProtocolError(
            f"reason mismatch: expected {expected_reason!r}, got {response.get('reason')!r}"
        )
    expected_outcome = expectation.get("outcome")
    if expected_outcome is not None and response.get("outcome") != expected_outcome:
        raise FloorProtocolError(
            f"outcome mismatch: expected {expected_outcome!r}, got {response.get('outcome')!r}"
        )

    if request.get("kind") == "execute" and expected_accepted:
        event = request.get("event")
        if not isinstance(event, dict):
            raise FloorProtocolError("execute request omitted event")
        expected_digest = event.get("semantic_digest")
        if response.get("semantic_digest") != expected_digest:
            raise FloorProtocolError("adapter changed the semantic digest")

    expected_descriptor_id = expectation.get("descriptor_id")
    if expected_descriptor_id == "$DESCRIPTOR_ID":
        expected_descriptor_id = adapter.descriptor_id
    if expected_descriptor_id is not None and response.get("descriptor_id") != expected_descriptor_id:
        raise FloorProtocolError("describe response did not bind the declared descriptor")

    expected_health = expectation.get("health_state")
    if expected_health is not None:
        health = response.get("health")
        if not isinstance(health, dict) or health.get("state") != expected_health:
            raise FloorProtocolError("health response did not expose the expected state")

    expected_observations = expectation.get("observations", {})
    if not isinstance(expected_observations, dict):
        raise FloorProtocolError("vector expectation.observations must be an object")
    observations = response.get("observations")
    if not isinstance(observations, dict):
        observations = {}
    for key, value in expected_observations.items():
        if value == "$TRACEPARENT":
            value = request.get("context", {}).get("traceparent")
        elif value == "$DELEGATION_ID":
            value = request.get("context", {}).get("delegation", {}).get("delegation_id")
        if observations.get(key) != value:
            raise FloorProtocolError(
                f"observation mismatch for {key!r}: expected {value!r}, got {observations.get(key)!r}"
            )


def _static_profile_checks(
    spec: FloorSpec,
    adapter: FloorAdapter,
) -> list[VectorResult]:
    raw = adapter.raw
    profiles = set(adapter.profiles)
    results: list[VectorResult] = []

    def add(profile: str, check_id: str, ok: bool, reason: str | None = None) -> None:
        if profile not in profiles:
            return
        results.append(
            VectorResult(
                vector_id=check_id,
                profile=profile,
                status="passed" if ok else "failed",
                reason=None if ok else reason,
                request_id=None,
                response_id=None,
                response_sha256=None,
                repeats=0,
            )
        )

    add(
        "core@1",
        "static-core-authority",
        raw["authority"]["may_grant"] is False
        and raw["authority"]["may_rewrite_semantics"] is False
        and "command-json@1" in raw["bindings"],
        "core requires command-json and a non-authorizing, non-mutating boundary",
    )
    add(
        "replay@1",
        "static-replay-contract",
        adapter.deterministic and adapter.replayable and raw.get("idempotency_key") == "event_id",
        "replay requires deterministic output, replayability, and event_id idempotency",
    )
    lifecycle = raw["lifecycle"]
    add(
        "lifecycle@1",
        "static-lifecycle-contract",
        lifecycle.get("supports_snapshot") is True and lifecycle.get("supports_reset") is True,
        "lifecycle requires snapshot and reset support",
    )
    observability = raw["observability"]
    add(
        "observability@1",
        "static-observability-contract",
        observability.get("trace_context") == "w3c-trace-context"
        and observability.get("structured_logs") is True,
        "observability requires W3C Trace Context and structured logs",
    )
    supply = raw["supply"]
    supply_ok = bool(supply.get("license_expression")) and bool(supply.get("artifacts"))
    add("supply@1", "static-supply-contract", supply_ok, "supply metadata is incomplete")
    privacy = raw["privacy"]
    add(
        "privacy@1",
        "static-privacy-contract",
        set(privacy.get("classes", [])).issubset(PRIVACY_CLASSES)
        and bool(privacy.get("retention")),
        "privacy classes or retention policy are incomplete",
    )
    accessibility = raw["accessibility"]
    add(
        "accessibility@1",
        "static-accessibility-contract",
        bool(accessibility.get("input_modalities"))
        and bool(accessibility.get("output_modalities"))
        and bool(accessibility.get("fallbacks")),
        "accessibility modalities or fallbacks are incomplete",
    )
    delegation = raw["delegation"]
    add(
        "agent-delegation@1",
        "static-agent-delegation-contract",
        delegation.get("may_escalate_authority") is False
        and (delegation.get("accepts_human") or delegation.get("accepts_agent")),
        "delegation must name accepted principals and forbid authority escalation",
    )
    return results


def _verified_profiles(
    adapter: FloorAdapter,
    results: Iterable[VectorResult],
) -> tuple[str, ...]:
    grouped: dict[str, list[VectorResult]] = {profile: [] for profile in adapter.profiles}
    for result in results:
        grouped.setdefault(result.profile, []).append(result)
    verified: list[str] = []
    for profile in PROFILE_ORDER:
        if profile not in adapter.profiles:
            continue
        rows = grouped.get(profile, [])
        if rows and all(row.status == "passed" for row in rows):
            verified.append(profile)
    return tuple(verified)


def quality_tier(
    spec: FloorSpec,
    verified_profiles: Iterable[str],
    *,
    independent_verifier: bool = False,
    substitution_receipt_sha256: str | None = None,
) -> str:
    verified = set(verified_profiles)
    tier = "declared"
    for candidate in TIER_ORDER[1:]:
        required = set(spec.raw["quality_tiers"][candidate]["profiles"])
        if not required.issubset(verified):
            break
        if candidate == "platinum":
            if not independent_verifier or substitution_receipt_sha256 is None:
                break
            _validate_sha256(
                substitution_receipt_sha256,
                where="substitution_receipt_sha256",
            )
        tier = candidate
    return tier


def _submission_from_results(
    spec: FloorSpec,
    adapter: FloorAdapter,
    results: list[VectorResult],
    *,
    independent_verifier: bool,
    substitution_receipt_sha256: str | None,
) -> dict[str, Any]:
    verified = _verified_profiles(adapter, results)
    failures = [result for result in results if result.status != "passed"]
    result = "pass" if not failures and "core@1" in verified else "fail"
    tier = quality_tier(
        spec,
        verified,
        independent_verifier=independent_verifier,
        substitution_receipt_sha256=substitution_receipt_sha256,
    )
    badges = [profile.removesuffix("@1") for profile in verified if profile not in {"core@1"}]
    submission: dict[str, Any] = {
        "format": SUBMISSION_FORMAT,
        "floor_id": spec.floor_id,
        "floor_version": spec.floor_version,
        "adapter_id": adapter.adapter_id,
        "adapter_version": adapter.adapter_version,
        "descriptor_id": adapter.descriptor_id,
        "declared_profiles": list(adapter.profiles),
        "verified_profiles": list(verified),
        "quality_tier": tier,
        "badges": sorted(badges),
        "result": result,
        "tests": [
            {
                "vector_id": item.vector_id,
                "profile": item.profile,
                "status": item.status,
                "reason": item.reason,
                "request_id": item.request_id,
                "response_id": item.response_id,
                "response_sha256": item.response_sha256,
                "repeats": item.repeats,
            }
            for item in sorted(results, key=lambda row: (PROFILE_ORDER.index(row.profile), row.vector_id))
        ],
        "evidence": {
            "floor_spec_sha256": hashlib.sha256(spec.source_path.read_bytes()).hexdigest(),
            "adapter_descriptor_sha256": hashlib.sha256(adapter.source_path.read_bytes()).hexdigest(),
            "vector_set_sha256": sha256_hex(spec.raw["vectors"]),
            "independent_verifier": independent_verifier,
            "substitution_receipt_sha256": substitution_receipt_sha256,
        },
        "verifier": {
            "implementation": "estate-lab-python",
            "version": "0.3.0",
            "authority": "conformance only; not semantic truth or deployment approval",
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.system().lower(),
        },
    }
    submission["submission_id"] = derived_submission_id(submission)
    return submission


def run_floor_conformance(
    spec: FloorSpec,
    adapter: FloorAdapter,
    *,
    output_root: Path | None = None,
    independent_verifier: bool = False,
    substitution_receipt_sha256: str | None = None,
) -> FloorSubmission:
    """Run every claimed profile and optionally emit a checksummed submission bundle."""

    results = _static_profile_checks(spec, adapter)
    for vector in spec.raw["vectors"]:
        profile = vector["profile"]
        if profile not in adapter.profiles:
            continue
        vector_id = vector["id"]
        repeats = int(vector.get("repeats", 1))
        request_id: str | None = None
        response_id: str | None = None
        response_sha256: str | None = None
        reason: str | None = None
        status = "passed"
        responses: list[bytes] = []
        try:
            request = materialize_request(spec, adapter, vector)
            request_id = request["request_id"]
            for _ in range(repeats):
                response = invoke_floor_adapter(adapter, request)
                validate_floor_response(adapter, request, response, vector["expect"])
                response_id = response["response_id"]
                encoded = canonical_json_bytes(response)
                response_sha256 = hashlib.sha256(encoded).hexdigest()
                responses.append(encoded)
            if repeats > 1 and any(item != responses[0] for item in responses[1:]):
                raise FloorProtocolError("repeated request did not produce byte-identical responses")
        except FloorProtocolError as exc:
            status = "failed"
            reason = str(exc)
        results.append(
            VectorResult(
                vector_id=vector_id,
                profile=profile,
                status=status,
                reason=reason,
                request_id=request_id,
                response_id=response_id,
                response_sha256=response_sha256,
                repeats=repeats,
            )
        )

    submission_raw = _submission_from_results(
        spec,
        adapter,
        results,
        independent_verifier=independent_verifier,
        substitution_receipt_sha256=substitution_receipt_sha256,
    )
    submission = load_floor_submission_from_value(submission_raw)
    if output_root is not None:
        bundle = output_root / submission.submission_id
        bundle.mkdir(parents=True, exist_ok=True)
        write_json(bundle / "submission.json", submission.raw)
        write_json(bundle / "floor.snapshot.json", spec.raw)
        write_json(bundle / "adapter.snapshot.json", adapter.raw)
        summary = render_conformance_summary(submission.raw)
        (bundle / "SUMMARY.md").write_text(summary, encoding="utf-8", newline="\n")
        _write_checksums(bundle)
    return submission


def render_conformance_summary(submission: Mapping[str, Any]) -> str:
    lines = [
        "# Interaction Floor conformance submission",
        "",
        f"Submission: `{submission['submission_id']}`",
        f"Adapter: `{submission['adapter_id']}@{submission['adapter_version']}`",
        f"Floor: `{submission['floor_id']}` (`{submission['floor_version']}`)",
        f"Result: **{str(submission['result']).upper()}**",
        f"Quality tier: **{submission['quality_tier']}**",
        f"Verified profiles: {', '.join(submission['verified_profiles']) or 'none'}",
        "",
        "| Profile | Vector | Status | Reason |",
        "|---|---|---|---|",
    ]
    for row in submission["tests"]:
        lines.append(
            f"| `{row['profile']}` | `{row['vector_id']}` | {row['status']} | "
            f"{(row.get('reason') or '').replace('|', '\\|')} |"
        )
    lines.extend(
        [
            "",
            "This receipt proves conformance to the named test vectors and descriptor checks. "
            "It does not grant deployment authority, validate domain meaning, certify physical safety, "
            "or establish that a supplier is suitable outside the tested boundary.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_checksums(root: Path) -> None:
    rows: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "CHECKSUMS.sha256":
            continue
        relative = path.relative_to(root).as_posix()
        rows.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {relative}")
    (root / "CHECKSUMS.sha256").write_text("\n".join(rows) + "\n", encoding="utf-8")


def load_floor_submission_from_value(raw: Mapping[str, Any]) -> FloorSubmission:
    value = dict(raw)
    if value.get("format") != SUBMISSION_FORMAT:
        raise FloorProtocolError(f"submission format must be {SUBMISSION_FORMAT!r}")
    submission_id = _require_string(value, "submission_id", where="submission")
    expected_id = derived_submission_id(value)
    if submission_id != expected_id:
        raise FloorProtocolError(
            f"submission_id mismatch: declared {submission_id!r}, expected {expected_id!r}"
        )
    floor_id = _require_string(value, "floor_id", where="submission")
    adapter_id = _require_string(value, "adapter_id", where="submission")
    adapter_version = _require_string(value, "adapter_version", where="submission")
    _validate_semver(adapter_version, where="submission.adapter_version")
    descriptor_id = _require_string(value, "descriptor_id", where="submission")
    result = _require_string(value, "result", where="submission")
    if result not in {"pass", "fail"}:
        raise FloorProtocolError("submission.result must be pass or fail")
    tier = _require_string(value, "quality_tier", where="submission")
    if tier not in TIER_ORDER:
        raise FloorProtocolError(f"submission.quality_tier must be one of {list(TIER_ORDER)}")
    verified = _require_string_list(
        value,
        "verified_profiles",
        where="submission",
        allow_empty=True,
    )
    tests = value.get("tests")
    if not isinstance(tests, list) or not tests:
        raise FloorProtocolError("submission.tests must be a non-empty array")
    for index, test in enumerate(tests):
        if not isinstance(test, dict):
            raise FloorProtocolError(f"submission.tests[{index}] must be an object")
        if test.get("status") not in {"passed", "failed"}:
            raise FloorProtocolError(f"submission.tests[{index}].status is invalid")
    if result == "pass" and any(test.get("status") != "passed" for test in tests):
        raise FloorProtocolError("passing submission contains failed tests")
    return FloorSubmission(
        submission_id=submission_id,
        floor_id=floor_id,
        adapter_id=adapter_id,
        adapter_version=adapter_version,
        descriptor_id=descriptor_id,
        result=result,
        tier=tier,
        verified_profiles=verified,
        raw=value,
    )


def load_floor_submission(path: Path) -> FloorSubmission:
    try:
        raw = load_json(path)
    except (OSError, ValueError) as exc:
        raise FloorProtocolError(f"cannot load submission {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise FloorProtocolError("submission root must be an object")
    submission = load_floor_submission_from_value(raw)
    return FloorSubmission(**{**submission.__dict__, "source_path": path.resolve()})


def build_floor_registry(
    spec: FloorSpec,
    submissions: Iterable[FloorSubmission],
) -> dict[str, Any]:
    def version_key(version: str) -> tuple[int, int, int, str]:
        match = SEMVER_RE.fullmatch(version)
        if match is None:
            raise FloorProtocolError(f"invalid adapter semantic version: {version}")
        core = version.split("+", 1)[0]
        core, _, suffix = core.partition("-")
        major, minor, patch = (int(part) for part in core.split("."))
        return (major, minor, patch, suffix)

    rows = sorted(
        submissions,
        key=lambda item: (item.adapter_id, version_key(item.adapter_version)),
    )
    entries: dict[str, list[dict[str, Any]]] = {}
    seen_versions: set[tuple[str, str]] = set()
    for submission in rows:
        if submission.floor_id != spec.floor_id:
            raise FloorProtocolError(
                f"submission {submission.submission_id} targets a different floor"
            )
        if submission.result != "pass" or submission.tier == "declared":
            raise FloorProtocolError(
                f"submission {submission.submission_id} is not registry-admissible"
            )
        key = (submission.adapter_id, submission.adapter_version)
        if key in seen_versions:
            raise FloorProtocolError(f"duplicate adapter version in registry: {key}")
        seen_versions.add(key)
        entries.setdefault(submission.adapter_id, []).append(
            {
                "adapter_version": submission.adapter_version,
                "descriptor_id": submission.descriptor_id,
                "submission_id": submission.submission_id,
                "quality_tier": submission.tier,
                "verified_profiles": list(submission.verified_profiles),
                "badges": list(submission.raw.get("badges", [])),
            }
        )
    registry: dict[str, Any] = {
        "format": REGISTRY_FORMAT,
        "floor_id": spec.floor_id,
        "floor_version": spec.floor_version,
        "entry_count": sum(len(value) for value in entries.values()),
        "adapters": [
            {"adapter_id": adapter_id, "versions": versions}
            for adapter_id, versions in sorted(entries.items())
        ],
        "admission_rule": (
            "pass + bronze-or-higher conformance; registry presence is not deployment approval"
        ),
    }
    registry["registry_id"] = derived_registry_id(registry)
    return registry


def validate_floor_registry(raw: Mapping[str, Any], spec: FloorSpec | None = None) -> dict[str, Any]:
    value = dict(raw)
    if value.get("format") != REGISTRY_FORMAT:
        raise FloorProtocolError(f"registry format must be {REGISTRY_FORMAT!r}")
    registry_id = _require_string(value, "registry_id", where="registry")
    expected_id = derived_registry_id(value)
    if registry_id != expected_id:
        raise FloorProtocolError(
            f"registry_id mismatch: declared {registry_id!r}, expected {expected_id!r}"
        )
    if spec is not None and value.get("floor_id") != spec.floor_id:
        raise FloorProtocolError("registry targets a different floor")
    adapters = value.get("adapters")
    if not isinstance(adapters, list):
        raise FloorProtocolError("registry.adapters must be an array")
    count = 0
    seen: set[tuple[str, str]] = set()
    for index, row in enumerate(adapters):
        if not isinstance(row, dict):
            raise FloorProtocolError(f"registry.adapters[{index}] must be an object")
        adapter_id = _require_string(row, "adapter_id", where=f"registry.adapters[{index}]")
        versions = row.get("versions")
        if not isinstance(versions, list) or not versions:
            raise FloorProtocolError(f"registry.adapters[{index}].versions must be non-empty")
        for version in versions:
            if not isinstance(version, dict):
                raise FloorProtocolError("registry version row must be an object")
            version_text = _require_string(version, "adapter_version", where="registry.version")
            key = (adapter_id, version_text)
            if key in seen:
                raise FloorProtocolError(f"duplicate registry entry: {key}")
            seen.add(key)
            count += 1
    if value.get("entry_count") != count:
        raise FloorProtocolError("registry.entry_count mismatch")
    return value


def render_registry_markdown(registry: Mapping[str, Any]) -> str:
    lines = [
        "# Interaction Floor adapter registry",
        "",
        f"Registry: `{registry['registry_id']}`",
        f"Floor: `{registry['floor_id']}`",
        f"Entries: **{registry['entry_count']}**",
        "",
        "| Adapter | Version | Tier | Profiles | Submission |",
        "|---|---|---|---|---|",
    ]
    for adapter in registry["adapters"]:
        for version in adapter["versions"]:
            lines.append(
                f"| `{adapter['adapter_id']}` | `{version['adapter_version']}` | "
                f"{version['quality_tier']} | {', '.join(version['verified_profiles'])} | "
                f"`{version['submission_id']}` |"
            )
    lines.extend(
        [
            "",
            "Registry admission proves a named conformance submission. It does not establish "
            "domain correctness, operational safety, supplier fitness, or authority to deploy.",
            "",
        ]
    )
    return "\n".join(lines)


def build_floor_description(spec: FloorSpec) -> dict[str, Any]:
    return {
        "format": FLOOR_FORMAT,
        "floor_id": spec.floor_id,
        "floor_version": spec.floor_version,
        "title": spec.title,
        "request_format": REQUEST_FORMAT,
        "response_format": RESPONSE_FORMAT,
        "event_format": EVENT_FORMAT,
        "profiles": list(spec.raw["profiles"]),
        "quality_tiers": list(spec.raw["quality_tiers"]),
        "bindings": [binding["id"] for binding in spec.raw["bindings"]],
        "vector_count": len(spec.raw["vectors"]),
        "authority_boundary": spec.raw["authority_boundary"],
    }


def render_asyncapi(spec: FloorSpec) -> str:
    """Render a deterministic AsyncAPI-compatible projection without a YAML dependency."""

    return "\n".join(
        [
            "asyncapi: 3.0.0",
            "info:",
            f"  title: {spec.title}",
            f"  version: {spec.floor_version}",
            "  description: Portable semantic interaction envelopes; conformance does not grant authority.",
            "channels:",
            "  interactionRequests:",
            "    address: axm/interaction/request",
            "    messages:",
            "      request:",
            "        $ref: '#/components/messages/InteractionRequest'",
            "  interactionResponses:",
            "    address: axm/interaction/response",
            "    messages:",
            "      response:",
            "        $ref: '#/components/messages/InteractionResponse'",
            "operations:",
            "  receiveInteraction:",
            "    action: receive",
            "    channel:",
            "      $ref: '#/channels/interactionRequests'",
            "  sendInteractionResult:",
            "    action: send",
            "    channel:",
            "      $ref: '#/channels/interactionResponses'",
            "components:",
            "  messages:",
            "    InteractionRequest:",
            "      payload:",
            "        $ref: './schemas/floor-request.schema.json'",
            "    InteractionResponse:",
            "      payload:",
            "        $ref: './schemas/floor-response.schema.json'",
            "x-axm-floor-id: " + spec.floor_id,
            "",
        ]
    )


def render_adapter_source(adapter_id: str) -> str:
    """Return a standalone stdlib adapter used by both the reference and starter kit."""

    template = r'''#!/usr/bin/env python3
"""Standalone Interaction Floor command-json adapter.

This file intentionally uses only the Python standard library. It may translate
into a domain runtime, but it may not grant authority or change semantic fields.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ADAPTER_ID = __ADAPTER_ID__


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256(value):
    payload = value if isinstance(value, bytes) else canonical(value)
    return hashlib.sha256(payload).hexdigest()


def stable(prefix, value, length=32):
    return f"{prefix}_{sha256(value)[:length]}"


def response_id(response):
    return stable("floorres1", {key: value for key, value in response.items() if key != "response_id"})


def request_id(request):
    return stable("floorreq1", {key: value for key, value in request.items() if key != "request_id"})


def semantic(event):
    return {
        "semantic_id": event.get("semantic_id"),
        "subject": event.get("subject"),
        "operation": event.get("operation"),
        "state_path": event.get("state_path"),
        "value": event.get("value"),
        "authority": event.get("authority"),
    }


def finish(request, accepted, reason=None, outcome=None, **extra):
    response = {
        "format": "axm-interaction-response/1",
        "request_id": request.get("request_id", "unresolved"),
        "adapter_id": ADAPTER_ID,
        "kind": str(request.get("kind") or "unknown"),
        "accepted": accepted,
        "reason": reason,
        "outcome": outcome or ("accepted" if accepted else "refused"),
        "semantic_digest": None,
        "observations": {},
    }
    response.update(extra)
    response["response_id"] = response_id(response)
    return response


def main(request_path, response_path, descriptor_path):
    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    descriptor = json.loads(Path(descriptor_path).read_text(encoding="utf-8"))
    if request.get("format") != "axm-interaction-request/1":
        result = finish(request, False, "request_format_unsupported")
    elif request.get("request_id") != request_id(request):
        result = finish(request, False, "request_identity_mismatch")
    elif request.get("target_adapter_id") != ADAPTER_ID:
        result = finish(request, False, "adapter_target_mismatch")
    elif str(request.get("floor_version", "")).split(".", 1)[0] != "1":
        result = finish(request, False, "floor_version_unsupported")
    elif request.get("context", {}).get("deadline_unix_ms", 1) <= 0:
        result = finish(request, False, "request_deadline_expired")
    elif request.get("kind") == "describe":
        result = finish(request, True, descriptor_id=descriptor["descriptor_id"], descriptor=descriptor)
    elif request.get("kind") == "health":
        result = finish(request, True, health={"state": "ready", "details": "reference adapter ready"})
    elif request.get("kind") == "snapshot":
        snapshot = {"format": "axm-interaction-snapshot/1", "adapter_id": ADAPTER_ID, "state": {}}
        snapshot["snapshot_id"] = stable("floorsnap1", snapshot)
        result = finish(request, True, snapshot=snapshot)
    elif request.get("kind") == "reset":
        result = finish(request, True, outcome="reset")
    elif request.get("kind") == "execute":
        event = request.get("event")
        if not isinstance(event, dict):
            result = finish(request, False, "semantic_event_missing")
        elif event.get("format") != "axm-semantic-event/1":
            result = finish(request, False, "semantic_event_format")
        elif not all(key in event.get("authority", {}) for key in ("actor", "role", "mandate", "ownership_epoch")):
            result = finish(request, False, "authority_incomplete")
        elif event.get("semantic_digest") != sha256(semantic(event)):
            result = finish(request, False, "semantic_digest_mismatch")
        else:
            observations = {
                "event_id": event.get("event_id"),
                "privacy_class": request.get("context", {}).get("privacy_class"),
            }
            traceparent = request.get("context", {}).get("traceparent")
            if traceparent is not None:
                observations["traceparent"] = traceparent
            delegation = request.get("context", {}).get("delegation")
            if isinstance(delegation, dict):
                observations["delegation_id"] = delegation.get("delegation_id")
            result = finish(
                request,
                True,
                outcome="accepted",
                semantic_digest=event["semantic_digest"],
                observations=observations,
            )
    else:
        result = finish(request, False, "request_kind_unsupported")
    Path(response_path).write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: adapter.py REQUEST RESPONSE DESCRIPTOR")
    main(sys.argv[1], sys.argv[2], sys.argv[3])
'''
    return template.replace("__ADAPTER_ID__", repr(adapter_id))


def build_adapter_descriptor(
    *,
    adapter_id: str,
    name: str,
    source_sha256: str,
    floor_version: str,
    source_path: str = "adapter.py",
) -> dict[str, Any]:
    if ADAPTER_ID_RE.fullmatch(adapter_id) is None:
        raise FloorProtocolError("adapter_id must be a reverse-domain-like lowercase identifier")
    _validate_sha256(source_sha256, where="source_sha256")
    raw: dict[str, Any] = {
        "format": ADAPTER_FORMAT,
        "adapter_id": adapter_id,
        "adapter_version": "0.1.0",
        "name": name,
        "description": "Portable command-json adapter generated from the Interaction Floor starter.",
        "floor": {
            "versions": [floor_version],
            "profiles": list(PROFILE_ORDER),
            "extensions": [],
        },
        "bindings": ["command-json@1"],
        "command": ["{python}", source_path, "{request}", "{response}", "{descriptor}"],
        "timeout_seconds": 10,
        "deterministic": True,
        "replayable": True,
        "local_only": True,
        "network_required": False,
        "idempotency_key": "event_id",
        "capabilities": {
            "directions": ["source", "target"],
            "operations": sorted(SEMANTIC_OPERATIONS),
            "modalities": ["semantic-json"],
        },
        "authority": {
            "consumes": ["actor", "role", "mandate", "ownership_epoch"],
            "may_grant": False,
            "may_rewrite_semantics": False,
        },
        "lifecycle": {
            "health_states": ["ready", "degraded", "unavailable"],
            "supports_snapshot": True,
            "supports_reset": True,
        },
        "observability": {
            "trace_context": "w3c-trace-context",
            "structured_logs": True,
        },
        "privacy": {
            "classes": ["public", "internal", "confidential", "restricted"],
            "retention": "adapter retains no request content by default",
        },
        "accessibility": {
            "input_modalities": ["semantic-json", "keyboard-compatible"],
            "output_modalities": ["structured-json", "text"],
            "fallbacks": ["text receipt", "software twin"],
        },
        "delegation": {
            "accepts_human": True,
            "accepts_agent": True,
            "may_escalate_authority": False,
        },
        "supply": {
            "license_expression": "Apache-2.0",
            "artifacts": [{"path": source_path, "sha256": source_sha256}],
            "sbom_ref": None,
            "provenance_ref": None,
        },
        "authority_exclusions": [
            "does not define semantic action meaning",
            "does not grant actor, role, mandate, or ownership authority",
            "does not certify physical safety",
            "does not accept a human decision or outcome",
            "does not become the canonical run record",
        ],
    }
    raw["descriptor_id"] = derived_adapter_descriptor_id(raw)
    return raw


def initialize_adapter(
    directory: Path,
    *,
    adapter_id: str,
    name: str,
    floor_version: str,
    force: bool = False,
) -> FloorAdapter:
    if directory.exists() and any(directory.iterdir()) and not force:
        raise FloorProtocolError(f"adapter directory is not empty: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    source = render_adapter_source(adapter_id)
    source_path = directory / "adapter.py"
    source_path.write_text(source, encoding="utf-8", newline="\n")
    descriptor = build_adapter_descriptor(
        adapter_id=adapter_id,
        name=name,
        source_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
        floor_version=floor_version,
    )
    descriptor_path = directory / "adapter.json"
    write_json(descriptor_path, descriptor)
    readme = f"""# {name}\n\nThis adapter implements the AXM Interaction Floor command-json binding without importing the AXM estate.\n\nRun conformance from an Estate Lab checkout:\n\n```bash\npython -m estate_lab floor test --adapter {descriptor_path.name} --output conformance\n```\n\nThe generated adapter is a deterministic echo boundary. Replace its accepted execute branch with a bounded translation into your product while preserving the semantic digest and authority fields.\n"""
    (directory / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    return load_floor_adapter(descriptor_path)


def verify_checksum_file(root: Path) -> int:
    checksum_path = root / "CHECKSUMS.sha256"
    if not checksum_path.is_file():
        raise FloorProtocolError(f"missing checksum file: {checksum_path}")
    count = 0
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        expected, relative = line.split("  ", 1)
        actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise FloorProtocolError(f"checksum mismatch: {root / relative}")
        count += 1
    return count
