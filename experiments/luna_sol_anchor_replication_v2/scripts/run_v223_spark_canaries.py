#!/usr/bin/env python3
"""Run only the authorized synthetic v2.2.3 Spark execution canaries."""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("luna_run_v223_canary", ROOT / "run_v2.py")
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

STUB = '''def summarize(records):
    """Return sorted per-account totals for eligible records."""
    raise NotImplementedError
'''

VISIBLE = '''import copy
from src.solution import summarize

records = [
    {"account": "beta", "amount": 7, "eligible": True},
    {"account": "alpha", "amount": 4, "eligible": True},
    {"account": "beta", "amount": -2, "eligible": True},
    {"account": "alpha", "amount": 100, "eligible": False},
]
before = copy.deepcopy(records)
assert summarize(records) == [
    {"account": "alpha", "total": 4},
    {"account": "beta", "total": 5},
]
assert records == before
assert summarize([]) == []
print("VISIBLE_OK")
'''

TASK_TEXT = '''Implement summarize(records) in src/solution.py. Include only records whose eligible field is true, sum integer amount values by account, and return a list of objects sorted by account. Do not mutate the input. Empty input returns an empty list.'''


def init_base(path: Path) -> None:
    runner.write(path / "src" / "__init__.py", "")
    runner.write(path / "src" / "solution.py", STUB)
    runner.write(path / "run_visible.py", VISIBLE)
    runner.write(path / "forbidden.txt", "preserve\n")
    for command in (
        ["init", "-q"],
        ["config", "user.name", "Spark v2.2.3 synthetic canary"],
        ["config", "user.email", "canary@example.invalid"],
        ["add", "."],
        ["commit", "-qm", "synthetic canary baseline"],
    ):
        result = runner.git(command, path)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors="replace"))


def run_case(output: Path, replicate: int) -> dict[str, Any]:
    trial = f"replicate_{replicate:03d}"
    case = output / trial
    base = case / "base"
    init_base(base)
    work = case / "work"
    runner.copy_state(base, work)
    crate = {
        "crate_id": f"synthetic-v223-{replicate:03d}",
        "objective": TASK_TEXT,
        "allowed_paths": ["src/solution.py"],
        "forbidden_paths": ["run_visible.py", "forbidden.txt", "src/__init__.py"],
        "dependencies": [],
        "visible_context_refs": ["synthetic task text", "run_visible.py"],
        "validator_ids": ["visible"],
        "command_budget": 6,
        "wall_time_seconds": 180,
        "stop_condition": "Stop only after the exact visible validator command exits 0.",
        "task_id": "synthetic_spark_execution_interface_v223",
        "trial_id": trial,
        "parent_state_sha256": runner.tree_state(base),
        "anchor_sha256": runner.sha_bytes(b"synthetic-no-anchor\n"),
        "controller_receipt_schema": "luna-sol-anchor-replication/spark-hand-controller-receipt@2.2.3",
    }
    packet = {
        "task_id": "synthetic_spark_execution_interface_v223",
        "trial_id": trial,
        "task_packet": {"task_text": TASK_TEXT},
        "hand_crate": crate,
    }
    call: dict[str, Any] | None = None
    receipt: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    try:
        call = runner.run_hand(output, trial, "synthetic_spark", "spark_hand", "gpt-5.3-codex-spark", "low", "workspace-write", work, crate, packet)
        receipt = runner.apply_hand(base, work, case / "accepted", {"src/solution.py"}, call)
    except runner.ControllerError as exc:
        error = exc.receipt()
        receipt_path = case / "synthetic_spark" / "spark_hand" / "controller_receipt.json"
        if receipt_path.is_file():
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except Exception as exc:
        error = {"code": "CANARY_CONTROLLER_EXCEPTION", "stage": "synthetic_canary", "message": str(exc)}
    call_dir = case / "synthetic_spark" / "spark_hand" / "call"
    dispatch_path = call_dir / "dispatch.json"
    dispatch = json.loads(dispatch_path.read_text(encoding="utf-8")) if dispatch_path.is_file() else {}
    prompt_path = call_dir / "prompt.txt"
    prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.is_file() else ""
    exact_validator = runner.powershell_command(runner.validator_command("visible"))
    passed = bool(
        receipt
        and receipt.get("admitted")
        and receipt.get("changed") == ["src/solution.py"]
        and receipt.get("visible_validators", {}).get("visible", {}).get("passed")
        and receipt.get("spark_final_prose_used_for_admission") is False
        and dispatch.get("surface") == "app_inherited"
        and dispatch.get("output_schema") is None
        and "--output-schema" not in dispatch.get("command", [])
        and "--ignore-user-config" not in dispatch.get("command", [])
        and exact_validator in prompt
        and (case / "accepted" / "forbidden.txt").read_bytes() == b"preserve\n"
    )
    result = {
        "id": f"V223_SYNTHETIC_SPARK_{replicate:03d}",
        "passed": passed,
        "trial_id": trial,
        "model": "gpt-5.3-codex-spark",
        "benchmark_task_loaded": False,
        "capability_evidence": False,
        "error": error,
        "dispatch_sha256": runner.sha(dispatch_path) if dispatch_path.is_file() else None,
        "prompt_sha256": runner.sha(prompt_path) if prompt_path.is_file() else None,
        "controller_receipt_sha256": runner.sha(case / "synthetic_spark" / "spark_hand" / "controller_receipt.json") if receipt else None,
        "changed": receipt.get("changed") if receipt else None,
        "validator_passed": receipt.get("visible_validators", {}).get("visible", {}).get("passed") if receipt else False,
        "spark_exit_code": call.get("exit_code") if call else None,
        "usage": call.get("usage") if call else {},
    }
    runner.write(case / "canary_result.json", runner.canon(result))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--replicates", type=int, default=3)
    parser.add_argument("--suite-commit", required=True)
    args = parser.parse_args()
    if args.replicates < 1:
        raise SystemExit("replicates must be positive")
    cli_identity = runner.require_cli_identity()
    head_result = runner.git(["rev-parse", "HEAD"], ROOT)
    if head_result.returncode:
        raise SystemExit(head_result.stderr.decode(errors="replace"))
    observed_head = head_result.stdout.decode().strip()
    if args.suite_commit != observed_head:
        raise SystemExit(f"suite commit mismatch: requested {args.suite_commit}, observed {observed_head}")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    cases = []
    for replicate in range(1, args.replicates + 1):
        case = run_case(output, replicate)
        cases.append(case)
        if not case["passed"]:
            break
    summary = {
        "schema": "luna-sol-anchor-replication/spark-execution-canaries@2.2.3",
        "protocol_revision": "2.2.3",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "suite_commit": observed_head,
        "cli_identity": cli_identity,
        "model": "gpt-5.3-codex-spark",
        "surface": "app_inherited",
        "free_form": True,
        "output_schema": None,
        "requested_calls": args.replicates,
        "call_count": len(cases),
        "all_pass": len(cases) == args.replicates and all(case["passed"] for case in cases),
        "cases": cases,
        "benchmark_calls": 0,
        "benchmark_task_loaded": False,
        "capability_evidence": False,
    }
    runner.write(output / "summary.json", runner.canon(summary))
    print(json.dumps({"output": str(output), "summary": summary}, indent=2, sort_keys=True))
    return 0 if summary["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
