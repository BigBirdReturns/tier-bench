"""Text-free summaries and preregistered matched-cell comparisons."""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from .canonical import load_json, read_jsonl, sha256_object, write_json_atomic
from .contracts import COMPARISON_SCHEMA, ContractError, SUMMARY_SCHEMA
from .engine import verify_run


def _numeric(values: Iterable[Any]) -> list[float]:
    return [float(value) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]


def _distribution(values: Iterable[Any]) -> dict[str, Any]:
    data = sorted(_numeric(values))
    if not data:
        return {"n": 0, "median": None, "minimum": None, "maximum": None, "iqr": None}
    if len(data) == 1:
        iqr = 0.0
    else:
        lower = data[: len(data) // 2]
        upper = data[(len(data) + 1) // 2 :]
        iqr = statistics.median(upper) - statistics.median(lower)
    return {
        "n": len(data),
        "median": statistics.median(data),
        "minimum": min(data),
        "maximum": max(data),
        "iqr": iqr,
    }


def _paired_latency(receipts: list[Mapping[str, Any]]) -> dict[str, Any]:
    by_block: dict[int, dict[str, float]] = defaultdict(dict)
    for receipt in receipts:
        if receipt.get("probe_kind") != "cache_reuse":
            continue
        condition = receipt.get("condition")
        if condition not in {"warm", "mutated"}:
            continue
        latency = receipt.get("timing", {}).get("latency_ms")
        if isinstance(latency, (int, float)):
            by_block[int(receipt["block"])][str(condition)] = float(latency)
    deltas: list[float] = []
    for block in sorted(by_block):
        pair = by_block[block]
        if "warm" in pair and "mutated" in pair:
            deltas.append(pair["warm"] - pair["mutated"])
    return {
        "role": "corroborating_only",
        "design": "interleaved_within_block",
        "paired_block_count": len(deltas),
        "warm_minus_mutated_ms": _distribution(deltas),
        "warm_faster_pair_count": sum(1 for delta in deltas if delta < 0),
        "mutated_faster_pair_count": sum(1 for delta in deltas if delta > 0),
        "ties": sum(1 for delta in deltas if delta == 0),
        "cache_verdict_from_latency": "prohibited",
    }


def _cache_accounting(receipts: list[Mapping[str, Any]]) -> dict[str, Any]:
    by_condition: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for receipt in receipts:
        if receipt.get("probe_kind") == "cache_reuse":
            by_condition[str(receipt.get("condition"))].append(receipt)

    def field(condition: str, name: str) -> list[Any]:
        return [
            receipt.get("response", {}).get("usage", {}).get(name)
            for receipt in by_condition.get(condition, [])
        ]

    warm_read = _numeric(field("warm", "cache_read_input_tokens"))
    mutated_read = _numeric(field("mutated", "cache_read_input_tokens"))
    prime_creation = _numeric(field("prime", "cache_creation_input_tokens"))
    counter_available = bool(warm_read or mutated_read or prime_creation)
    return {
        "evidence_rank": "primary_provider_reported_usage" if counter_available else "unavailable",
        "provider_counter_available": counter_available,
        "prime_cache_creation_input_tokens": _distribution(prime_creation),
        "warm_cache_read_input_tokens": _distribution(warm_read),
        "mutated_cache_read_input_tokens": _distribution(mutated_read),
        "warm_positive_cache_read_count": sum(1 for value in warm_read if value > 0),
        "mutated_positive_cache_read_count": sum(1 for value in mutated_read if value > 0),
        "conclusion_class": (
            "MEASURED_PROVIDER_COUNTERS" if counter_available else "UNMEASURED_PROVIDER_COUNTERS"
        ),
    }


def _cache_threshold(receipts: list[Mapping[str, Any]]) -> dict[str, Any]:
    by_size: dict[int, dict[str, list[float]]] = defaultdict(lambda: {"prime_creation": [], "warm_read": []})
    for receipt in receipts:
        if receipt.get("probe_kind") != "cache_threshold":
            continue
        condition = str(receipt.get("condition"))
        parts = condition.split("-")
        if len(parts) < 3:
            continue
        try:
            size = int(parts[1])
        except ValueError:
            continue
        usage = receipt.get("response", {}).get("usage", {})
        if condition.endswith("-prime"):
            value = usage.get("cache_creation_input_tokens")
            if isinstance(value, (int, float)):
                by_size[size]["prime_creation"].append(float(value))
        elif condition.endswith("-warm"):
            value = usage.get("cache_read_input_tokens")
            if isinstance(value, (int, float)):
                by_size[size]["warm_read"].append(float(value))
    positive_sizes = [
        size for size, values in by_size.items() if any(value > 0 for value in values["warm_read"])
    ]
    return {
        "units_are_synthetic_words_not_provider_tokens": True,
        "by_threshold_units": {
            str(size): {
                "prime_cache_creation_input_tokens": _distribution(values["prime_creation"]),
                "warm_cache_read_input_tokens": _distribution(values["warm_read"]),
                "warm_positive_cache_read_count": sum(1 for value in values["warm_read"] if value > 0),
            }
            for size, values in sorted(by_size.items())
        },
        "lowest_observed_positive_warm_read_threshold_units": min(positive_sizes) if positive_sizes else None,
        "classification": "OBSERVED_THRESHOLD_BRACKET" if positive_sizes else "UNMEASURED_THRESHOLD",
    }


def _api_contract_observations(receipts: list[Mapping[str, Any]]) -> dict[str, Any]:
    contract_values: dict[str, set[str]] = defaultdict(set)
    telemetry_values: dict[str, set[str]] = defaultdict(set)
    opaque_counts: dict[str, int] = defaultdict(int)
    for receipt in receipts:
        headers = receipt.get("response", {}).get("captured_headers", {})
        if not isinstance(headers, Mapping):
            continue
        for key, value in headers.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            lowered = key.lower()
            if "request-id" in lowered or lowered == "request_id":
                opaque_counts[lowered] += 1
            elif "version" in lowered or "revision" in lowered:
                contract_values[lowered].add(value)
            else:
                telemetry_values[lowered].add(value)
    return {
        "contract_header_values": {
            key: sorted(items) for key, items in sorted(contract_values.items())
        },
        "contract_header_change_count": sum(
            max(0, len(items) - 1) for items in contract_values.values()
        ),
        "telemetry_header_values": {
            key: sorted(items) for key, items in sorted(telemetry_values.items())
        },
        "opaque_request_id_presence_count": dict(sorted(opaque_counts.items())),
        "request_id_values_retained": False,
        "provider_signed_identity": False,
    }


def _identity_summary(receipts: list[Mapping[str, Any]]) -> dict[str, Any]:
    by_adapter: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for receipt in receipts:
        identity = receipt.get("response", {}).get("identity", {})
        adapter = identity.get("adapter")
        if isinstance(adapter, str):
            by_adapter[adapter].append(identity)
    output: dict[str, Any] = {}
    for adapter, identities in sorted(by_adapter.items()):
        strengths = [identity.get("signal_strength") for identity in identities]
        output[adapter] = {
            "observations": len(identities),
            "signal_strength_counts": {
                "strong": strengths.count("strong"),
                "weak": strengths.count("weak"),
                "none": strengths.count("none"),
            },
            "binding_match_count": sum(
                1 for identity in identities if identity.get("model_binding_status") == "match"
            ),
            "binding_mismatch_count": sum(
                1 for identity in identities if identity.get("model_binding_status") == "mismatch"
            ),
            "binding_unavailable_count": sum(
                1
                for identity in identities
                if identity.get("model_binding_status") == "unavailable"
            ),
            "distinct_response_models": sorted(
                {
                    identity["response_model"]
                    for identity in identities
                    if isinstance(identity.get("response_model"), str)
                }
            ),
            "distinct_system_fingerprints": sorted(
                {
                    identity["system_fingerprint"]
                    for identity in identities
                    if isinstance(identity.get("system_fingerprint"), str)
                }
            ),
            "cross_adapter_drift_verdict": "prohibited",
        }
    return output


def _retention_summary(receipts: list[Mapping[str, Any]]) -> dict[str, Any]:
    by_condition: dict[str, list[bool]] = defaultdict(list)
    for receipt in receipts:
        if receipt.get("probe_kind") != "retention":
            continue
        match = receipt.get("response", {}).get("anchor_match")
        if isinstance(match, bool):
            by_condition[str(receipt.get("condition"))].append(match)
    return {
        condition: {
            "observations": len(values),
            "exact_anchor_match_count": sum(values),
            "exact_anchor_miss_count": len(values) - sum(values),
        }
        for condition, values in sorted(by_condition.items())
    }


def _context_summary(receipts: list[Mapping[str, Any]]) -> dict[str, Any]:
    by_condition: dict[str, list[str]] = defaultdict(list)
    for receipt in receipts:
        if receipt.get("probe_kind") != "context_sweep":
            continue
        by_condition[str(receipt.get("condition"))].append(str(receipt.get("status")))
    return {
        condition: {
            "observations": len(statuses),
            "status_counts": {status: statuses.count(status) for status in sorted(set(statuses))},
        }
        for condition, statuses in sorted(by_condition.items())
    }


def summarize_run(run_dir: Path, out_path: Path | None = None) -> dict[str, Any]:
    verification = verify_run(run_dir)
    snapshot = load_json(run_dir / "manifest.snapshot.json")
    receipts = read_jsonl(run_dir / "receipts.jsonl")
    summary = {
        "schema": SUMMARY_SCHEMA,
        "campaign_id": snapshot["campaign_id"],
        "manifest_sha256": receipts[0]["manifest_sha256"] if receipts else None,
        "api_contract_sha256": receipts[0]["api_contract_sha256"] if receipts else None,
        "usage_semantics_id": snapshot["subject"]["api_contract"]["usage_semantics_id"],
        "probe_suite_sha256": sha256_object(snapshot["probes"]),
        "provider": snapshot["subject"]["provider"],
        "adapter": snapshot["subject"]["adapter"],
        "resolved_model": snapshot["subject"]["resolved_model"],
        "receipt_count": len(receipts),
        "verification": verification,
        "cache_accounting": _cache_accounting(receipts),
        "cache_threshold": _cache_threshold(receipts),
        "api_contract_observations": _api_contract_observations(receipts),
        "latency": _paired_latency(receipts),
        "identity": _identity_summary(receipts),
        "retention": _retention_summary(receipts),
        "context_sweep": _context_summary(receipts),
        "measurement_boundary": {
            "provider_reported_usage": "measured_when_present",
            "response_model_binding": "measured_when_present",
            "system_fingerprint": "measured_when_present",
            "physical_kv_cache_bytes": "UNMEASURED",
            "kv_compression_or_quantization": "UNMEASURED",
            "eviction_policy": "UNMEASURED",
            "fleet_topology": "UNMEASURED",
            "provider_internal_cost_and_margin": "UNMEASURED",
        },
        "retention_audit": {
            "prompt_text_in_summary": False,
            "response_text_in_summary": False,
            "raw_evidence_location": "private-run-artifact",
        },
    }
    summary["summary_sha256"] = sha256_object(summary)
    if out_path is not None:
        write_json_atomic(out_path, summary)
    return summary


def _load_summaries(paths: Iterable[Path]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for path in paths:
        summary = load_json(path)
        if summary.get("schema") != SUMMARY_SCHEMA:
            raise ContractError(f"not a frontier summary: {path}")
        campaign_id = summary.get("campaign_id")
        if not isinstance(campaign_id, str) or campaign_id in result:
            raise ContractError(f"duplicate or invalid campaign id in summaries: {path}")
        result[campaign_id] = summary
    return result


def compare_summaries(
    matrix: Mapping[str, Any], summary_paths: Iterable[Path], out_path: Path | None = None
) -> dict[str, Any]:
    if matrix.get("schema") != COMPARISON_SCHEMA:
        raise ContractError(f"comparison matrix schema must be {COMPARISON_SCHEMA}")
    summaries = _load_summaries(summary_paths)
    pair_results: list[dict[str, Any]] = []
    for pair in matrix.get("pairs", []):
        if not isinstance(pair, Mapping):
            raise ContractError("comparison pair must be an object")
        left_id = pair.get("left_campaign_id")
        right_id = pair.get("right_campaign_id")
        if left_id not in summaries or right_id not in summaries:
            raise ContractError(f"missing summary for comparison pair {pair.get('id')}")
        left = summaries[left_id]
        right = summaries[right_id]
        required_equal = pair.get("required_equal", [])
        mismatches: list[dict[str, Any]] = []
        for field in required_equal:
            if left.get(field) != right.get(field):
                mismatches.append(
                    {"field": field, "left": left.get(field), "right": right.get(field)}
                )
        token_metrics_allowed = (
            left.get("usage_semantics_id") == right.get("usage_semantics_id")
            and left.get("api_contract_sha256") == right.get("api_contract_sha256")
        )
        pair_results.append(
            {
                "id": pair.get("id"),
                "left_campaign_id": left_id,
                "right_campaign_id": right_id,
                "matched_contract": not mismatches,
                "contract_mismatches": mismatches,
                "token_metric_comparison": (
                    "allowed" if token_metrics_allowed and not mismatches else "refused"
                ),
                "token_metric_refusal_reason": (
                    None
                    if token_metrics_allowed and not mismatches
                    else "API contract or usage semantics differ"
                ),
                "observed": {
                    "left_cache_accounting": left.get("cache_accounting"),
                    "right_cache_accounting": right.get("cache_accounting"),
                    "left_latency": left.get("latency"),
                    "right_latency": right.get("latency"),
                    "left_identity": left.get("identity"),
                    "right_identity": right.get("identity"),
                    "left_retention": left.get("retention"),
                    "right_retention": right.get("retention"),
                },
                "capability_ranking": "prohibited",
            }
        )
    comparison = {
        "schema": "tier-bench/frontier-fingerprint-comparison-receipt@1",
        "matrix_id": matrix.get("matrix_id"),
        "matrix_sha256": sha256_object(matrix),
        "pairs": pair_results,
    }
    comparison["comparison_sha256"] = sha256_object(comparison)
    if out_path is not None:
        write_json_atomic(out_path, comparison)
    return comparison
