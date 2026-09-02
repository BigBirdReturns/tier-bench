"""Fail-closed manifest contracts for frontier fingerprint campaigns."""

from __future__ import annotations

import os
import re
from copy import deepcopy
from typing import Any, Mapping

from .canonical import sha256_object

MANIFEST_SCHEMA = "tier-bench/frontier-fingerprint-manifest@1"
RECEIPT_SCHEMA = "tier-bench/frontier-fingerprint-receipt@1"
SUMMARY_SCHEMA = "tier-bench/frontier-fingerprint-summary@1"
PASSIVE_SCHEMA = "tier-bench/frontier-passive-observation@1"
COMPARISON_SCHEMA = "tier-bench/frontier-fingerprint-comparison@1"
PLAN_SCHEMA = "tier-bench/frontier-fingerprint-plan@1"

ADAPTERS = {"mock", "anthropic_messages", "openai_responses"}
PROBE_KINDS = {
    "cache_reuse",
    "cache_threshold",
    "prefix_boundary",
    "context_sweep",
    "retention",
    "serialization",
    "tool_schema",
    "effort",
    "identity",
}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
LIVE_ACK = "I_ACKNOWLEDGE_PAID_PROVIDER_CALLS"


class ContractError(ValueError):
    """Raised when a manifest or evidence object violates a frozen contract."""


def _require(mapping: Mapping[str, Any], key: str, kind: type, where: str) -> Any:
    if key not in mapping:
        raise ContractError(f"{where}.{key} is required")
    value = mapping[key]
    if not isinstance(value, kind):
        raise ContractError(f"{where}.{key} must be {kind.__name__}")
    return value


def _positive_int(value: Any, where: str, *, minimum: int = 1) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ContractError(f"{where} must be an integer >= {minimum}")
    return value


def _nonnegative_number(value: Any, where: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise ContractError(f"{where} must be a nonnegative number")
    return float(value)


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ContractError(f"schema must be {MANIFEST_SCHEMA!r}")

    campaign_id = _require(manifest, "campaign_id", str, "manifest")
    if not ID_RE.fullmatch(campaign_id):
        raise ContractError("manifest.campaign_id contains unsupported characters")

    subject = _require(manifest, "subject", dict, "manifest")
    adapter = _require(subject, "adapter", str, "manifest.subject")
    if adapter not in ADAPTERS:
        raise ContractError(f"unsupported adapter: {adapter!r}")
    _require(subject, "provider", str, "manifest.subject")

    binding = _require(subject, "model_binding", dict, "manifest.subject")
    literal = binding.get("literal")
    environment = binding.get("environment")
    if bool(literal) == bool(environment):
        raise ContractError(
            "manifest.subject.model_binding requires exactly one of literal or environment"
        )
    if literal is not None and not isinstance(literal, str):
        raise ContractError("model_binding.literal must be a string")
    if environment is not None:
        if not isinstance(environment, str) or not environment.startswith("TIER_"):
            raise ContractError("model_binding.environment must be a TIER_* variable")

    api_contract = _require(subject, "api_contract", dict, "manifest.subject")
    endpoint = _require(api_contract, "endpoint", str, "manifest.subject.api_contract")
    _require(api_contract, "revision", str, "manifest.subject.api_contract")
    _require(api_contract, "usage_semantics_id", str, "manifest.subject.api_contract")
    _require(api_contract, "response_identity_signal", str, "manifest.subject.api_contract")
    headers = _require(api_contract, "request_headers", dict, "manifest.subject.api_contract")
    capture_headers = _require(
        api_contract,
        "response_headers_to_capture",
        list,
        "manifest.subject.api_contract",
    )
    if any(not isinstance(item, str) or not item for item in capture_headers):
        raise ContractError("response_headers_to_capture must contain non-empty strings")

    if adapter == "anthropic_messages":
        if endpoint.rstrip("/") != "https://api.anthropic.com/v1/messages":
            raise ContractError("anthropic_messages endpoint must be the Messages API")
        if not isinstance(headers.get("anthropic-version"), str):
            raise ContractError("anthropic_messages requires a pinned anthropic-version header")
    elif adapter == "openai_responses":
        if endpoint.rstrip("/") != "https://api.openai.com/v1/responses":
            raise ContractError("openai_responses endpoint must be /v1/responses")
        if not api_contract.get("revision").startswith("responses-"):
            raise ContractError("openai_responses revision must pin a responses-* contract")
    elif adapter == "mock" and not endpoint.startswith("mock://"):
        raise ContractError("mock adapter endpoint must use mock://")

    retention = _require(manifest, "retention", dict, "manifest")
    if retention.get("public_text") != "forbidden":
        raise ContractError("manifest.retention.public_text must be 'forbidden'")
    if retention.get("raw_evidence") != "private-run-artifact":
        raise ContractError(
            "manifest.retention.raw_evidence must be 'private-run-artifact'"
        )
    if retention.get("hash_algorithm") != "sha256":
        raise ContractError("manifest.retention.hash_algorithm must be sha256")

    execution = _require(manifest, "execution", dict, "manifest")
    if not isinstance(execution.get("allow_live"), bool):
        raise ContractError("manifest.execution.allow_live must be boolean")
    _positive_int(execution.get("max_requests"), "manifest.execution.max_requests")
    _positive_int(
        execution.get("max_wall_seconds"), "manifest.execution.max_wall_seconds"
    )
    _nonnegative_number(
        execution.get("max_estimated_usd"), "manifest.execution.max_estimated_usd"
    )
    timeout = execution.get("request_timeout_seconds", 120)
    _positive_int(timeout, "manifest.execution.request_timeout_seconds")
    _positive_int(
        execution.get("max_provider_errors", 1),
        "manifest.execution.max_provider_errors",
    )

    if execution["allow_live"]:
        if adapter == "mock":
            raise ContractError("mock campaigns cannot enable live dispatch")
        pricing = _require(manifest, "pricing", dict, "manifest")
        for key in (
            "input_per_million",
            "cache_write_per_million",
            "cache_read_per_million",
            "output_per_million",
        ):
            _nonnegative_number(pricing.get(key), f"manifest.pricing.{key}")
        if execution["max_estimated_usd"] <= 0:
            raise ContractError("live campaigns require a positive estimated cost ceiling")

    probes = _require(manifest, "probes", list, "manifest")
    if not probes:
        raise ContractError("manifest.probes must not be empty")
    seen: set[str] = set()
    total_floor = 0
    for index, probe in enumerate(probes):
        where = f"manifest.probes[{index}]"
        if not isinstance(probe, dict):
            raise ContractError(f"{where} must be an object")
        probe_id = _require(probe, "id", str, where)
        if not ID_RE.fullmatch(probe_id):
            raise ContractError(f"{where}.id contains unsupported characters")
        if probe_id in seen:
            raise ContractError(f"duplicate probe id: {probe_id}")
        seen.add(probe_id)
        kind = _require(probe, "kind", str, where)
        if kind not in PROBE_KINDS:
            raise ContractError(f"unsupported probe kind: {kind!r}")
        repeats = _positive_int(probe.get("repeats", 1), f"{where}.repeats")
        _positive_int(probe.get("seed", index + 1), f"{where}.seed", minimum=0)
        _positive_int(
            probe.get("max_output_tokens", 64), f"{where}.max_output_tokens"
        )
        _validate_probe_shape(probe, where)
        total_floor += minimum_requests_for_probe(probe)

    if total_floor > execution["max_requests"]:
        raise ContractError(
            "manifest execution.max_requests is below the deterministic plan size "
            f"({execution['max_requests']} < {total_floor})"
        )


def _validate_probe_shape(probe: Mapping[str, Any], where: str) -> None:
    kind = probe["kind"]
    if kind in {"cache_reuse", "prefix_boundary", "serialization", "tool_schema"}:
        _positive_int(probe.get("prefix_units"), f"{where}.prefix_units")
        _positive_int(probe.get("suffix_units", 16), f"{where}.suffix_units")
    if kind == "cache_threshold":
        thresholds = _require(probe, "threshold_units", list, where)
        if not thresholds:
            raise ContractError(f"{where}.threshold_units must not be empty")
        for threshold in thresholds:
            _positive_int(threshold, f"{where}.threshold_units[]")
        _positive_int(probe.get("suffix_units", 16), f"{where}.suffix_units")
    if kind == "cache_reuse":
        fraction = probe.get("mutation_fraction", 0.25)
        if not isinstance(fraction, (int, float)) or not 0 <= fraction < 1:
            raise ContractError(f"{where}.mutation_fraction must be in [0, 1)")
    if kind == "prefix_boundary":
        fractions = _require(probe, "mutation_fractions", list, where)
        if not fractions:
            raise ContractError(f"{where}.mutation_fractions must not be empty")
        for fraction in fractions:
            if not isinstance(fraction, (int, float)) or not 0 <= fraction < 1:
                raise ContractError(f"{where}.mutation_fractions values must be in [0, 1)")
    if kind == "context_sweep":
        sizes = _require(probe, "context_units", list, where)
        if not sizes:
            raise ContractError(f"{where}.context_units must not be empty")
        for size in sizes:
            _positive_int(size, f"{where}.context_units[]")
    if kind == "retention":
        _positive_int(probe.get("context_units"), f"{where}.context_units")
        positions = _require(probe, "anchor_positions", list, where)
        if not positions:
            raise ContractError(f"{where}.anchor_positions must not be empty")
        for position in positions:
            if not isinstance(position, (int, float)) or not 0 <= position <= 1:
                raise ContractError(f"{where}.anchor_positions values must be in [0, 1]")
    if kind == "serialization":
        variants = probe.get("variants", ["canonical", "pretty", "reordered"])
        if not isinstance(variants, list) or len(variants) < 2:
            raise ContractError(f"{where}.variants must contain at least two variants")
    if kind == "tool_schema":
        variants = probe.get("variants", ["stable", "description_mutated"])
        if not isinstance(variants, list) or len(variants) < 2:
            raise ContractError(f"{where}.variants must contain at least two variants")
    if kind == "effort":
        levels = _require(probe, "levels", list, where)
        if not levels or any(not isinstance(level, str) for level in levels):
            raise ContractError(f"{where}.levels must contain effort strings")


def minimum_requests_for_probe(probe: Mapping[str, Any]) -> int:
    repeats = int(probe.get("repeats", 1))
    kind = probe["kind"]
    if kind == "cache_reuse":
        return repeats * 3
    if kind == "cache_threshold":
        return repeats * len(probe["threshold_units"]) * 2
    if kind == "prefix_boundary":
        return repeats * (1 + len(probe["mutation_fractions"]))
    if kind == "context_sweep":
        return repeats * len(probe["context_units"])
    if kind == "retention":
        return repeats * len(probe["anchor_positions"])
    if kind == "serialization":
        return repeats * len(probe.get("variants", ["canonical", "pretty", "reordered"]))
    if kind == "tool_schema":
        return repeats * len(probe.get("variants", ["stable", "description_mutated"]))
    if kind == "effort":
        return repeats * len(probe["levels"])
    return repeats


def manifest_hash(manifest: Mapping[str, Any]) -> str:
    validate_manifest(manifest)
    return sha256_object(manifest)


def api_contract_hash(manifest: Mapping[str, Any]) -> str:
    validate_manifest(manifest)
    subject = manifest["subject"]
    contract = {
        "adapter": subject["adapter"],
        "provider": subject["provider"],
        "api_contract": subject["api_contract"],
    }
    return sha256_object(contract)


def probe_contract_hash(probe: Mapping[str, Any]) -> str:
    public = {key: value for key, value in probe.items() if key != "notes"}
    return sha256_object(public)


def resolve_model(manifest: Mapping[str, Any], environ: Mapping[str, str] | None = None) -> str:
    validate_manifest(manifest)
    binding = manifest["subject"]["model_binding"]
    if "literal" in binding:
        return binding["literal"]
    env = os.environ if environ is None else environ
    name = binding["environment"]
    value = env.get(name, "").strip()
    if not value:
        raise ContractError(f"model binding environment variable is unset: {name}")
    return value


def model_binding_display(manifest: Mapping[str, Any]) -> str:
    binding = manifest["subject"]["model_binding"]
    if "literal" in binding:
        return binding["literal"]
    return f"UNRESOLVED_ENV:{binding['environment']}"


def resolved_manifest_snapshot(
    manifest: Mapping[str, Any], model: str
) -> dict[str, Any]:
    snapshot = deepcopy(dict(manifest))
    snapshot["subject"]["resolved_model"] = model
    snapshot["subject"]["model_binding_sha256"] = sha256_object(
        manifest["subject"]["model_binding"]
    )
    return snapshot


def assert_live_authorized(
    manifest: Mapping[str, Any],
    *,
    cli_live: bool,
    environ: Mapping[str, str] | None = None,
) -> None:
    validate_manifest(manifest)
    adapter = manifest["subject"]["adapter"]
    if adapter == "mock":
        if cli_live:
            raise ContractError("--live is invalid for the mock adapter")
        return
    if not cli_live:
        raise ContractError("provider dispatch requires the --live command-line gate")
    if not manifest["execution"]["allow_live"]:
        raise ContractError("provider dispatch is disabled by manifest.execution.allow_live")
    env = os.environ if environ is None else environ
    if env.get("TIER_FRONTIER_LIVE") != LIVE_ACK:
        raise ContractError(
            "provider dispatch requires TIER_FRONTIER_LIVE=" + LIVE_ACK
        )


def api_key_environment(adapter: str) -> str:
    if adapter == "anthropic_messages":
        return "ANTHROPIC_API_KEY"
    if adapter == "openai_responses":
        return "OPENAI_API_KEY"
    if adapter == "mock":
        return ""
    raise ContractError(f"unsupported adapter: {adapter}")
