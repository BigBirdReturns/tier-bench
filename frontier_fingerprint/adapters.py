"""Provider request construction, transport, and response normalization."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping

from .canonical import canonical_json_bytes, sha256_bytes, sha256_object
from .contracts import ContractError, api_key_environment
from .probes import PromptMaterial


@dataclass(frozen=True)
class TransportResult:
    status_code: int
    response_headers: dict[str, str]
    body: bytes
    latency_ms: float
    transport_error: str | None = None


@dataclass(frozen=True)
class NormalizedResponse:
    usage: dict[str, Any]
    usage_source_paths: dict[str, str | None]
    identity: dict[str, Any]
    output_text: str
    stop_reason: str | None
    error_type: str | None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _nested(mapping: Mapping[str, Any], *keys: str) -> Any:
    value: Any = mapping
    for key in keys:
        if not isinstance(value, Mapping) or key not in value:
            return None
        value = value[key]
    return value


def _identity(
    *,
    requested_model: str,
    response_model: str | None,
    system_fingerprint: str | None,
    response_id: str | None,
    adapter: str,
) -> dict[str, Any]:
    if system_fingerprint:
        signal = "strong_backend_fingerprint"
        strength = "strong"
    elif response_model:
        signal = "weak_response_model_only"
        strength = "weak"
    else:
        signal = "no_response_identity"
        strength = "none"

    if response_model is None:
        binding_status = "unavailable"
    elif response_model == requested_model:
        binding_status = "match"
    else:
        binding_status = "mismatch"

    return {
        "adapter": adapter,
        "requested_model": requested_model,
        "response_model": response_model,
        "response_id_sha256": (
            sha256_bytes(response_id.encode("utf-8")) if response_id else None
        ),
        "system_fingerprint": system_fingerprint,
        "signal": signal,
        "signal_strength": strength,
        "model_binding_status": binding_status,
    }


def normalize_anthropic(
    body: Mapping[str, Any], requested_model: str
) -> NormalizedResponse:
    usage_raw = body.get("usage") if isinstance(body.get("usage"), Mapping) else {}
    cache_creation = _integer(usage_raw.get("cache_creation_input_tokens"))
    if cache_creation is None:
        cache_creation = _integer(
            _nested(usage_raw, "cache_creation", "ephemeral_5m_input_tokens")
        )
        one_hour = _integer(
            _nested(usage_raw, "cache_creation", "ephemeral_1h_input_tokens")
        )
        if cache_creation is not None or one_hour is not None:
            cache_creation = (cache_creation or 0) + (one_hour or 0)
    usage = {
        "provider_input_tokens": _integer(usage_raw.get("input_tokens")),
        "cache_creation_input_tokens": cache_creation,
        "cache_read_input_tokens": _integer(usage_raw.get("cache_read_input_tokens")),
        "output_tokens": _integer(usage_raw.get("output_tokens")),
        "total_tokens": None,
    }
    components = [
        usage["provider_input_tokens"],
        usage["cache_creation_input_tokens"],
        usage["cache_read_input_tokens"],
        usage["output_tokens"],
    ]
    if any(value is not None for value in components):
        usage["total_tokens"] = sum(value or 0 for value in components)

    blocks = body.get("content") if isinstance(body.get("content"), list) else []
    output_parts = [
        block.get("text", "")
        for block in blocks
        if isinstance(block, Mapping)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
    ]
    response_model = body.get("model") if isinstance(body.get("model"), str) else None
    response_id = body.get("id") if isinstance(body.get("id"), str) else None
    return NormalizedResponse(
        usage=usage,
        usage_source_paths={
            "provider_input_tokens": "$.usage.input_tokens",
            "cache_creation_input_tokens": "$.usage.cache_creation_input_tokens|$.usage.cache_creation.*",
            "cache_read_input_tokens": "$.usage.cache_read_input_tokens",
            "output_tokens": "$.usage.output_tokens",
        },
        identity=_identity(
            requested_model=requested_model,
            response_model=response_model,
            system_fingerprint=None,
            response_id=response_id,
            adapter="anthropic_messages",
        ),
        output_text="".join(output_parts),
        stop_reason=body.get("stop_reason") if isinstance(body.get("stop_reason"), str) else None,
        error_type=_nested(body, "error", "type")
        if isinstance(_nested(body, "error", "type"), str)
        else None,
    )


def _openai_output_text(body: Mapping[str, Any]) -> str:
    direct = body.get("output_text")
    if isinstance(direct, str):
        return direct
    parts: list[str] = []
    output = body.get("output") if isinstance(body.get("output"), list) else []
    for item in output:
        if not isinstance(item, Mapping):
            continue
        content = item.get("content") if isinstance(item.get("content"), list) else []
        for block in content:
            if not isinstance(block, Mapping):
                continue
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def normalize_openai(
    body: Mapping[str, Any], requested_model: str
) -> NormalizedResponse:
    usage_raw = body.get("usage") if isinstance(body.get("usage"), Mapping) else {}
    usage = {
        "provider_input_tokens": _integer(usage_raw.get("input_tokens")),
        "cache_creation_input_tokens": None,
        "cache_read_input_tokens": _integer(
            _nested(usage_raw, "input_tokens_details", "cached_tokens")
        ),
        "output_tokens": _integer(usage_raw.get("output_tokens")),
        "total_tokens": _integer(usage_raw.get("total_tokens")),
    }
    response_model = body.get("model") if isinstance(body.get("model"), str) else None
    response_id = body.get("id") if isinstance(body.get("id"), str) else None
    fingerprint = (
        body.get("system_fingerprint")
        if isinstance(body.get("system_fingerprint"), str)
        else None
    )
    return NormalizedResponse(
        usage=usage,
        usage_source_paths={
            "provider_input_tokens": "$.usage.input_tokens",
            "cache_creation_input_tokens": None,
            "cache_read_input_tokens": "$.usage.input_tokens_details.cached_tokens",
            "output_tokens": "$.usage.output_tokens",
        },
        identity=_identity(
            requested_model=requested_model,
            response_model=response_model,
            system_fingerprint=fingerprint,
            response_id=response_id,
            adapter="openai_responses",
        ),
        output_text=_openai_output_text(body),
        stop_reason=(
            body.get("status") if isinstance(body.get("status"), str) else None
        ),
        error_type=_nested(body, "error", "type")
        if isinstance(_nested(body, "error", "type"), str)
        else None,
    )


def normalize_mock(body: Mapping[str, Any], requested_model: str) -> NormalizedResponse:
    usage_raw = body.get("usage") if isinstance(body.get("usage"), Mapping) else {}
    usage = {
        "provider_input_tokens": _integer(usage_raw.get("input_tokens")),
        "cache_creation_input_tokens": _integer(
            usage_raw.get("cache_creation_input_tokens")
        ),
        "cache_read_input_tokens": _integer(usage_raw.get("cache_read_input_tokens")),
        "output_tokens": _integer(usage_raw.get("output_tokens")),
        "total_tokens": _integer(usage_raw.get("total_tokens")),
    }
    return NormalizedResponse(
        usage=usage,
        usage_source_paths={
            "provider_input_tokens": "$.usage.input_tokens",
            "cache_creation_input_tokens": "$.usage.cache_creation_input_tokens",
            "cache_read_input_tokens": "$.usage.cache_read_input_tokens",
            "output_tokens": "$.usage.output_tokens",
        },
        identity=_identity(
            requested_model=requested_model,
            response_model=body.get("model") if isinstance(body.get("model"), str) else None,
            system_fingerprint=(
                body.get("system_fingerprint")
                if isinstance(body.get("system_fingerprint"), str)
                else None
            ),
            response_id=body.get("id") if isinstance(body.get("id"), str) else None,
            adapter="mock",
        ),
        output_text=body.get("output_text") if isinstance(body.get("output_text"), str) else "",
        stop_reason=body.get("stop_reason") if isinstance(body.get("stop_reason"), str) else None,
        error_type=None,
    )


def normalize_response(
    adapter: str, body: Mapping[str, Any], requested_model: str
) -> NormalizedResponse:
    if adapter == "anthropic_messages":
        return normalize_anthropic(body, requested_model)
    if adapter == "openai_responses":
        return normalize_openai(body, requested_model)
    if adapter == "mock":
        return normalize_mock(body, requested_model)
    raise ContractError(f"unsupported adapter: {adapter}")


def _anthropic_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(tool) for tool in tools]


def _openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for tool in tools:
        converted.append(
            {
                "type": "function",
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
                "strict": True,
            }
        )
    return converted


def build_request_body(
    *,
    manifest: Mapping[str, Any],
    spec: Mapping[str, Any],
    prompt: PromptMaterial,
    model: str,
) -> dict[str, Any]:
    adapter = manifest["subject"]["adapter"]
    max_tokens = next(
        int(probe.get("max_output_tokens", 64))
        for probe in manifest["probes"]
        if probe["id"] == spec["probe_id"]
    )

    if adapter == "anthropic_messages":
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": prompt.system_text,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt.prefix_text,
                            "cache_control": {"type": "ephemeral"},
                        },
                        {"type": "text", "text": prompt.suffix_text},
                    ],
                }
            ],
        }
        if prompt.tools:
            body["tools"] = _anthropic_tools(prompt.tools)
        if prompt.effort:
            body["effort"] = prompt.effort
        return body

    if adapter == "openai_responses":
        body = {
            "model": model,
            "instructions": prompt.system_text,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": prompt.prefix_text + "\n" + prompt.suffix_text,
                        }
                    ],
                }
            ],
            "max_output_tokens": max_tokens,
            "store": False,
            "prompt_cache_key": prompt.cache_key,
        }
        if prompt.tools:
            body["tools"] = _openai_tools(prompt.tools)
        if prompt.effort:
            body["reasoning"] = {"effort": prompt.effort}
        return body

    if adapter == "mock":
        return {
            "model": model,
            "system": prompt.system_text,
            "prefix": prompt.prefix_text,
            "suffix": prompt.suffix_text,
            "tools": prompt.tools,
            "effort": prompt.effort,
            "cache_key": prompt.cache_key,
            "probe_meta": {
                "observation_id": spec["observation_id"],
                "probe_kind": spec["probe_kind"],
                "condition": spec["condition"],
                "block": spec["block"],
                "expected_anchor": prompt.expected_anchor,
                "prefix_units": spec["parameters"].get("prefix_units", 0),
            },
        }

    raise ContractError(f"unsupported adapter: {adapter}")


class HTTPAdapter:
    """Raw HTTP adapter with no automatic retry and no secret retention."""

    def __init__(self, manifest: Mapping[str, Any], environ: Mapping[str, str] | None = None):
        self.manifest = manifest
        self.environ = os.environ if environ is None else environ

    def execute(self, request_body: bytes) -> TransportResult:
        subject = self.manifest["subject"]
        adapter = subject["adapter"]
        api_contract = subject["api_contract"]
        key_env = api_key_environment(adapter)
        api_key = self.environ.get(key_env, "")
        if not api_key:
            raise ContractError(f"missing provider credential environment variable: {key_env}")

        headers = {"content-type": "application/json", "user-agent": "tier-bench-frontier-fingerprint/0.1"}
        headers.update({str(k): str(v) for k, v in api_contract["request_headers"].items()})
        if adapter == "anthropic_messages":
            headers["x-api-key"] = api_key
        elif adapter == "openai_responses":
            headers["authorization"] = f"Bearer {api_key}"

        request = urllib.request.Request(
            api_contract["endpoint"],
            data=request_body,
            headers=headers,
            method="POST",
        )
        started = time.perf_counter()
        timeout = int(self.manifest["execution"].get("request_timeout_seconds", 120))
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
                status = int(response.status)
                response_headers = {key.lower(): value for key, value in response.headers.items()}
                error = None
        except urllib.error.HTTPError as exc:
            body = exc.read()
            status = int(exc.code)
            response_headers = {key.lower(): value for key, value in exc.headers.items()}
            error = f"HTTPError:{exc.code}"
        except urllib.error.URLError as exc:
            body = canonical_json_bytes({"transport_error": str(exc.reason)})
            status = 0
            response_headers = {}
            error = f"URLError:{type(exc.reason).__name__}"
        latency_ms = (time.perf_counter() - started) * 1000.0
        return TransportResult(status, response_headers, body, latency_ms, error)


class MockAdapter:
    """Deterministic provider-free adapter used only for conformance tests."""

    def __init__(self, *, identity_mismatch: bool = False):
        self.cached_prefixes: set[str] = set()
        self.identity_mismatch = identity_mismatch
        self.counter = 0

    def execute(self, request_body: bytes) -> TransportResult:
        started = time.perf_counter()
        request = json.loads(request_body)
        self.counter += 1
        meta = request["probe_meta"]
        model = request["model"]
        response_model = f"{model}-aliased" if self.identity_mismatch else model
        cache_key = request["cache_key"]
        prefix_hash = sha256_bytes(request["prefix"].encode("utf-8"))
        cache_identity = f"{cache_key}:{prefix_hash}"
        prefix_units = int(meta.get("prefix_units", 0))
        condition = meta.get("condition")

        is_prime = condition == "prime" or (isinstance(condition, str) and condition.endswith("-prime"))
        is_warm = condition == "warm" or (isinstance(condition, str) and condition.endswith("-warm"))
        if is_prime:
            cache_creation = prefix_units
            cache_read = 0
            self.cached_prefixes.add(cache_identity)
        elif is_warm and cache_identity in self.cached_prefixes:
            cache_creation = 0
            cache_read = prefix_units
        else:
            cache_creation = prefix_units if prefix_units else 0
            cache_read = 0
            self.cached_prefixes.add(cache_identity)

        expected_anchor = meta.get("expected_anchor")
        output_text = (
            json.dumps({"anchor": expected_anchor}, separators=(",", ":"))
            if expected_anchor
            else ("READY" if meta.get("probe_kind") == "identity" else "ACK")
        )
        input_tokens = max(1, prefix_units // 2 + len(request.get("suffix", "").split()))
        output_tokens = max(1, len(output_text.split()))
        body = canonical_json_bytes(
            {
                "id": f"mock-response-{self.counter}",
                "model": response_model,
                "system_fingerprint": "mock-backend-2026-09",
                "output_text": output_text,
                "stop_reason": "end_turn",
                "usage": {
                    "input_tokens": input_tokens,
                    "cache_creation_input_tokens": cache_creation,
                    "cache_read_input_tokens": cache_read,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                },
            }
        )
        elapsed = (time.perf_counter() - started) * 1000.0
        synthetic_latency = 4.0 + (0.5 if cache_read else 2.0) + (self.counter % 3) * 0.1
        return TransportResult(
            200,
            {"x-mock-contract": "mock-v1", "x-request-id": f"req-{self.counter}"},
            body,
            max(elapsed, synthetic_latency),
            None,
        )


def selected_response_headers(
    manifest: Mapping[str, Any], headers: Mapping[str, str]
) -> dict[str, str]:
    """Capture only preregistered headers and hash opaque request identifiers.

    Request identifiers can support provider-side support investigations, but they
    are linkable transport metadata rather than API-contract evidence. Public
    receipts retain only their SHA-256 digests.
    """

    allowed = {
        item.lower()
        for item in manifest["subject"]["api_contract"]["response_headers_to_capture"]
    }
    captured: dict[str, str] = {}
    for key, value in headers.items():
        normalized = key.lower()
        if normalized not in allowed:
            continue
        if "request-id" in normalized or normalized == "request_id":
            captured[normalized] = "sha256:" + sha256_bytes(value.encode("utf-8"))
        else:
            captured[normalized] = value
    return captured


def request_contract_descriptor(
    manifest: Mapping[str, Any], request_body: bytes
) -> dict[str, Any]:
    parsed = json.loads(request_body)
    return {
        "body_sha256": sha256_bytes(request_body),
        "body_bytes": len(request_body),
        "model": parsed.get("model"),
        "api_contract_sha256": sha256_object(
            {
                "adapter": manifest["subject"]["adapter"],
                "provider": manifest["subject"]["provider"],
                "api_contract": manifest["subject"]["api_contract"],
            }
        ),
    }
