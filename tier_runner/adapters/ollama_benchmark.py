from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any
from urllib.request import urlopen

from cost_guard import Tier
from harness.attempt import run_attempt
from harness.model_call import get_guard
from harness.task_schema import Task
from tier_runner.benchmark_report import REPORT_PATH, SCHEMA, requested_count


BACKEND_SCHEMA = "tier-bench/tier-backend-result@1"
ADAPTER_VERSION = "1"


class AdapterError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _task_from_prompt(prompt: str) -> str:
    match = re.search(r"\nTask:\n(.*?)\n\nDeclared edit scope:\n", "\n" + prompt, re.S)
    if not match or not match.group(1).strip():
        raise AdapterError("frozen prompt has no benchmark task")
    return match.group(1).strip()


def _verify_model(base_url: str, model: str, digest: str) -> None:
    with urlopen(base_url.rstrip("/") + "/api/tags", timeout=10) as response:
        value = json.loads(response.read())
    for entry in value.get("models", []):
        if entry.get("name") == model and entry.get("digest") == digest:
            return
    raise AdapterError("the frozen local benchmark model/digest is not installed")


def _tasks(source_root: Path, count: int) -> list[Path]:
    candidates: list[Path] = []
    for tier in ("t1", "t2", "t3"):
        candidates.extend(sorted((source_root / "tasks").glob(f"{tier}_*.json")))
    if len(candidates) < count:
        raise AdapterError(f"only {len(candidates)} eligible benchmark tasks exist")
    return candidates[:count]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Bounded local Tier Desk benchmark adapter")
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
    result.add_argument("--surface", default="ollama-local-benchmark")
    result.add_argument("--cost-basis", default="shadow-estimated")
    result.add_argument("--base-url", default="http://127.0.0.1:11434")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.adapter_version != ADAPTER_VERSION:
        raise AdapterError("benchmark adapter version drifted from the frozen manifest")
    dispatch = json.loads(args.dispatch.read_text(encoding="utf-8"))
    intent = _task_from_prompt(args.prompt.read_text(encoding="utf-8"))
    count = requested_count(intent)
    _verify_model(args.base_url, args.model, args.model_digest)
    source_root = Path(__file__).resolve().parents[2]
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=source_root, capture_output=True, text=True, check=True
    ).stdout.strip()
    if head != dispatch.get("base_commit"):
        raise AdapterError("benchmark source HEAD does not equal the frozen dispatch base")
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", "tasks", "fixtures", "harness", "cost_guard.py", "models.json"],
        cwd=source_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if dirty:
        raise AdapterError("benchmark source files differ from the frozen base")

    run_dir = args.result.parent
    guard = get_guard()
    guard.log_file = str(run_dir / "benchmark-costs.jsonl")
    rows: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    old_cwd = Path.cwd()
    try:
        os.chdir(source_root)
        for trial, task_path in enumerate(_tasks(source_root, count), 1):
            task = Task.from_json(task_path)
            tier = Tier[task.tier]
            started = time.monotonic()
            row, output = run_attempt(
                task,
                tier,
                args.model,
                canonical_root=source_root,
                establish_canonical=False,
            )
            latency_ms = (time.monotonic() - started) * 1000
            input_tokens = int(row.get("input_tokens", 0) or 0)
            output_tokens = int(row.get("output_tokens", 0) or 0)
            if input_tokens + output_tokens <= 0:
                raise AdapterError(f"benchmark task {task.task_id} has no provider telemetry")
            row["duration_seconds"] = round(latency_ms / 1000, 6)
            row["output_sha256"] = _sha_bytes((output or "").encode())
            rows.append(row)
            session_id = "ollama-benchmark-" + _sha_bytes(
                f"{dispatch['run_id']}:{trial}:{task.task_id}".encode()
            )
            calls.append(
                {
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
                    "cost_usd": float(row.get("actual_cost", 0) or 0),
                    "latency_ms": latency_ms,
                    "trial": trial,
                    "note": f"{args.cost_basis}; local deterministic benchmark observation",
                    "extra": {
                        "backend_manifest_sha256": dispatch["backend_manifest_sha256"],
                        "backend_surface": args.surface,
                        "benchmark_task_id": task.task_id,
                        "cost_basis": args.cost_basis,
                        "dispatch_receipt_sha256": _sha(args.dispatch),
                        "prompt_template_sha256": dispatch["prompt_template_sha256"],
                        "runtime_model_id": args.model,
                        "session_id": session_id,
                        "telemetry_complete": True,
                        "tool_versions": {
                            "model_digest": args.model_digest,
                            "ollama": args.ollama_version,
                            "tier_ollama_benchmark_adapter": args.adapter_version,
                        },
                        "validator_pass": bool(row.get("pass")),
                    },
                }
            )
    finally:
        os.chdir(old_cwd)

    total_input = sum(int(row["input_tokens"]) for row in rows)
    total_output = sum(int(row["output_tokens"]) for row in rows)
    passes = sum(int(bool(row.get("pass"))) for row in rows)
    report = {
        "schema": SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "suite_commit": head,
        "model": args.model,
        "model_digest": args.model_digest,
        "requested_count": count,
        "rows": rows,
        "summary": {
            "attempts": count,
            "passes": passes,
            "failures": count - passes,
            "input_tokens": total_input,
            "output_tokens": total_output,
            "cost_usd": sum(float(row.get("actual_cost", 0) or 0) for row in rows),
            "wall_seconds": round(sum(float(row["duration_seconds"]) for row in rows), 6),
        },
    }
    packet_report = args.worktree / REPORT_PATH
    packet_report.parent.mkdir(parents=True, exist_ok=True)
    packet_report.write_bytes(_canonical(report))
    sealed_report = run_dir / "benchmark-report.json"
    sealed_report.write_bytes(_canonical(report))
    costs = run_dir / "benchmark-costs.jsonl"
    args.result.write_bytes(
        _canonical(
            {
                "schema": BACKEND_SCHEMA,
                "calls": calls,
                "artifacts": [
                    {"name": "benchmark_report", "path": sealed_report.name, "sha256": _sha(sealed_report)},
                    {"name": "benchmark_costs", "path": costs.name, "sha256": _sha(costs)},
                ],
            }
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AdapterError, OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"tier local benchmark adapter: {exc}", flush=True)
        raise SystemExit(2)
