"""Execution and verification engine for frontier fingerprint campaigns."""

from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .adapters import (
    HTTPAdapter,
    MockAdapter,
    build_request_body,
    normalize_response,
    request_contract_descriptor,
    selected_response_headers,
)
from .canonical import (
    canonical_json_bytes,
    load_json,
    read_jsonl,
    safe_relative_path,
    sha256_bytes,
    sha256_object,
    write_bytes_atomic,
    write_json_atomic,
    write_jsonl_atomic,
)
from .contracts import (
    ContractError,
    PLAN_SCHEMA,
    RECEIPT_SCHEMA,
    api_contract_hash,
    assert_live_authorized,
    manifest_hash,
    model_binding_display,
    resolve_model,
    resolved_manifest_snapshot,
    validate_manifest,
)
from .probes import build_schedule, materialize_prompt, public_plan


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_json_body(body: bytes) -> Mapping[str, Any]:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ContractError(f"provider response body is not JSON: {exc}") from exc
    if not isinstance(parsed, Mapping):
        raise ContractError("provider response body must be a JSON object")
    return parsed


def _anchor_match(output_text: str, expected_anchor: str | None) -> bool | None:
    if expected_anchor is None:
        return None
    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, Mapping) and parsed.get("anchor") == expected_anchor


def _estimate_cost(
    adapter: str, usage: Mapping[str, Any], pricing: Mapping[str, Any] | None
) -> float | None:
    if pricing is None:
        return 0.0 if adapter == "mock" else None

    input_tokens = usage.get("provider_input_tokens")
    cache_write = usage.get("cache_creation_input_tokens")
    cache_read = usage.get("cache_read_input_tokens")
    output = usage.get("output_tokens")
    if all(value is None for value in (input_tokens, cache_write, cache_read, output)):
        return None

    if adapter == "openai_responses":
        total_input = int(input_tokens or 0)
        cached = int(cache_read or 0)
        uncached = max(0, total_input - cached)
        cost = (
            uncached * float(pricing["input_per_million"])
            + cached * float(pricing["cache_read_per_million"])
            + int(output or 0) * float(pricing["output_per_million"])
        ) / 1_000_000.0
        return cost

    cost = (
        int(input_tokens or 0) * float(pricing["input_per_million"])
        + int(cache_write or 0) * float(pricing["cache_write_per_million"])
        + int(cache_read or 0) * float(pricing["cache_read_per_million"])
        + int(output or 0) * float(pricing["output_per_million"])
    ) / 1_000_000.0
    return cost


def build_plan(manifest: Mapping[str, Any], *, resolve: bool = False) -> dict[str, Any]:
    validate_manifest(manifest)
    model = resolve_model(manifest) if resolve else model_binding_display(manifest)
    plan = public_plan(manifest, model)
    if plan["schema"] != PLAN_SCHEMA:
        raise AssertionError("plan schema mismatch")
    return plan


def execute_campaign(
    manifest: Mapping[str, Any],
    run_dir: Path,
    *,
    cli_live: bool = False,
    environ: Mapping[str, str] | None = None,
    mock_adapter: MockAdapter | None = None,
) -> dict[str, Any]:
    """Execute a campaign and retain exact request/response bodies privately."""

    validate_manifest(manifest)
    env = os.environ if environ is None else environ
    assert_live_authorized(manifest, cli_live=cli_live, environ=env)
    model = resolve_model(manifest, env)
    schedule = build_schedule(manifest)
    execution = manifest["execution"]
    if len(schedule) > int(execution["max_requests"]):
        raise ContractError("deterministic schedule exceeds manifest request ceiling")

    run_dir = run_dir.resolve()
    if run_dir.exists() and any(run_dir.iterdir()):
        raise ContractError(f"run directory must be absent or empty: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "private" / "requests").mkdir(parents=True, exist_ok=True)
    (run_dir / "private" / "responses").mkdir(parents=True, exist_ok=True)

    snapshot = resolved_manifest_snapshot(manifest, model)
    write_json_atomic(run_dir / "manifest.snapshot.json", snapshot)
    plan = public_plan(manifest, model)
    write_json_atomic(run_dir / "plan.json", plan)

    adapter_name = manifest["subject"]["adapter"]
    if adapter_name == "mock":
        adapter: Any = mock_adapter or MockAdapter()
    else:
        adapter = HTTPAdapter(manifest, env)

    started_monotonic = time.monotonic()
    previous_hash: str | None = None
    receipts: list[dict[str, Any]] = []
    cumulative_cost = 0.0
    provider_error_count = 0
    termination_reason = "completed"

    for spec in schedule:
        wall_elapsed = time.monotonic() - started_monotonic
        if wall_elapsed > int(execution["max_wall_seconds"]):
            raise ContractError("campaign wall-clock ceiling reached before next dispatch")

        prompt = materialize_prompt(spec)
        request_object = build_request_body(
            manifest=manifest, spec=spec, prompt=prompt, model=model
        )
        request_bytes = canonical_json_bytes(request_object)
        request_rel = f"private/requests/{spec['ordinal']:04d}.json"
        response_rel = f"private/responses/{spec['ordinal']:04d}.json"
        write_bytes_atomic(run_dir / request_rel, request_bytes)

        started_at = _utc_now()
        transport = adapter.execute(request_bytes)
        ended_at = _utc_now()
        write_bytes_atomic(run_dir / response_rel, transport.body)

        response_object = _parse_json_body(transport.body)
        normalized = normalize_response(adapter_name, response_object, model)
        captured_headers = selected_response_headers(manifest, transport.response_headers)
        anchor_match = _anchor_match(normalized.output_text, prompt.expected_anchor)
        cost = _estimate_cost(adapter_name, normalized.usage, manifest.get("pricing"))
        if cost is not None:
            cumulative_cost += cost
        ceiling = float(execution["max_estimated_usd"])
        if ceiling >= 0 and cumulative_cost > ceiling + 1e-12:
            budget_status = "exceeded_after_observation"
        else:
            budget_status = "within_ceiling"

        request_descriptor = request_contract_descriptor(manifest, request_bytes)
        response_descriptor = {
            "body_path": response_rel,
            "body_sha256": sha256_bytes(transport.body),
            "body_bytes": len(transport.body),
            "http_status": transport.status_code,
            "transport_error": transport.transport_error,
            "captured_headers": captured_headers,
            "captured_headers_sha256": sha256_object(captured_headers),
            "usage": normalized.usage,
            "usage_sha256": sha256_object(normalized.usage),
            "usage_source_paths": normalized.usage_source_paths,
            "identity": normalized.identity,
            "identity_sha256": sha256_object(normalized.identity),
            "stop_reason": normalized.stop_reason,
            "error_type": normalized.error_type,
            "anchor_match": anchor_match,
        }
        observation_status = "observed"
        if transport.status_code < 200 or transport.status_code >= 300:
            observation_status = "provider_error"
            provider_error_count += 1
        if normalized.identity["model_binding_status"] == "mismatch":
            observation_status = "identity_mismatch"
        if budget_status == "exceeded_after_observation":
            observation_status = "budget_exceeded"

        receipt_core = {
            "schema": RECEIPT_SCHEMA,
            "campaign_id": manifest["campaign_id"],
            "manifest_sha256": manifest_hash(manifest),
            "api_contract_sha256": api_contract_hash(manifest),
            "usage_semantics_id": manifest["subject"]["api_contract"][
                "usage_semantics_id"
            ],
            "observation_id": spec["observation_id"],
            "ordinal": spec["ordinal"],
            "probe_id": spec["probe_id"],
            "probe_kind": spec["probe_kind"],
            "probe_contract_sha256": spec["probe_contract_sha256"],
            "block": spec["block"],
            "condition": spec["condition"],
            "sequence_in_block": spec["sequence_in_block"],
            "status": observation_status,
            "request": {
                "body_path": request_rel,
                **request_descriptor,
                "prompt_descriptor": prompt.public_descriptor,
            },
            "response": response_descriptor,
            "timing": {
                "started_at": started_at,
                "ended_at": ended_at,
                "latency_ms": round(float(transport.latency_ms), 6),
                "evidence_role": "corroborating_only",
            },
            "budget": {
                "observation_estimated_usd": cost,
                "cumulative_estimated_usd": round(cumulative_cost, 12),
                "ceiling_usd": ceiling,
                "status": budget_status,
            },
            "evidence_binding": {
                "request_body_authenticated": True,
                "request_body_rebuilt_from_frozen_generator": True,
                "response_body_authenticated": True,
                "usage_rederived_from_response_body": True,
                "identity_rederived_from_response_body": True,
                "public_prompt_text_retained": False,
                "public_response_text_retained": False,
            },
            "previous_receipt_sha256": previous_hash,
        }
        receipt_hash = sha256_object(receipt_core)
        receipt = {**receipt_core, "receipt_sha256": receipt_hash}
        receipts.append(receipt)
        previous_hash = receipt_hash

        if observation_status == "budget_exceeded":
            termination_reason = "budget_exceeded"
            break
        if observation_status == "identity_mismatch":
            termination_reason = "identity_mismatch"
            break
        if provider_error_count >= int(execution.get("max_provider_errors", 1)):
            termination_reason = "provider_error_limit"
            break

    write_jsonl_atomic(run_dir / "receipts.jsonl", receipts)
    run_record = {
        "schema": "tier-bench/frontier-fingerprint-run@1",
        "campaign_id": manifest["campaign_id"],
        "manifest_sha256": manifest_hash(manifest),
        "api_contract_sha256": api_contract_hash(manifest),
        "receipt_count": len(receipts),
        "planned_request_count": len(schedule),
        "last_receipt_sha256": previous_hash,
        "cumulative_estimated_usd": round(cumulative_cost, 12),
        "completed": len(receipts) == len(schedule),
        "termination_reason": termination_reason,
        "provider_error_count": provider_error_count,
        "created_at": _utc_now(),
    }
    write_json_atomic(run_dir / "run.json", run_record)
    return run_record


def _manifest_from_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    manifest = json.loads(json.dumps(snapshot))
    subject = manifest["subject"]
    subject.pop("resolved_model", None)
    subject.pop("model_binding_sha256", None)
    return manifest


def _compare_exact(label: str, observed: Any, expected: Any) -> None:
    if observed != expected:
        raise ContractError(f"{label} mismatch: observed={observed!r}, expected={expected!r}")


def verify_run(run_dir: Path) -> dict[str, Any]:
    """Authenticate exact bodies, then rederive usage and identity from them."""

    run_dir = run_dir.resolve()
    snapshot = load_json(run_dir / "manifest.snapshot.json")
    if not isinstance(snapshot, Mapping):
        raise ContractError("manifest snapshot must be an object")
    model = snapshot["subject"].get("resolved_model")
    if not isinstance(model, str) or not model:
        raise ContractError("manifest snapshot lacks resolved model binding")
    manifest = _manifest_from_snapshot(snapshot)
    validate_manifest(manifest)
    receipts = read_jsonl(run_dir / "receipts.jsonl")
    plan = load_json(run_dir / "plan.json")
    _compare_exact("plan schema", plan.get("schema"), PLAN_SCHEMA)
    _compare_exact("plan manifest hash", plan.get("manifest_sha256"), manifest_hash(manifest))
    _compare_exact("plan API contract hash", plan.get("api_contract_sha256"), api_contract_hash(manifest))

    schedule = build_schedule(manifest)
    if len(receipts) > len(schedule):
        raise ContractError("receipt count exceeds deterministic plan")

    previous_hash: str | None = None
    verified = 0
    identity_mismatches = 0
    for index, receipt in enumerate(receipts):
        if not isinstance(receipt, Mapping):
            raise ContractError(f"receipt {index} must be an object")
        _compare_exact(f"receipt {index} schema", receipt.get("schema"), RECEIPT_SCHEMA)
        supplied_hash = receipt.get("receipt_sha256")
        core = dict(receipt)
        core.pop("receipt_sha256", None)
        calculated_hash = sha256_object(core)
        _compare_exact(f"receipt {index} self hash", supplied_hash, calculated_hash)
        _compare_exact(
            f"receipt {index} previous hash",
            receipt.get("previous_receipt_sha256"),
            previous_hash,
        )
        previous_hash = calculated_hash

        spec = schedule[index]
        for field in (
            "observation_id",
            "ordinal",
            "probe_id",
            "probe_kind",
            "probe_contract_sha256",
            "block",
            "condition",
            "sequence_in_block",
        ):
            _compare_exact(f"receipt {index} {field}", receipt.get(field), spec[field])
        _compare_exact(
            f"receipt {index} manifest hash",
            receipt.get("manifest_sha256"),
            manifest_hash(manifest),
        )
        _compare_exact(
            f"receipt {index} API contract hash",
            receipt.get("api_contract_sha256"),
            api_contract_hash(manifest),
        )

        request_info = receipt.get("request")
        response_info = receipt.get("response")
        if not isinstance(request_info, Mapping) or not isinstance(response_info, Mapping):
            raise ContractError(f"receipt {index} lacks request/response evidence")
        request_path = safe_relative_path(run_dir, str(request_info.get("body_path")))
        response_path = safe_relative_path(run_dir, str(response_info.get("body_path")))
        if not request_path.is_file() or not response_path.is_file():
            raise ContractError(f"receipt {index} raw evidence body is missing")
        request_bytes = request_path.read_bytes()
        response_bytes = response_path.read_bytes()
        _compare_exact(
            f"receipt {index} request body hash",
            request_info.get("body_sha256"),
            sha256_bytes(request_bytes),
        )
        _compare_exact(
            f"receipt {index} response body hash",
            response_info.get("body_sha256"),
            sha256_bytes(response_bytes),
        )
        _compare_exact(
            f"receipt {index} request API contract hash",
            request_info.get("api_contract_sha256"),
            api_contract_hash(manifest),
        )
        _compare_exact(
            f"receipt {index} request body bytes",
            request_info.get("body_bytes"),
            len(request_bytes),
        )
        _compare_exact(
            f"receipt {index} response body bytes",
            response_info.get("body_bytes"),
            len(response_bytes),
        )
        captured_headers = response_info.get("captured_headers")
        if not isinstance(captured_headers, Mapping):
            raise ContractError(f"receipt {index} captured headers must be an object")
        _compare_exact(
            f"receipt {index} captured headers hash",
            response_info.get("captured_headers_sha256"),
            sha256_object(captured_headers),
        )

        prompt = materialize_prompt(spec)
        expected_request_object = build_request_body(
            manifest=manifest,
            spec=spec,
            prompt=prompt,
            model=model,
        )
        expected_request_bytes = canonical_json_bytes(expected_request_object)
        _compare_exact(
            f"receipt {index} exact deterministic request body",
            request_bytes,
            expected_request_bytes,
        )
        request_object = _parse_json_body(request_bytes)
        _compare_exact(f"receipt {index} requested model", request_object.get("model"), model)
        response_object = _parse_json_body(response_bytes)
        normalized = normalize_response(manifest["subject"]["adapter"], response_object, model)
        _compare_exact(f"receipt {index} usage", response_info.get("usage"), normalized.usage)
        _compare_exact(
            f"receipt {index} usage hash",
            response_info.get("usage_sha256"),
            sha256_object(normalized.usage),
        )
        _compare_exact(
            f"receipt {index} usage source paths",
            response_info.get("usage_source_paths"),
            normalized.usage_source_paths,
        )
        _compare_exact(f"receipt {index} identity", response_info.get("identity"), normalized.identity)
        _compare_exact(
            f"receipt {index} identity hash",
            response_info.get("identity_sha256"),
            sha256_object(normalized.identity),
        )

        _compare_exact(
            f"receipt {index} prompt descriptor",
            request_info.get("prompt_descriptor"),
            prompt.public_descriptor,
        )
        _compare_exact(
            f"receipt {index} anchor result",
            response_info.get("anchor_match"),
            _anchor_match(normalized.output_text, prompt.expected_anchor),
        )
        if normalized.identity["model_binding_status"] == "mismatch":
            identity_mismatches += 1
        verified += 1

    run_record = load_json(run_dir / "run.json")
    _compare_exact("run schema", run_record.get("schema"), "tier-bench/frontier-fingerprint-run@1")
    _compare_exact("run campaign id", run_record.get("campaign_id"), manifest["campaign_id"])
    _compare_exact("run manifest hash", run_record.get("manifest_sha256"), manifest_hash(manifest))
    _compare_exact("run API contract hash", run_record.get("api_contract_sha256"), api_contract_hash(manifest))
    _compare_exact("run receipt count", run_record.get("receipt_count"), len(receipts))
    _compare_exact("run planned request count", run_record.get("planned_request_count"), len(schedule))
    _compare_exact("run last receipt hash", run_record.get("last_receipt_sha256"), previous_hash)
    actual_provider_errors = sum(1 for receipt in receipts if receipt.get("status") == "provider_error")
    _compare_exact("run provider error count", run_record.get("provider_error_count"), actual_provider_errors)
    completed = len(receipts) == len(schedule)
    _compare_exact("run completed", run_record.get("completed"), completed)
    if completed:
        expected_termination = "completed"
    elif receipts and receipts[-1].get("status") == "budget_exceeded":
        expected_termination = "budget_exceeded"
    elif receipts and receipts[-1].get("status") == "identity_mismatch":
        expected_termination = "identity_mismatch"
    elif actual_provider_errors >= int(manifest["execution"].get("max_provider_errors", 1)):
        expected_termination = "provider_error_limit"
    else:
        raise ContractError("partial run does not satisfy a manifest stopping rule")
    _compare_exact("run termination reason", run_record.get("termination_reason"), expected_termination)
    return {
        "verified": True,
        "campaign_id": manifest["campaign_id"],
        "receipt_count": verified,
        "planned_request_count": len(schedule),
        "last_receipt_sha256": previous_hash,
        "identity_mismatch_count": identity_mismatches,
        "raw_request_bodies_authenticated": verified,
        "raw_response_bodies_authenticated": verified,
        "usage_objects_rederived": verified,
        "identity_objects_rederived": verified,
        "termination_reason": expected_termination,
        "exact_requests_rebuilt": verified,
    }


def reseal_receipts_for_test(receipts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Recompute a chain after mutation. This exists only for adversarial tests.

    It demonstrates that body rederivation catches an attacker who can rewrite the
    recorder's envelope and recompute every receipt hash.
    """

    previous: str | None = None
    result: list[dict[str, Any]] = []
    for receipt in receipts:
        core = dict(receipt)
        core.pop("receipt_sha256", None)
        core["previous_receipt_sha256"] = previous
        digest = sha256_object(core)
        result.append({**core, "receipt_sha256": digest})
        previous = digest
    return result
