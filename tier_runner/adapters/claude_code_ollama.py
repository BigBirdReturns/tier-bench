from __future__ import annotations

"""Fail-closed Claude Code adapter for a dedicated loopback Ollama server.

This adapter deliberately mirrors the existing Claude Code packet boundary while
changing only the provider surface.  The Ollama server is expected to have been
started separately with a machine attestation that binds its loopback endpoint,
GPU UUID, context policy, executable, and process identity.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener
import uuid


SCHEMA = "tier-bench/tier-backend-result@1"
SERVER_ATTESTATION_SCHEMA = "tier-bench/ollama-server-attestation@1"
ADAPTER_VERSION = "1"
CLAUDE_TOOLS = "Read,Edit,Write,Glob,Grep"
EMPTY_MCP_CONFIG = '{"mcpServers":{}}'
MAX_API_RESPONSE_BYTES = 16 * 1024 * 1024
REQUIRED_CLAUDE_FLAGS = {
    "--add-dir",
    "--allowedTools",
    "--disable-slash-commands",
    "--effort",
    "--mcp-config",
    "--no-chrome",
    "--no-session-persistence",
    "--permission-mode",
    "--safe-mode",
    "--strict-mcp-config",
    "--tools",
}

# No subscription, API, cloud-provider, or inherited session identity is allowed
# to reach a local coding flight.  PATH/SystemRoot and other process essentials
# remain available to the Claude Code executable itself.
BLOCKED_ENV_KEYS = {
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_CUSTOM_HEADERS",
    "CLAUDECODE",
    "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_USE_VERTEX",
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_WORK_TREE",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "OLDPWD",
    "PWD",
}
BLOCKED_ENV_PREFIXES = (
    "ANTHROPIC_",
    "AWS_",
    "AZURE_",
    "BEDROCK_",
    "GOOGLE_",
    "VERTEX_",
)


class OllamaAdapterError(RuntimeError):
    pass


def _canonical(data: Any) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _write_json(path: Path, value: Any) -> str:
    path.write_bytes(_canonical(value))
    return _sha(path)


def _version(binary: str) -> str:
    result = subprocess.run([binary, "--version"], capture_output=True, text=True)
    if result.returncode:
        raise OllamaAdapterError(
            f"cannot read Claude Code version: {(result.stderr or '').strip()}"
        )
    value = (result.stdout or "").strip()
    if not value:
        raise OllamaAdapterError("Claude Code returned an empty version")
    return value


def _help_surface_bytes(output: bytes) -> str:
    missing = sorted(
        flag for flag in REQUIRED_CLAUDE_FLAGS if flag.encode("ascii") not in output
    )
    if missing:
        raise OllamaAdapterError(f"Claude Code isolation flags are unavailable: {missing}")
    return _sha_bytes(output)


def _help_surface(binary: str) -> str:
    result = subprocess.run([binary, "--help"], capture_output=True)
    if result.returncode:
        stderr = result.stderr.decode(errors="replace").strip()
        raise OllamaAdapterError(f"cannot read Claude Code help: {stderr}")
    return _help_surface_bytes(result.stdout)


def _absolute_permission_path(path: Path) -> str:
    posix = path.resolve().as_posix()
    if len(posix) >= 3 and posix[1:3] == ":/":
        return f"//{posix[0].lower()}{posix[2:]}"
    return "//" + posix.lstrip("/")


def _escape_permission_pattern(path: str) -> str:
    return re.sub(r"([*?\[\]])", r"\\\1", path)


def _packet_access_args(worktree: Path) -> list[str]:
    return ["--add-dir", str(worktree)]


def _packet_permission_args(worktree: Path, files: list[str]) -> list[str]:
    rules: list[str] = []
    for path in files:
        normalized = path.replace("\\", "/")
        relative = Path(*PurePosixPath(normalized.rstrip("/")).parts)
        absolute = _escape_permission_pattern(
            _absolute_permission_path(worktree / relative)
        )
        target = f"{absolute}/**" if normalized.endswith("/") else absolute
        rules.extend((f"Read({target})", f"Edit({target})", f"Write({target})"))
    return ["--permission-mode", "dontAsk", "--allowedTools", *rules]


def _claude_command(
    binary: str, model: str, effort: str, worktree: Path, files: list[str]
) -> list[str]:
    return [
        binary,
        "--print",
        "--input-format",
        "text",
        "--output-format",
        "json",
        "--model",
        model,
        "--effort",
        effort,
        *_packet_permission_args(worktree, files),
        "--safe-mode",
        "--no-session-persistence",
        "--disable-slash-commands",
        "--no-chrome",
        *_packet_access_args(worktree),
        "--strict-mcp-config",
        "--mcp-config",
        EMPTY_MCP_CONFIG,
        "--tools",
        CLAUDE_TOOLS,
    ]


def _usage(data: dict[str, Any]) -> dict[str, int]:
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return {
        "input_tokens": int(usage.get("input_tokens", 0) or 0),
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
        "cache_read_tokens": int(usage.get("cache_read_input_tokens", 0) or 0),
        "cache_write_tokens": int(usage.get("cache_creation_input_tokens", 0) or 0),
    }


def _usage_evidenced(data: dict[str, Any]) -> bool:
    usage = data.get("usage")
    required = {
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    }
    return bool(
        isinstance(usage, dict)
        and required <= set(usage)
        and all(
            isinstance(usage[key], int)
            and not isinstance(usage[key], bool)
            and usage[key] >= 0
            for key in required
        )
    )


def _runtime_model(data: dict[str, Any], requested: str) -> tuple[str, bool]:
    model_usage = data.get("modelUsage")
    if isinstance(model_usage, dict) and len(model_usage) == 1:
        model = next(iter(model_usage))
        if isinstance(model, str) and model:
            return model, True
    model = data.get("model")
    if isinstance(model, str) and model:
        return model, True
    return requested, False


def _loopback_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "http":
        raise OllamaAdapterError("Ollama endpoint must use plain HTTP on loopback")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise OllamaAdapterError("Ollama endpoint cannot contain credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise OllamaAdapterError("Ollama endpoint must not contain a path")
    if parsed.hostname is None or parsed.port is None:
        raise OllamaAdapterError("Ollama endpoint must include an explicit loopback port")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise OllamaAdapterError(
            "Ollama endpoint must use a loopback IP literal, not DNS"
        ) from exc
    if not address.is_loopback:
        raise OllamaAdapterError("Ollama endpoint must be loopback-only")
    host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    return f"http://{host}:{parsed.port}"


def _api_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    base_url = _loopback_base_url(base_url)
    raw_payload = _canonical(payload) if payload is not None else None
    request = Request(
        base_url + path,
        data=raw_payload,
        method=method,
        headers={"Content-Type": "application/json"} if raw_payload is not None else {},
    )
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(MAX_API_RESPONSE_BYTES + 1)
    except OSError as exc:
        raise OllamaAdapterError(f"Ollama API request failed for {path}: {exc}") from exc
    if len(raw) > MAX_API_RESPONSE_BYTES:
        raise OllamaAdapterError(f"Ollama API response is too large for {path}")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OllamaAdapterError(f"Ollama API returned invalid JSON for {path}") from exc
    if not isinstance(value, dict):
        raise OllamaAdapterError(f"Ollama API response must be an object for {path}")
    return value


def _model_aliases(model: str) -> set[str]:
    aliases = {model}
    if model.endswith(":latest"):
        aliases.add(model[: -len(":latest")])
    elif ":" not in model.rsplit("/", 1)[-1]:
        aliases.add(model + ":latest")
    return aliases


def _row_model_names(row: dict[str, Any]) -> set[str]:
    return {
        value
        for key in ("name", "model")
        if isinstance((value := row.get(key)), str) and value
    }


def _find_model(
    container: dict[str, Any], model: str, label: str
) -> dict[str, Any] | None:
    rows = container.get("models")
    if not isinstance(rows, list):
        raise OllamaAdapterError(f"Ollama {label} response has no models array")
    aliases = _model_aliases(model)
    matches = [
        row
        for row in rows
        if isinstance(row, dict) and (_row_model_names(row) & aliases)
    ]
    if len(matches) > 1:
        raise OllamaAdapterError(
            f"Ollama {label} expected at most one exact model {model!r}, "
            f"found {len(matches)}"
        )
    return matches[0] if matches else None


def _select_model(container: dict[str, Any], model: str, label: str) -> dict[str, Any]:
    match = _find_model(container, model, label)
    if match is None:
        raise OllamaAdapterError(f"Ollama {label} has no exact model {model!r}")
    return match


def _model_digest(row: dict[str, Any]) -> str:
    value = row.get("digest")
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise OllamaAdapterError("Ollama model has no full lowercase SHA-256 digest")
    return value


def _running_attestation(
    row: dict[str, Any], *, expected_context: int, min_gpu_residency: float
) -> dict[str, Any]:
    size = row.get("size")
    size_vram = row.get("size_vram")
    context = row.get("context_length")
    for value, label in ((size, "size"), (size_vram, "size_vram"), (context, "context_length")):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise OllamaAdapterError(f"Ollama running model {label} is invalid")
    if context < expected_context:
        raise OllamaAdapterError(
            f"Ollama allocated context {context}, below required {expected_context}"
        )
    ratio = 1.0 if size == 0 and size_vram == 0 else (size_vram / size if size else 0.0)
    if not math.isfinite(ratio) or ratio < min_gpu_residency:
        raise OllamaAdapterError(
            "Ollama model is not sufficiently GPU-resident: "
            f"ratio={ratio:.6f}, required={min_gpu_residency:.6f}"
        )
    return {
        "context_length": context,
        "gpu_residency_ratio": ratio,
        "size": size,
        "size_vram": size_vram,
    }


def _server_attestation(
    path: Path,
    expected_sha256: str,
    *,
    ollama_host: str,
    ollama_version: str,
    context_length: int,
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise OllamaAdapterError("server-attestation SHA-256 is invalid")
    raw = path.read_bytes()
    actual = _sha_bytes(raw)
    if actual != expected_sha256:
        raise OllamaAdapterError(
            f"server-attestation hash mismatch: expected {expected_sha256}, got {actual}"
        )
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OllamaAdapterError("server attestation is invalid JSON") from exc
    if not isinstance(value, dict) or value.get("schema") != SERVER_ATTESTATION_SCHEMA:
        raise OllamaAdapterError(
            f"server attestation schema must be {SERVER_ATTESTATION_SCHEMA}"
        )
    expected = {
        "ollama_host": _loopback_base_url(ollama_host),
        "ollama_version": ollama_version,
        "context_length": context_length,
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            raise OllamaAdapterError(
                f"server attestation {key} contradicts frozen backend command"
            )
    gpu_uuid = value.get("gpu_uuid")
    if not isinstance(gpu_uuid, str) or not re.fullmatch(r"GPU-[0-9A-Fa-f-]+", gpu_uuid):
        raise OllamaAdapterError("server attestation has no NVIDIA GPU UUID")
    pid = value.get("server_pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise OllamaAdapterError("server attestation has no positive process id")
    launch = value.get("launch_environment")
    if not isinstance(launch, dict):
        raise OllamaAdapterError("server attestation has no launch environment")
    required_launch = {
        "CUDA_VISIBLE_DEVICES": gpu_uuid,
        "OLLAMA_CONTEXT_LENGTH": str(context_length),
        "OLLAMA_HOST": urlsplit(_loopback_base_url(ollama_host)).netloc,
        "OLLAMA_MAX_LOADED_MODELS": "1",
        "OLLAMA_NUM_PARALLEL": "1",
    }
    for key, expected_value in required_launch.items():
        if str(launch.get(key)) != expected_value:
            raise OllamaAdapterError(
                f"server launch environment {key} contradicts attestation"
            )
    return value


def _local_env(environment: dict[str, str], ollama_host: str) -> dict[str, str]:
    endpoint = _loopback_base_url(ollama_host)
    clean: dict[str, str] = {}
    for key, value in environment.items():
        if key.startswith("TIER_") or key in BLOCKED_ENV_KEYS:
            continue
        if key.startswith("CLAUDE_CODE_") and key.endswith("_SESSION_ID"):
            continue
        if key.startswith(BLOCKED_ENV_PREFIXES):
            continue
        if key.upper() in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}:
            continue
        clean[key] = value
    clean["ANTHROPIC_AUTH_TOKEN"] = "ollama"
    clean["ANTHROPIC_API_KEY"] = ""
    clean["ANTHROPIC_BASE_URL"] = endpoint
    clean["NO_PROXY"] = "127.0.0.1,::1,localhost"
    clean["no_proxy"] = clean["NO_PROXY"]
    clean["PYTHONUTF8"] = "1"
    return clean


def _copy_attestation(source: Path, destination: Path) -> str:
    raw = source.read_bytes()
    destination.write_bytes(raw)
    return _sha_bytes(raw)


def _adapter_source_sha256() -> str:
    return _sha(Path(__file__))


def _kill_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _run_claude(
    command: list[str],
    *,
    cwd: Path,
    prompt: str,
    environment: dict[str, str],
    timeout_seconds: float,
) -> tuple[int, str, str, bool]:
    creationflags = (
        subprocess.CREATE_NEW_PROCESS_GROUP
        if os.name == "nt" and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP")
        else 0
    )
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
        start_new_session=os.name != "nt",
        creationflags=creationflags,
    )
    try:
        stdout, stderr = process.communicate(input=prompt, timeout=timeout_seconds)
        return process.returncode, stdout or "", stderr or "", False
    except subprocess.TimeoutExpired:
        _kill_process_tree(process)
        stdout, stderr = process.communicate()
        return 124, stdout or "", stderr or "", True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fresh, safe-mode Claude Code adapter for a GPU-pinned Ollama server"
    )
    parser.add_argument("--arm", required=True)
    parser.add_argument("--dispatch", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--claude-bin", default="claude")
    parser.add_argument("--claude-version", required=True)
    parser.add_argument("--claude-help-sha256", required=True)
    parser.add_argument("--adapter-version", default=ADAPTER_VERSION)
    parser.add_argument("--adapter-source-sha256", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--tier", default="local-coding-candidate")
    parser.add_argument("--surface", default="ollama-claude-code-local")
    parser.add_argument("--cost-basis", default="shadow-estimated")
    parser.add_argument("--ollama-host", required=True)
    parser.add_argument("--ollama-version", required=True)
    parser.add_argument("--ollama-model-digest", required=True)
    parser.add_argument("--context-length", type=int, required=True)
    parser.add_argument("--min-gpu-residency", type=float, default=0.95)
    parser.add_argument("--server-attestation", type=Path, required=True)
    parser.add_argument("--server-attestation-sha256", required=True)
    parser.add_argument("--call-timeout-seconds", type=float, default=900.0)
    args = parser.parse_args(argv)

    if args.adapter_version != ADAPTER_VERSION:
        raise OllamaAdapterError(
            "adapter version drift: this code is adapter "
            f"{ADAPTER_VERSION!r}, manifest requested {args.adapter_version!r}"
        )
    if args.context_length <= 0:
        raise OllamaAdapterError("context length must be positive")
    if args.call_timeout_seconds <= 0:
        raise OllamaAdapterError("call timeout must be positive")
    if not 0.0 <= args.min_gpu_residency <= 1.0:
        raise OllamaAdapterError("minimum GPU residency must be between zero and one")

    actual_adapter_hash = _adapter_source_sha256()
    if actual_adapter_hash != args.adapter_source_sha256:
        raise OllamaAdapterError(
            "adapter source drift: "
            f"expected {args.adapter_source_sha256}, got {actual_adapter_hash}"
        )

    ollama_host = _loopback_base_url(args.ollama_host)
    actual_claude_version = _version(args.claude_bin)
    if actual_claude_version != args.claude_version:
        raise OllamaAdapterError(
            "Claude Code version drift: "
            f"expected {args.claude_version!r}, got {actual_claude_version!r}"
        )
    actual_help_hash = _help_surface(args.claude_bin)
    if actual_help_hash != args.claude_help_sha256:
        raise OllamaAdapterError(
            "Claude Code help-surface drift: "
            f"expected {args.claude_help_sha256}, got {actual_help_hash}"
        )

    attestation = _server_attestation(
        args.server_attestation,
        args.server_attestation_sha256,
        ollama_host=ollama_host,
        ollama_version=args.ollama_version,
        context_length=args.context_length,
    )
    version_payload = _api_json(ollama_host, "/api/version")
    actual_ollama_version = version_payload.get("version")
    if actual_ollama_version != args.ollama_version:
        raise OllamaAdapterError(
            "Ollama version drift: "
            f"expected {args.ollama_version!r}, got {actual_ollama_version!r}"
        )
    tags_payload = _api_json(ollama_host, "/api/tags")
    installed_model = _select_model(tags_payload, args.model, "tags")
    actual_digest = _model_digest(installed_model)
    if actual_digest != args.ollama_model_digest:
        raise OllamaAdapterError(
            "Ollama model digest drift: "
            f"expected {args.ollama_model_digest}, got {actual_digest}"
        )
    running_before = _api_json(ollama_host, "/api/ps")

    dispatch = json.loads(args.dispatch.read_text(encoding="utf-8"))
    if not isinstance(dispatch, dict) or not isinstance(dispatch.get("files"), list):
        raise OllamaAdapterError("dispatch is missing its bounded file scope")
    prompt = args.prompt.read_text(encoding="utf-8")
    raw_path = args.result.with_name("claude-ollama-result.raw.json")
    stderr_path = args.result.with_name("claude-ollama-result.stderr.txt")
    preflight_path = args.result.with_name("ollama-preflight.json")
    postflight_path = args.result.with_name("ollama-postflight.json")
    attestation_copy_path = args.result.with_name("ollama-server-attestation.json")

    preflight = {
        "schema": "tier-bench/ollama-adapter-preflight@1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "ollama_host": ollama_host,
        "ollama_version": actual_ollama_version,
        "model": installed_model,
        "running_before": running_before,
        "server_attestation_sha256": args.server_attestation_sha256,
    }
    _write_json(preflight_path, preflight)
    copied_attestation_hash = _copy_attestation(
        args.server_attestation, attestation_copy_path
    )
    if copied_attestation_hash != args.server_attestation_sha256:
        raise OllamaAdapterError("copied server attestation changed bytes")

    command = _claude_command(
        args.claude_bin,
        args.model,
        args.effort,
        args.worktree,
        [str(item) for item in dispatch["files"]],
    )
    child_env = _local_env(dict(os.environ), ollama_host)
    started = time.monotonic()
    returncode, stdout, stderr, timed_out = _run_claude(
        command,
        cwd=args.worktree,
        prompt=prompt,
        environment=child_env,
        timeout_seconds=args.call_timeout_seconds,
    )
    latency_ms = (time.monotonic() - started) * 1000
    raw_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}

    running_after = _api_json(ollama_host, "/api/ps")
    attestation_errors: list[str] = []
    running_model: dict[str, Any] | None = None
    running_metrics: dict[str, Any] = {}
    try:
        running_model = _select_model(running_after, args.model, "running-model")
        if _model_digest(running_model) != args.ollama_model_digest:
            raise OllamaAdapterError("running model digest contradicts frozen model digest")
        running_metrics = _running_attestation(
            running_model,
            expected_context=args.context_length,
            min_gpu_residency=args.min_gpu_residency,
        )
    except OllamaAdapterError as exc:
        attestation_errors.append(str(exc))

    runtime_model, runtime_model_evidenced = _runtime_model(data, args.model)
    if runtime_model_evidenced and runtime_model != args.model:
        attestation_errors.append(
            f"Claude Code reported runtime model {runtime_model!r}, expected {args.model!r}"
        )
    session_id = data.get("session_id")
    usage = _usage(data)
    telemetry_complete = bool(
        data
        and isinstance(session_id, str)
        and session_id
        and runtime_model_evidenced
        and runtime_model == args.model
        and _usage_evidenced(data)
        and running_model is not None
        and not attestation_errors
    )
    process_passed = returncode == 0 and not timed_out and not data.get("is_error", False)
    outcome = "pass" if process_passed and telemetry_complete else "error"

    postflight = {
        "schema": "tier-bench/ollama-adapter-postflight@1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "ollama_host": ollama_host,
        "model": running_model,
        "metrics": running_metrics,
        "running_after": running_after,
        "attestation_errors": attestation_errors,
        "telemetry_complete": telemetry_complete,
        "timed_out": timed_out,
    }
    _write_json(postflight_path, postflight)

    tool_versions = {
        "claude_code": actual_claude_version,
        "claude_help_sha256": actual_help_hash,
        "ollama": str(actual_ollama_version),
        "ollama_endpoint": ollama_host,
        "ollama_server_attestation_sha256": args.server_attestation_sha256,
        "tier_claude_ollama_adapter": args.adapter_version,
        "tier_claude_ollama_adapter_sha256": actual_adapter_hash,
    }
    note = (
        f"{args.cost_basis} local-zero-marginal; claude_rc={returncode}; "
        f"attestation_errors={len(attestation_errors)}"
    )
    call = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "account": args.account,
        "model": args.model,
        "tier": args.tier,
        "task_id": dispatch.get("task_id", "MISSING"),
        "phase": args.arm,
        "outcome": outcome,
        "effort": args.effort,
        **usage,
        "cost_usd": 0.0,
        "latency_ms": latency_ms,
        "trial": 0,
        "note": note,
        "extra": {
            "backend_manifest_sha256": dispatch.get("backend_manifest_sha256"),
            "backend_surface": args.surface,
            "cost_basis": args.cost_basis,
            "dispatch_receipt_sha256": _sha(args.dispatch),
            "prompt_template_sha256": dispatch.get("prompt_template_sha256"),
            "runtime_model_id": runtime_model,
            "session_id": session_id or f"MISSING-{uuid.uuid4()}",
            "telemetry_complete": telemetry_complete,
            "tool_versions": tool_versions,
            "raw_result_sha256": _sha(raw_path),
            "stderr_sha256": _sha(stderr_path),
            "ollama_preflight_sha256": _sha(preflight_path),
            "ollama_postflight_sha256": _sha(postflight_path),
            "ollama_model_digest": args.ollama_model_digest,
            "ollama_context_length": running_metrics.get("context_length"),
            "ollama_size": running_metrics.get("size"),
            "ollama_size_vram": running_metrics.get("size_vram"),
            "ollama_gpu_residency_ratio": running_metrics.get("gpu_residency_ratio"),
            "ollama_server_attestation_sha256": args.server_attestation_sha256,
            "ollama_gpu_uuid": attestation.get("gpu_uuid"),
            "attestation_errors": attestation_errors,
            "call_timeout_seconds": args.call_timeout_seconds,
            "timed_out": timed_out,
        },
    }
    args.result.write_bytes(
        _canonical(
            {
                "schema": SCHEMA,
                "calls": [call],
                "artifacts": [
                    {"name": "provider_raw", "path": raw_path.name, "sha256": _sha(raw_path)},
                    {
                        "name": "provider_stderr",
                        "path": stderr_path.name,
                        "sha256": _sha(stderr_path),
                    },
                    {
                        "name": "ollama_preflight",
                        "path": preflight_path.name,
                        "sha256": _sha(preflight_path),
                    },
                    {
                        "name": "ollama_postflight",
                        "path": postflight_path.name,
                        "sha256": _sha(postflight_path),
                    },
                    {
                        "name": "ollama_server_attestation",
                        "path": attestation_copy_path.name,
                        "sha256": _sha(attestation_copy_path),
                    },
                ],
            }
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"tier Claude/Ollama adapter: {exc}", file=sys.stderr)
        raise SystemExit(2)
