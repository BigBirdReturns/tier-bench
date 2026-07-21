from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import time

from ..desk_common import hidden_process_kwargs

from .ollama_emit import (
    SCHEMA,
    AdapterError,
    _apply_emission,
    _canonical,
    _context_files,
    _sha,
    _sha_bytes,
)


ADAPTER_VERSION = "1"
MAX_LAST_MESSAGE_BYTES = 512_000


def _codex_version(codex_bin: str) -> str:
    executable = shutil.which(codex_bin)
    if executable is None:
        raise AdapterError(f"codex CLI is not on PATH: {codex_bin}")
    probe = subprocess.run(
        [executable, "--version"],
        capture_output=True,
        text=True,
        **hidden_process_kwargs(),
    )
    if probe.returncode:
        raise AdapterError(f"codex --version exited {probe.returncode}")
    return probe.stdout.strip()


def _strip_fences(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        first_newline = value.find("\n")
        if first_newline >= 0 and value.endswith("```"):
            value = value[first_newline + 1 : -3].strip()
    return value


def _collect_usage(events_raw: str) -> tuple[int, int, int, bool]:
    input_tokens = output_tokens = cache_read = 0
    seen = False
    for line in events_raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        usage = event.get("usage")
        if isinstance(usage, dict):
            seen = True
            input_tokens += int(usage.get("input_tokens", 0) or 0)
            output_tokens += int(usage.get("output_tokens", 0) or 0)
            cache_read += int(usage.get("cached_input_tokens", 0) or 0)
    return input_tokens, output_tokens, cache_read, seen


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Codex CLI subscription text-emission tier adapter"
    )
    result.add_argument("--arm", required=True)
    result.add_argument("--dispatch", type=Path, required=True)
    result.add_argument("--prompt", type=Path, required=True)
    result.add_argument("--result", type=Path, required=True)
    result.add_argument("--worktree", type=Path, required=True)
    result.add_argument("--model", required=True)
    result.add_argument("--effort", required=True)
    result.add_argument("--codex-version", required=True)
    result.add_argument("--adapter-version", default=ADAPTER_VERSION)
    result.add_argument("--codex-bin", default="codex")
    result.add_argument("--account", default="chatgpt-subscription")
    result.add_argument("--tier", default="frontier")
    result.add_argument("--surface", default="codex-cli-subscription-text-emit")
    result.add_argument("--cost-basis", default="subscription-derived")
    result.add_argument("--timeout", type=float, default=300.0)
    result.add_argument("--oss", action="store_true")
    result.add_argument("--local-provider", default="ollama")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.adapter_version != ADAPTER_VERSION:
        raise AdapterError("codex adapter version drifted from the frozen manifest")
    actual_version = _codex_version(args.codex_bin)
    if actual_version != args.codex_version:
        raise AdapterError(
            f"codex CLI version drift: expected {args.codex_version!r}, got {actual_version!r}"
        )
    dispatch = json.loads(args.dispatch.read_text(encoding="utf-8"))
    if not isinstance(dispatch, dict) or not isinstance(dispatch.get("files"), list):
        raise AdapterError("dispatch receipt has no file scope")
    prompt = args.prompt.read_text(encoding="utf-8")
    worktree = args.worktree.resolve()
    context = _context_files(worktree, prompt)
    file_blocks = "\n\n".join(f"=== {path} ===\n{content}" for path, content in context)
    message = (
        "You are a bounded code-editing hand. Reply with ONLY a JSON object of the form "
        '{"files":[{"path":"<repo-relative path>","content":"<complete replacement file>"}]} '
        "with exactly one file. No prose, no markdown fences. Never emit deletions, "
        "instruction files, or paths outside the declared scope. The controller, not you, "
        "runs acceptance and decides whether the patch is valid.\n\n"
        f"{prompt}\n\nBOUNDED FILE CONTEXT\n{file_blocks}"
    )
    run_dir = args.result.parent
    last_path = run_dir / "codex-last-message.txt"
    command = [
        args.codex_bin,
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "--json",
        "-C",
        str(worktree),
        "-m",
        args.model,
        "-c",
        f'model_reasoning_effort="{args.effort}"',
    ]
    if args.oss:
        command += ["--oss", "--local-provider", args.local_provider]
    command += [
        "-o",
        str(last_path),
        "-",
    ]
    started_ns = time.time_ns()
    started = time.monotonic()
    try:
        process = subprocess.run(
            command,
            input=message,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=args.timeout,
            **hidden_process_kwargs(),
        )
    except subprocess.TimeoutExpired as exc:
        raise AdapterError(f"codex exec exceeded {args.timeout:.0f}s") from exc
    latency_ms = (time.monotonic() - started) * 1000
    raw_path = run_dir / "codex-result.raw.jsonl"
    raw_path.write_text(process.stdout or "", encoding="utf-8", newline="\n")
    stderr_path = run_dir / "codex-result.stderr.txt"
    stderr_path.write_text(process.stderr or "", encoding="utf-8", newline="\n")
    if process.returncode:
        raise AdapterError(f"codex exec exited {process.returncode}")
    if not last_path.is_file():
        raise AdapterError("codex exec produced no last message")
    last_raw = last_path.read_bytes()
    if len(last_raw) > MAX_LAST_MESSAGE_BYTES:
        raise AdapterError("codex last message exceeded the bounded output size")
    try:
        emission = json.loads(_strip_fences(last_raw.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdapterError(f"codex last message is not a JSON emission: {exc}") from exc
    if not isinstance(emission, dict):
        raise AdapterError("codex emission must be a JSON object")
    changed = _apply_emission(worktree, dispatch["files"], emission)
    emission_path = run_dir / "codex-emission.json"
    emission_path.write_bytes(_canonical({"changed": changed, "emission": emission}))
    input_tokens, output_tokens, cache_read, telemetry_seen = _collect_usage(
        process.stdout or ""
    )
    session_id = "codex-" + _sha_bytes(
        f"{started_ns}:{_sha_bytes(last_raw)}:{_sha(raw_path)}".encode()
    )
    call = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "account": args.account,
        "model": args.model,
        "tier": args.tier,
        "task_id": dispatch["task_id"],
        "phase": args.arm,
        "outcome": "pass",
        "effort": args.effort,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": 0,
        "cost_usd": 0.0,
        "latency_ms": latency_ms,
        "trial": 0,
        "note": f"{args.cost_basis}; codex exec text emission; telemetry_seen={telemetry_seen}",
        "extra": {
            "backend_manifest_sha256": dispatch["backend_manifest_sha256"],
            "backend_surface": args.surface,
            "cost_basis": args.cost_basis,
            "dispatch_receipt_sha256": _sha(args.dispatch),
            "prompt_template_sha256": dispatch["prompt_template_sha256"],
            "runtime_model_id": args.model,
            "session_id": session_id,
            "telemetry_complete": telemetry_seen,
            "tool_versions": {
                "codex_cli": actual_version,
                "tier_codex_emit_adapter": args.adapter_version,
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
                    {"name": "last_message", "path": last_path.name, "sha256": _sha(last_path)},
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
        print(f"tier codex adapter: {exc}", flush=True)
        raise SystemExit(2)
