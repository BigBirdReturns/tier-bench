"""Passive transcript accounting with structural-only, text-free output."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .canonical import canonical_json_bytes, sha256_bytes, sha256_object, write_json_atomic
from .contracts import PASSIVE_SCHEMA, ContractError

_ALLOWED_ADAPTERS = {"claude_code_jsonl", "codex_jsonl", "generic_provider_json"}
_COMPACTION_KEYS = {
    "compact_metadata",
    "compaction",
    "context_management",
    "context_window_compaction",
    "summary_boundary",
    "is_compact_summary",
    "compacted",
}


def _known_usage_objects(record: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    candidates: list[tuple[str, Any]] = [
        ("$.usage", record.get("usage")),
        ("$.message.usage", _at(record, "message", "usage")),
        ("$.response.usage", _at(record, "response", "usage")),
        ("$.event.usage", _at(record, "event", "usage")),
        ("$.data.usage", _at(record, "data", "usage")),
    ]
    return [(path, value) for path, value in candidates if isinstance(value, Mapping)]


def _at(record: Mapping[str, Any], *path: str) -> Any:
    value: Any = record
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _usage_from_object(usage: Mapping[str, Any]) -> dict[str, Any]:
    input_tokens = _int(usage.get("input_tokens"))
    if input_tokens is None:
        input_tokens = _int(usage.get("input_tokens_total"))
    cached = _int(usage.get("cache_read_input_tokens"))
    if cached is None:
        details = usage.get("input_tokens_details")
        if isinstance(details, Mapping):
            cached = _int(details.get("cached_tokens"))
    creation = _int(usage.get("cache_creation_input_tokens"))
    if creation is None:
        cache_creation = usage.get("cache_creation")
        if isinstance(cache_creation, Mapping):
            creation = sum(
                value
                for value in (
                    _int(cache_creation.get("ephemeral_5m_input_tokens")),
                    _int(cache_creation.get("ephemeral_1h_input_tokens")),
                )
                if value is not None
            )
    output_tokens = _int(usage.get("output_tokens"))
    total_tokens = _int(usage.get("total_tokens"))
    return {
        "input_tokens": input_tokens,
        "cache_read_input_tokens": cached,
        "cache_creation_input_tokens": creation,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _known_model(record: Mapping[str, Any]) -> tuple[str | None, str | None]:
    paths = [
        ("$.model", record.get("model")),
        ("$.message.model", _at(record, "message", "model")),
        ("$.response.model", _at(record, "response", "model")),
        ("$.event.model", _at(record, "event", "model")),
        ("$.data.model", _at(record, "data", "model")),
    ]
    for path, value in paths:
        if isinstance(value, str) and 0 < len(value) <= 200:
            return value, path
    return None, None


def _known_fingerprint(record: Mapping[str, Any]) -> tuple[str | None, str | None]:
    paths = [
        ("$.system_fingerprint", record.get("system_fingerprint")),
        ("$.response.system_fingerprint", _at(record, "response", "system_fingerprint")),
        ("$.message.system_fingerprint", _at(record, "message", "system_fingerprint")),
    ]
    for path, value in paths:
        if isinstance(value, str) and 0 < len(value) <= 200:
            return value, path
    return None, None


def _structural_markers(value: Any, prefix: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower()
            path = f"{prefix}.{key}"
            if normalized in _COMPACTION_KEYS:
                found.append(path)
            found.extend(_structural_markers(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_structural_markers(child, f"{prefix}[{index}]"))
    return found


def _parse_records(data: bytes) -> list[tuple[bytes, Mapping[str, Any]]]:
    stripped = data.lstrip()
    if not stripped:
        return []
    if stripped.startswith(b"["):
        parsed = json.loads(data)
        if not isinstance(parsed, list):
            raise ContractError("JSON array expected")
        result = []
        for item in parsed:
            if isinstance(item, Mapping):
                encoded = canonical_json_bytes(item)
                result.append((encoded, item))
        return result
    if stripped.startswith(b"{"):
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, Mapping):
            return [(canonical_json_bytes(parsed), parsed)]

    result: list[tuple[bytes, Mapping[str, Any]]] = []
    for line_number, raw in enumerate(data.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ContractError(f"invalid JSONL record at line {line_number}: {exc}") from exc
        if isinstance(item, Mapping):
            result.append((raw, item))
    return result


def observe_transcript(
    input_path: Path,
    *,
    adapter: str,
    abrupt_drop_fraction: float = 0.35,
    abrupt_drop_minimum_tokens: int = 256,
) -> dict[str, Any]:
    if adapter not in _ALLOWED_ADAPTERS:
        raise ContractError(f"unsupported passive adapter: {adapter}")
    if not 0 < abrupt_drop_fraction < 1:
        raise ContractError("abrupt_drop_fraction must be in (0, 1)")
    data = input_path.read_bytes()
    records = _parse_records(data)
    observations: list[dict[str, Any]] = []

    for index, (raw_record, record) in enumerate(records):
        usage_candidates = _known_usage_objects(record)
        usage_path: str | None = None
        usage: dict[str, Any] | None = None
        for candidate_path, candidate in usage_candidates:
            extracted = _usage_from_object(candidate)
            if any(value is not None for value in extracted.values()):
                usage_path = candidate_path
                usage = extracted
                break
        model, model_path = _known_model(record)
        fingerprint, fingerprint_path = _known_fingerprint(record)
        markers = sorted(set(_structural_markers(record)))
        if usage is None and model is None and fingerprint is None and not markers:
            continue
        observations.append(
            {
                "event_index": index,
                "source_record_sha256": sha256_bytes(raw_record),
                "usage": usage,
                "usage_source_path": usage_path,
                "model": model,
                "model_source_path": model_path,
                "system_fingerprint": fingerprint,
                "system_fingerprint_source_path": fingerprint_path,
                "structural_compaction_markers": markers,
            }
        )

    abrupt_candidates: list[dict[str, Any]] = []
    previous: tuple[int, int] | None = None
    for observation in observations:
        usage = observation.get("usage")
        current = usage.get("input_tokens") if isinstance(usage, Mapping) else None
        if not isinstance(current, int):
            continue
        if previous is not None:
            previous_index, previous_tokens = previous
            if previous_tokens >= abrupt_drop_minimum_tokens:
                drop_fraction = (previous_tokens - current) / previous_tokens
                if drop_fraction >= abrupt_drop_fraction:
                    abrupt_candidates.append(
                        {
                            "previous_event_index": previous_index,
                            "current_event_index": observation["event_index"],
                            "previous_input_tokens": previous_tokens,
                            "current_input_tokens": current,
                            "drop_fraction": round(drop_fraction, 6),
                            "classification": "numeric_context_drop_candidate",
                            "transcript_text_used": False,
                        }
                    )
        previous = (observation["event_index"], current)

    model_sequence = [
        observation["model"] for observation in observations if observation.get("model")
    ]
    fingerprint_sequence = [
        observation["system_fingerprint"]
        for observation in observations
        if observation.get("system_fingerprint")
    ]
    output = {
        "schema": PASSIVE_SCHEMA,
        "adapter": adapter,
        "source_file_sha256": sha256_bytes(data),
        "source_file_bytes": len(data),
        "source_path_retained": False,
        "record_count": len(records),
        "observation_count": len(observations),
        "observations": observations,
        "abrupt_context_drop_candidates": abrupt_candidates,
        "structural_compaction_marker_count": sum(
            len(observation["structural_compaction_markers"])
            for observation in observations
        ),
        "identity": {
            "distinct_models": sorted(set(model_sequence)),
            "model_change_count": sum(
                1 for left, right in zip(model_sequence, model_sequence[1:]) if left != right
            ),
            "distinct_system_fingerprints": sorted(set(fingerprint_sequence)),
            "system_fingerprint_change_count": sum(
                1
                for left, right in zip(fingerprint_sequence, fingerprint_sequence[1:])
                if left != right
            ),
        },
        "retention_audit": {
            "transcript_text_retained": False,
            "prompt_text_retained": False,
            "response_text_retained": False,
            "structural_keys_retained": True,
            "numeric_usage_retained": True,
        },
    }
    output["observation_sha256"] = sha256_object(output)
    return output


def observe_to_file(input_path: Path, output_path: Path, *, adapter: str) -> dict[str, Any]:
    output = observe_transcript(input_path, adapter=adapter)
    write_json_atomic(output_path, output)
    return output
