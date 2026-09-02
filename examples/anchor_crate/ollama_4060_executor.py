#!/usr/bin/env python3
"""Physical Ollama/CUDA executor for the Anchor Crate command ABI.

The process is a bounded execution supplier. It may emit a candidate decision packet and
measured runtime telemetry. It never owns canonical hashes, the durable anchor, hidden
validators, acceptance, promotion, or production claims.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Mapping, Sequence
import urllib.error
import urllib.parse
import urllib.request

REQUEST_SCHEMA = "tier-bench/anchor-executor-request@1"
RESPONSE_SCHEMA = "tier-bench/anchor-executor-response@1"
BINDING_SCHEMA = "tier-bench/anchor-ollama-cuda-binding@1"

DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "asset_id",
        "claim",
        "blockers",
        "evidence_record_ids",
        "summary",
        "requires_human_review",
    ],
    "properties": {
        "asset_id": {"type": "string"},
        "claim": {
            "type": "string",
            "enum": ["physically_available", "not_physically_available"],
        },
        "blockers": {"type": "array", "items": {"type": "string"}},
        "evidence_record_ids": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "requires_human_review": {"type": "boolean"},
    },
}


class ExecutorError(RuntimeError):
    """The physical backend failed a bounded precondition or invocation."""


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def hash_json(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutorError(f"cannot read binding {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ExecutorError("binding root must be an object")
    return value


def require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExecutorError(f"{label} must be a non-empty string")
    return value.strip()


def require_int(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ExecutorError(f"{label} must be an integer >= {minimum}")
    return value


def assert_loopback_endpoint(endpoint: str) -> None:
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme != "http" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ExecutorError("Ollama endpoint must be a plain loopback HTTP origin")
    host = parsed.hostname
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ExecutorError("Ollama endpoint must remain loopback-only")
    if parsed.path not in {"", "/"}:
        raise ExecutorError("Ollama endpoint must not contain a path")


def http_json(
    endpoint: str,
    path: str,
    *,
    timeout: float,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    url = endpoint.rstrip("/") + path
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        raise ExecutorError(f"Ollama request failed for {path}: {exc}") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecutorError(f"Ollama returned invalid JSON for {path}") from exc
    if not isinstance(value, dict):
        raise ExecutorError(f"Ollama response for {path} must be an object")
    return value


def find_model(rows: Any, model: str, digest: str) -> dict[str, Any] | None:
    if not isinstance(rows, list):
        return None
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        identity = raw.get("name") or raw.get("model")
        if identity == model and raw.get("digest") == digest:
            return dict(raw)
    return None


def parse_csv_number(value: str) -> float | None:
    value = value.strip()
    if not value or value.lower() in {"n/a", "[n/a]", "not supported"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def query_gpu(binding: Mapping[str, Any]) -> dict[str, Any]:
    execution = binding["execution"]
    gpu = binding["gpu"]
    prefix = execution.get("nvidia_smi_command")
    if prefix is None:
        prefix = [require_text(execution.get("nvidia_smi_path"), "execution.nvidia_smi_path")]
    if not isinstance(prefix, list) or not prefix or not all(isinstance(item, str) and item for item in prefix):
        raise ExecutorError("execution.nvidia_smi_command must be a non-empty string array")
    command = [
        *prefix,
        "-i",
        require_text(gpu.get("uuid"), "gpu.uuid"),
        "--query-gpu=uuid,name,memory.total,memory.used,driver_version,pci.bus_id,pstate,power.limit,power.draw,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            shell=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ExecutorError(f"nvidia-smi query failed: {exc}") from exc
    if completed.returncode != 0:
        diagnostic = completed.stderr.decode("utf-8", errors="replace")[:500]
        raise ExecutorError(f"nvidia-smi exited {completed.returncode}: {diagnostic}")
    lines = completed.stdout.decode("utf-8", errors="replace").strip().splitlines()
    if len(lines) != 1:
        raise ExecutorError(f"expected one GPU row for bound UUID, received {len(lines)}")
    parts = [part.strip() for part in lines[0].split(",")]
    if len(parts) < 10:
        raise ExecutorError("nvidia-smi GPU row is incomplete")
    row = {
        "captured_monotonic_ns": time.monotonic_ns(),
        "uuid": parts[0],
        "name": parts[1],
        "memory_total_mib": parse_csv_number(parts[2]),
        "memory_used_mib": parse_csv_number(parts[3]),
        "driver_version": parts[4],
        "pci_bus_id": parts[5],
        "pstate": parts[6],
        "power_limit_watts": parse_csv_number(parts[7]),
        "power_draw_watts": parse_csv_number(parts[8]),
        "utilization_percent": parse_csv_number(parts[9]),
    }
    expected = binding["gpu"]
    for key in ("uuid", "name", "driver_version", "pci_bus_id"):
        if str(row.get(key)) != str(expected.get(key)):
            raise ExecutorError(f"bound GPU {key} changed: expected {expected.get(key)!r}, got {row.get(key)!r}")
    expected_memory = int(expected["memory_total_mib"])
    observed_memory = row["memory_total_mib"]
    if observed_memory is None or int(round(observed_memory)) != expected_memory:
        raise ExecutorError("bound GPU memory envelope changed")
    return row


class GpuSampler:
    def __init__(self, binding: Mapping[str, Any], interval_s: float = 0.10) -> None:
        self.binding = binding
        self.interval_s = interval_s
        self.samples: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.samples.append(query_gpu(self.binding))
            except ExecutorError as exc:
                self.errors.append(str(exc))
            self._stop.wait(self.interval_s)

    def __enter__(self) -> "GpuSampler":
        self._thread = threading.Thread(target=self._run, name="anchor-gpu-sampler", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        try:
            self.samples.append(query_gpu(self.binding))
        except ExecutorError as query_exc:
            self.errors.append(str(query_exc))

    def metrics(self) -> dict[str, Any]:
        if not self.samples:
            raise ExecutorError("GPU telemetry produced no samples")
        power_rows = [
            row for row in self.samples if isinstance(row.get("power_draw_watts"), (int, float))
        ]
        energy_wh = 0.0
        for left, right in zip(power_rows, power_rows[1:]):
            elapsed_s = max(
                0.0,
                (right["captured_monotonic_ns"] - left["captured_monotonic_ns"]) / 1_000_000_000,
            )
            energy_wh += (
                (float(left["power_draw_watts"]) + float(right["power_draw_watts"]))
                / 2.0
                * elapsed_s
                / 3600.0
            )
        memory = [
            float(row["memory_used_mib"])
            for row in self.samples
            if isinstance(row.get("memory_used_mib"), (int, float))
        ]
        return {
            "sample_count": len(self.samples),
            "memory_peak_mib": int(math.ceil(max(memory))) if memory else 0,
            "energy_mwh": max(0, int(round(energy_wh * 1000.0))),
            "samples": self.samples,
            "errors": self.errors,
        }


def validate_binding(raw: Mapping[str, Any], *, backend_id: str, expected_digest: str) -> dict[str, Any]:
    if raw.get("schema") != BINDING_SCHEMA:
        raise ExecutorError(f"binding.schema must be {BINDING_SCHEMA}")
    if raw.get("backend_id") != backend_id:
        raise ExecutorError("binding backend identity mismatch")
    if hash_json(raw) != expected_digest:
        raise ExecutorError("binding content hash mismatch")
    if raw.get("physical_qualification") is not True:
        raise ExecutorError("physical executor requires an admitted physical binding")
    if raw.get("production_claim") is not False or raw.get("promotion_authorized") is not False:
        raise ExecutorError("physical binding may not claim production or promotion")
    runtime = raw.get("runtime")
    gpu = raw.get("gpu")
    execution = raw.get("execution")
    if not isinstance(runtime, Mapping) or not isinstance(gpu, Mapping) or not isinstance(execution, Mapping):
        raise ExecutorError("binding requires runtime, GPU, and execution objects")
    endpoint = require_text(runtime.get("endpoint"), "runtime.endpoint")
    assert_loopback_endpoint(endpoint)
    require_text(runtime.get("model"), "runtime.model")
    require_text(runtime.get("model_digest"), "runtime.model_digest")
    require_int(runtime.get("min_size_vram_bytes"), "runtime.min_size_vram_bytes", minimum=1)
    require_int(gpu.get("memory_total_mib"), "gpu.memory_total_mib", minimum=2048)
    return dict(raw)


def inspect_runtime(binding: Mapping[str, Any], *, require_loaded: bool) -> dict[str, Any]:
    runtime = binding["runtime"]
    endpoint = runtime["endpoint"]
    timeout = float(runtime.get("probe_timeout_seconds", 10))
    version = http_json(endpoint, "/api/version", timeout=timeout)
    tags = http_json(endpoint, "/api/tags", timeout=timeout)
    model = runtime["model"]
    digest = runtime["model_digest"]
    tag = find_model(tags.get("models"), model, digest)
    if tag is None:
        raise ExecutorError("exact bound model and digest are not present in Ollama catalog")
    running = http_json(endpoint, "/api/ps", timeout=timeout)
    loaded = find_model(running.get("models"), model, digest)
    if require_loaded and loaded is None:
        raise ExecutorError("exact bound model is not resident in Ollama")
    if loaded is not None:
        size_vram = loaded.get("size_vram")
        if not isinstance(size_vram, int) or size_vram < int(runtime["min_size_vram_bytes"]):
            raise ExecutorError("Ollama reports insufficient accelerator residency for the bound model")
    gpu = query_gpu(binding)
    if require_loaded:
        used = gpu.get("memory_used_mib")
        minimum_used = int(binding["gpu"].get("min_loaded_memory_mib", 1024))
        if not isinstance(used, (int, float)) or used < minimum_used:
            raise ExecutorError("bound GPU memory use is below the admitted loaded-model floor")
    return {
        "ollama_version": version.get("version"),
        "catalog_model": tag,
        "loaded_model": loaded,
        "gpu": gpu,
    }


def validate_candidate(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ExecutorError("model candidate must be a JSON object")
    required = set(DECISION_SCHEMA["required"])
    if set(value) != required:
        raise ExecutorError("model candidate fields differ from the bounded decision schema")
    if not isinstance(value["asset_id"], str) or not value["asset_id"].strip():
        raise ExecutorError("candidate asset_id is invalid")
    if value["claim"] not in {"physically_available", "not_physically_available"}:
        raise ExecutorError("candidate claim is invalid")
    if not isinstance(value["blockers"], list) or not all(isinstance(x, str) for x in value["blockers"]):
        raise ExecutorError("candidate blockers are invalid")
    if not isinstance(value["evidence_record_ids"], list) or not all(
        isinstance(x, str) for x in value["evidence_record_ids"]
    ):
        raise ExecutorError("candidate evidence record identities are invalid")
    if not isinstance(value["summary"], str) or not value["summary"].strip():
        raise ExecutorError("candidate summary is empty")
    if value["requires_human_review"] is not True:
        raise ExecutorError("candidate attempted to bypass human review")
    return value


def decision_prompt(state: Mapping[str, Any]) -> str:
    return (
        "You are a bounded decision-packet formatter. Use only the supplied readiness state. "
        "Copy asset_id, blockers, and evidence_record_ids exactly. Set claim to "
        "physically_available only when physically_available is true; otherwise use "
        "not_physically_available. Write one concise summary. requires_human_review must be true. "
        "Return only the JSON object required by the supplied schema.\n\n"
        "READINESS_STATE="
        + json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )


def append_evidence(binding: Mapping[str, Any], event: Mapping[str, Any]) -> str | None:
    raw = binding["execution"].get("evidence_log")
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(canonical_bytes(dict(event)))
    return sha256_bytes(path.read_bytes())


def execute_candidate(binding: Mapping[str, Any], inputs: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    state = inputs.get("node:derive_availability")
    if not isinstance(state, Mapping):
        raise ExecutorError("decision.generate requires node:derive_availability")
    runtime = binding["runtime"]
    endpoint = runtime["endpoint"]
    request = {
        "model": runtime["model"],
        "prompt": decision_prompt(state),
        "stream": False,
        "format": DECISION_SCHEMA,
        "keep_alive": runtime.get("keep_alive", "10m"),
        "options": {
            "temperature": 0,
            "seed": 0,
            "num_ctx": int(runtime.get("context_length", 8192)),
        },
    }
    started = time.monotonic_ns()
    with GpuSampler(binding) as sampler:
        provider = http_json(
            endpoint,
            "/api/generate",
            timeout=float(runtime.get("inference_timeout_seconds", 180)),
            payload=request,
        )
    elapsed_ms = max(1, int((time.monotonic_ns() - started) / 1_000_000))
    text = provider.get("response")
    if not isinstance(text, str) or not text.strip():
        raise ExecutorError("Ollama returned no candidate text")
    try:
        candidate = validate_candidate(json.loads(text))
    except json.JSONDecodeError as exc:
        raise ExecutorError("Ollama candidate is not valid JSON") from exc
    runtime_state = inspect_runtime(binding, require_loaded=True)
    metrics = sampler.metrics()
    evidence_event = {
        "schema": "tier-bench/anchor-physical-executor-event@1",
        "request_sha256": hash_json(request),
        "provider": {
            "model": provider.get("model"),
            "done": provider.get("done"),
            "done_reason": provider.get("done_reason"),
            "prompt_eval_count": provider.get("prompt_eval_count"),
            "eval_count": provider.get("eval_count"),
            "total_duration_ns": provider.get("total_duration"),
            "load_duration_ns": provider.get("load_duration"),
            "prompt_eval_duration_ns": provider.get("prompt_eval_duration"),
            "eval_duration_ns": provider.get("eval_duration"),
        },
        "runtime_state": runtime_state,
        "gpu_samples": metrics["samples"],
        "sampler_errors": metrics["errors"],
        "candidate_sha256": hash_json(candidate),
    }
    evidence_sha256 = append_evidence(binding, evidence_event)
    return candidate, {
        "status": "ok",
        "elapsed_ms": elapsed_ms,
        "memory_peak_mib": metrics["memory_peak_mib"],
        "energy_mwh": metrics["energy_mwh"],
        "evidence_log_sha256": evidence_sha256,
    }


def response(
    *,
    request_id: str,
    backend_id: str,
    status: str,
    output: Any,
    telemetry: Mapping[str, Any] | None = None,
    advisory: Sequence[str] = (),
) -> dict[str, Any]:
    base = dict(telemetry or {})
    return {
        "schema": RESPONSE_SCHEMA,
        "request_id": request_id,
        "backend_id": backend_id,
        "status": status,
        "output": output,
        "telemetry": {
            "status": str(base.get("status", status)),
            "elapsed_ms": int(base.get("elapsed_ms", 0)),
            "memory_peak_mib": int(base.get("memory_peak_mib", 0)),
            "energy_mwh": int(base.get("energy_mwh", 0)),
        },
        "advisory": list(advisory),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--expected-binding-sha256", required=True)
    args = parser.parse_args(argv)

    try:
        binding = validate_binding(
            load_json(args.binding),
            backend_id=args.backend,
            expected_digest=args.expected_binding_sha256,
        )
        request = json.load(sys.stdin)
        if not isinstance(request, dict) or request.get("schema") != REQUEST_SCHEMA:
            raise ExecutorError("invalid request schema")
        if request.get("backend_id") != args.backend:
            raise ExecutorError("request backend identity mismatch")
        request_id = require_text(request.get("request_id"), "request_id")
        operation = require_text(request.get("operation"), "operation")
        payload = request.get("payload")
        if not isinstance(payload, Mapping):
            raise ExecutorError("request payload must be an object")

        if operation == "describe":
            output = {
                "backend_id": args.backend,
                "protocol": RESPONSE_SCHEMA,
                "binding_sha256": args.expected_binding_sha256,
                "model": binding["runtime"]["model"],
                "model_digest": binding["runtime"]["model_digest"],
                "gpu_uuid": binding["gpu"]["uuid"],
                "capabilities": binding["capabilities"],
            }
            result = response(
                request_id=request_id,
                backend_id=args.backend,
                status="ok",
                output=output,
            )
        elif operation == "probe":
            state = inspect_runtime(binding, require_loaded=True)
            required = payload.get("required_capabilities", [])
            if not isinstance(required, list) or not all(isinstance(x, str) for x in required):
                raise ExecutorError("probe required_capabilities must be a string array")
            missing = sorted(set(required) - set(binding["capabilities"]))
            if missing:
                raise ExecutorError(f"backend lacks required capabilities: {missing}")
            result = response(
                request_id=request_id,
                backend_id=args.backend,
                status="ok",
                output={
                    "backend_id": args.backend,
                    "capabilities": binding["capabilities"],
                    "binding_sha256": args.expected_binding_sha256,
                    "runtime_state": state,
                },
                telemetry={
                    "status": "ok",
                    "elapsed_ms": 0,
                    "memory_peak_mib": int(state["gpu"].get("memory_used_mib") or 0),
                    "energy_mwh": 0,
                },
            )
        elif operation == "execute":
            crate = payload.get("crate")
            inputs = payload.get("inputs")
            if not isinstance(crate, Mapping) or not isinstance(inputs, Mapping):
                raise ExecutorError("execute requires crate and inputs objects")
            if crate.get("operation") != "decision.generate":
                raise ExecutorError("physical 4060 backend supports only decision.generate")
            candidate, telemetry = execute_candidate(binding, inputs)
            advisory = []
            if telemetry.pop("evidence_log_sha256", None):
                advisory.append("physical executor evidence appended to the binding-declared log")
            result = response(
                request_id=request_id,
                backend_id=args.backend,
                status="ok",
                output=candidate,
                telemetry=telemetry,
                advisory=advisory,
            )
        elif operation in {"collect", "cancel"}:
            result = response(
                request_id=request_id,
                backend_id=args.backend,
                status="ok",
                output={"state": "no_async_work"},
            )
        else:
            raise ExecutorError(f"unsupported driver operation: {operation}")
    except (ExecutorError, OSError, ValueError, json.JSONDecodeError) as exc:
        request_id = "unknown"
        try:
            if isinstance(locals().get("request"), dict):
                request_id = str(locals()["request"].get("request_id") or "unknown")
        except Exception:
            pass
        result = response(
            request_id=request_id,
            backend_id=args.backend,
            status="error",
            output=None,
            telemetry={"status": "error", "elapsed_ms": 0, "memory_peak_mib": 0, "energy_mwh": 0},
            advisory=[str(exc)],
        )
        json.dump(result, sys.stdout, sort_keys=True, separators=(",", ":"))
        sys.stdout.write("\n")
        return 2

    json.dump(result, sys.stdout, sort_keys=True, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
