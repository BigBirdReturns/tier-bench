from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SCHEMA = "tier-bench/tier-backend-result@1"
ADAPTER_VERSION = "3"
MAX_CONTEXT_BYTES = 18_000
MAX_CONTEXT_FILES = 3
MAX_OUTPUT_BYTES = 512_000
INSTRUCTION_NAMES = {"AGENTS.md", "CLAUDE.md"}


class AdapterError(RuntimeError):
    pass


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _post(url: str, payload: dict[str, Any], timeout: float) -> tuple[dict[str, Any], bytes]:
    raw = _canonical(payload)
    request = Request(
        url,
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_OUTPUT_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise AdapterError(f"Ollama request failed: {exc}") from exc
    if len(body) > MAX_OUTPUT_BYTES:
        raise AdapterError("Ollama response exceeded the bounded output size")
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdapterError(f"Ollama returned invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise AdapterError("Ollama response must be an object")
    return value, body


def _get(url: str, timeout: float) -> dict[str, Any]:
    try:
        with urlopen(url, timeout=timeout) as response:
            body = response.read(MAX_OUTPUT_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise AdapterError(f"Ollama readiness request failed: {exc}") from exc
    if len(body) > MAX_OUTPUT_BYTES:
        raise AdapterError("Ollama readiness response exceeded the bounded output size")
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdapterError(f"Ollama readiness response is invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise AdapterError("Ollama readiness response must be an object")
    return value


def _normalize(path: str) -> str:
    value = path.replace("\\", "/").strip()
    pure = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or pure.is_absolute()
        or ".." in pure.parts
        or any(part in {"", ".", ".git"} for part in pure.parts)
        or pure.name.upper() in {name.upper() for name in INSTRUCTION_NAMES}
    ):
        raise AdapterError(f"unsafe emitted path: {path!r}")
    return pure.as_posix()


def _in_scope(path: str, scopes: list[str]) -> bool:
    for scope in scopes:
        normalized = scope.replace("\\", "/")
        if normalized.endswith("/"):
            if path.startswith(normalized) and path != normalized:
                return True
        elif path == normalized:
            return True
    return False


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]{2,}", value.lower()) if token not in {"the", "and", "for", "with", "this", "that"}}


def _context_files(worktree: Path, prompt: str) -> list[tuple[str, str]]:
    candidates: list[tuple[int, str, str, int]] = []
    intent_tokens = _tokens(prompt)
    for item in worktree.rglob("*"):
        if not item.is_file() or item.is_symlink():
            continue
        relative = item.relative_to(worktree).as_posix()
        if ".git" in PurePosixPath(relative).parts or item.name.upper() in {name.upper() for name in INSTRUCTION_NAMES}:
            continue
        raw = item.read_bytes()
        if b"\0" in raw or len(raw) > MAX_CONTEXT_BYTES:
            continue
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            continue
        score = (8 * len(intent_tokens & _tokens(relative))) + len(
            intent_tokens & _tokens(content)
        )
        if item.name.lower() in {"readme.md", "pyproject.toml", "package.json"}:
            score += 1
        cost = len(relative.encode()) + len(content.encode())
        candidates.append((score, relative, content, cost))
    candidates.sort(key=lambda entry: (-entry[0], entry[1]))
    selected: list[tuple[str, str]] = []
    used = 0
    for _, relative, content, cost in candidates:
        if len(selected) >= MAX_CONTEXT_FILES:
            break
        if used + cost > MAX_CONTEXT_BYTES:
            continue
        selected.append((relative, content))
        used += cost
    if not selected:
        raise AdapterError("the scoped packet has no bounded UTF-8 file context")
    return selected


def _output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "files": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "minLength": 1},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["files"],
        "additionalProperties": False,
    }


def _apply_emission(worktree: Path, scopes: list[str], emission: dict[str, Any]) -> list[str]:
    files = emission.get("files")
    if not isinstance(files, list) or not files:
        raise AdapterError("model emission must contain at least one file")
    changed: list[str] = []
    seen: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"path", "content"}:
            raise AdapterError("each model emission must contain exactly path and content")
        path = _normalize(str(entry["path"]))
        content = entry["content"]
        if not isinstance(content, str):
            raise AdapterError(f"emitted content for {path} must be text")
        if path in seen:
            raise AdapterError(f"model emitted duplicate path: {path}")
        if not _in_scope(path, scopes):
            raise AdapterError(f"model emitted path outside dispatch scope: {path}")
        seen.add(path)
        target = (worktree / Path(*PurePosixPath(path).parts)).resolve()
        try:
            target.relative_to(worktree.resolve())
        except ValueError as exc:
            raise AdapterError(f"model emitted path outside packet: {path}") from exc
        if target.is_file() and target.read_bytes().endswith(b"\n") and not content.endswith("\n"):
            content += "\n"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        changed.append(path)
    return sorted(changed)


def _verify_model(base_url: str, model: str, digest: str, timeout: float) -> None:
    tags = _get(base_url.rstrip("/") + "/api/tags", timeout)
    models = tags.get("models")
    if not isinstance(models, list):
        raise AdapterError("Ollama readiness response has no models array")
    for entry in models:
        if isinstance(entry, dict) and entry.get("name") == model:
            if entry.get("digest") != digest:
                raise AdapterError("Ollama model digest drifted from the frozen manifest")
            return
    raise AdapterError(f"Ollama model is not installed: {model}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Strict local Ollama text-emission tier adapter")
    result.add_argument("--arm", required=True)
    result.add_argument("--dispatch", type=Path, required=True)
    result.add_argument("--prompt", type=Path, required=True)
    result.add_argument("--result", type=Path, required=True)
    result.add_argument("--worktree", type=Path, required=True)
    result.add_argument("--model", required=True)
    result.add_argument("--model-digest", required=True)
    result.add_argument("--ollama-version", required=True)
    result.add_argument("--adapter-version", default=ADAPTER_VERSION)
    result.add_argument("--account", default="local-ollama")
    result.add_argument("--tier", default="local")
    result.add_argument("--surface", default="ollama-local-text-emit")
    result.add_argument("--cost-basis", default="shadow-estimated")
    result.add_argument("--base-url", default="http://127.0.0.1:11434")
    result.add_argument("--timeout", type=float, default=180.0)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.adapter_version != ADAPTER_VERSION:
        raise AdapterError("Ollama adapter version drifted from the frozen manifest")
    dispatch = json.loads(args.dispatch.read_text(encoding="utf-8"))
    if not isinstance(dispatch, dict) or not isinstance(dispatch.get("files"), list):
        raise AdapterError("dispatch receipt has no file scope")
    prompt = args.prompt.read_text(encoding="utf-8")
    _verify_model(args.base_url, args.model, args.model_digest, min(args.timeout, 10.0))
    context = _context_files(args.worktree, prompt)
    file_blocks = "\n\n".join(
        f"=== {path} ===\n{content}" for path, content in context
    )
    system = (
        "You are a bounded code-editing hand. Return only JSON matching the supplied schema. "
        "Emit exactly one complete replacement file. Never emit prose, "
        "deletions, instruction files, or paths outside the declared scope. The controller, not "
        "you, runs acceptance and decides whether the patch is valid."
    )
    user = f"{prompt}\n\nBOUNDED FILE CONTEXT\n{file_blocks}"
    request_payload = {
        "model": args.model,
        "stream": False,
        "think": False,
        "format": _output_schema(),
        "options": {"temperature": 0, "num_predict": 16384},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    started_ns = time.time_ns()
    started = time.monotonic()
    response, raw_response = _post(
        args.base_url.rstrip("/") + "/api/chat", request_payload, args.timeout
    )
    run_dir = args.result.parent
    raw_path = run_dir / "ollama-result.raw.json"
    raw_path.write_bytes(raw_response)
    latency_ms = (time.monotonic() - started) * 1000
    message = response.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content:
        raise AdapterError("Ollama response has no assistant content")
    try:
        emission = json.loads(content)
    except json.JSONDecodeError as exc:
        raise AdapterError(f"Ollama assistant content is invalid JSON: {exc}") from exc
    if not isinstance(emission, dict):
        raise AdapterError("Ollama assistant content must be a JSON object")
    changed = _apply_emission(args.worktree.resolve(), dispatch["files"], emission)
    emission_path = run_dir / "ollama-emission.json"
    emission_path.write_bytes(_canonical({"changed": changed, "emission": emission}))
    runtime_model = response.get("model")
    if runtime_model != args.model:
        raise AdapterError("Ollama runtime model contradicts the frozen manifest")
    input_tokens = response.get("prompt_eval_count", 0)
    output_tokens = response.get("eval_count", 0)
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        raise AdapterError("Ollama response has incomplete token telemetry")
    session_id = "ollama-" + _sha_bytes(
        f"{started_ns}:{response.get('created_at', '')}:{_sha_bytes(raw_response)}".encode()
    )
    call = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "account": args.account,
        "model": args.model,
        "tier": args.tier,
        "task_id": dispatch["task_id"],
        "phase": args.arm,
        "outcome": "pass",
        "effort": "deterministic",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": 0.0,
        "latency_ms": latency_ms,
        "trial": 0,
        "note": f"{args.cost_basis}; local Ollama strict text emission",
        "extra": {
            "backend_manifest_sha256": dispatch["backend_manifest_sha256"],
            "backend_surface": args.surface,
            "cost_basis": args.cost_basis,
            "dispatch_receipt_sha256": _sha(args.dispatch),
            "prompt_template_sha256": dispatch["prompt_template_sha256"],
            "runtime_model_id": args.model,
            "session_id": session_id,
            "telemetry_complete": True,
            "tool_versions": {
                "model_digest": args.model_digest,
                "ollama": args.ollama_version,
                "tier_ollama_emit_adapter": args.adapter_version,
            },
        },
    }
    args.result.write_bytes(
        _canonical(
            {
                "schema": SCHEMA,
                "calls": [call],
                "artifacts": [
                    {"name": "provider_raw", "path": raw_path.name, "sha256": _sha(raw_path)},
                    {"name": "emission", "path": emission_path.name, "sha256": _sha(emission_path)},
                ],
            }
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AdapterError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"tier ollama adapter: {exc}", flush=True)
        raise SystemExit(2)
