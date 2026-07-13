from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


SCHEMA = "tier-bench/tier-backend-result@1"
EMPTY_MCP_CONFIG = '{"mcpServers":{}}'
REQUIRED_CLAUDE_FLAGS = {
    "--add-dir",
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
NON_SUBSCRIPTION_ENV_KEYS = {
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_CUSTOM_HEADERS",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_USE_VERTEX",
    "GOOGLE_APPLICATION_CREDENTIALS",
}
NON_SUBSCRIPTION_ENV_PREFIXES = ("AWS_", "AZURE_", "BEDROCK_", "GOOGLE_", "VERTEX_")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _version(binary: str) -> str:
    result = subprocess.run([binary, "--version"], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"cannot read Claude Code version: {result.stderr.strip()}")
    return result.stdout.strip()


def _help_surface_bytes(output: bytes) -> str:
    missing = sorted(
        flag for flag in REQUIRED_CLAUDE_FLAGS if flag.encode("ascii") not in output
    )
    if missing:
        raise RuntimeError(f"Claude Code isolation flags are unavailable: {missing}")
    return hashlib.sha256(output).hexdigest()


def _help_surface(binary: str) -> str:
    result = subprocess.run([binary, "--help"], capture_output=True)
    if result.returncode:
        stderr = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"cannot read Claude Code help: {stderr}")
    return _help_surface_bytes(result.stdout)


def _subscription_env(environment: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in environment.items()
        if not key.startswith("TIER_")
        and key not in {"GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE", "OLDPWD", "PWD"}
        and key not in NON_SUBSCRIPTION_ENV_KEYS
        and not key.startswith(NON_SUBSCRIPTION_ENV_PREFIXES)
    }


def _packet_access_args(worktree: Path) -> list[str]:
    return ["--add-dir", str(worktree)]


def _usage(data: dict) -> dict:
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return {
        "input_tokens": int(usage.get("input_tokens", 0) or 0),
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
        "cache_read_tokens": int(usage.get("cache_read_input_tokens", 0) or 0),
        "cache_write_tokens": int(usage.get("cache_creation_input_tokens", 0) or 0),
    }


def _usage_evidenced(data: dict) -> bool:
    usage = data.get("usage")
    required = {
        "input_tokens", "output_tokens", "cache_read_input_tokens",
        "cache_creation_input_tokens",
    }
    return bool(
        isinstance(usage, dict)
        and required <= set(usage)
        and all(isinstance(usage[key], int) and not isinstance(usage[key], bool) and usage[key] >= 0
                for key in required)
    )


def _runtime_model(data: dict, requested: str) -> tuple[str, bool]:
    model_usage = data.get("modelUsage")
    if isinstance(model_usage, dict) and len(model_usage) == 1:
        return next(iter(model_usage)), True
    model = data.get("model")
    if isinstance(model, str) and model:
        return model, True
    return requested, False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fresh, safe-mode Claude Code tier adapter")
    parser.add_argument("--arm", required=True)
    parser.add_argument("--dispatch", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--claude-bin", default="claude")
    parser.add_argument("--claude-version", required=True)
    parser.add_argument("--claude-help-sha256", required=True)
    parser.add_argument("--adapter-version", default="3")
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--tier", default="cheap")
    parser.add_argument("--surface", default="claude-code-subscription")
    parser.add_argument("--cost-basis", default="subscription-derived")
    args = parser.parse_args(argv)

    actual_version = _version(args.claude_bin)
    if actual_version != args.claude_version:
        raise RuntimeError(
            f"Claude Code version drift: expected {args.claude_version!r}, got {actual_version!r}"
        )
    actual_help_hash = _help_surface(args.claude_bin)
    if actual_help_hash != args.claude_help_sha256:
        raise RuntimeError(
            "Claude Code help-surface drift: "
            f"expected {args.claude_help_sha256}, got {actual_help_hash}"
        )
    dispatch = json.loads(args.dispatch.read_text(encoding="utf-8"))
    prompt = args.prompt.read_text(encoding="utf-8")
    raw_path = args.result.with_name("claude-result.raw.json")
    stderr_path = args.result.with_name("claude-result.stderr.txt")
    command = [
        args.claude_bin,
        "--print",
        "--input-format", "text",
        "--output-format", "json",
        "--model", args.model,
        "--effort", args.effort,
        "--permission-mode", "acceptEdits",
        "--safe-mode",
        "--no-session-persistence",
        "--disable-slash-commands",
        "--no-chrome",
        *_packet_access_args(args.worktree),
        "--strict-mcp-config",
        "--mcp-config", EMPTY_MCP_CONFIG,
        "--tools", "Read,Edit,Write",
    ]
    child_env = _subscription_env(dict(os.environ))
    started = time.monotonic()
    process = subprocess.run(
        command,
        cwd=args.worktree,
        input=prompt,
        capture_output=True,
        text=True,
        env=child_env,
    )
    latency_ms = (time.monotonic() - started) * 1000
    raw_path.write_text(process.stdout or "", encoding="utf-8")
    stderr_path.write_text(process.stderr or "", encoding="utf-8")
    try:
        data = json.loads(process.stdout)
    except json.JSONDecodeError:
        data = {}
    usage = _usage(data)
    runtime_model, runtime_model_evidenced = _runtime_model(data, args.model)
    session_id = data.get("session_id")
    telemetry_complete = bool(
        data
        and isinstance(session_id, str)
        and session_id
        and runtime_model_evidenced
        and _usage_evidenced(data)
    )
    outcome = "pass" if process.returncode == 0 and not data.get("is_error", False) else "error"
    note = f"{args.cost_basis}; claude_rc={process.returncode}"
    call = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "account": args.account,
        "model": args.model,
        "tier": args.tier,
        "task_id": dispatch["task_id"],
        "phase": args.arm,
        "outcome": outcome,
        "effort": args.effort,
        **usage,
        "cost_usd": float(data.get("total_cost_usd", 0) or 0),
        "latency_ms": latency_ms,
        "trial": 0,
        "note": note,
        "extra": {
            "backend_manifest_sha256": dispatch["backend_manifest_sha256"],
            "backend_surface": args.surface,
            "cost_basis": args.cost_basis,
            "dispatch_receipt_sha256": _sha(args.dispatch),
            "prompt_template_sha256": dispatch["prompt_template_sha256"],
            "runtime_model_id": runtime_model,
            "session_id": session_id or "MISSING",
            "telemetry_complete": telemetry_complete,
            "tool_versions": {
                "claude_code": actual_version,
                "claude_help_sha256": actual_help_hash,
                "tier_claude_adapter": args.adapter_version,
            },
            "raw_result_sha256": _sha(raw_path),
            "stderr_sha256": _sha(stderr_path),
        },
    }
    args.result.write_text(
        json.dumps(
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
                ],
            },
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"tier claude adapter: {exc}", file=sys.stderr)
        raise SystemExit(2)
