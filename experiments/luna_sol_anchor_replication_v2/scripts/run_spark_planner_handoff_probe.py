#!/usr/bin/env python3
"""Probe a planner-authored, free-form Spark execution handoff on real code."""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("luna_run_v222_handoff_probe", ROOT / "run_v2.py")
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

STUB = '''def summarize(records):
    """Return sorted per-account totals for eligible records."""
    raise NotImplementedError
'''

VERIFY = '''import copy
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
print("VERIFY_OK")
'''


def canon(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def write(path: Path, value: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value.encode() if isinstance(value, str) else value)


def git(subject: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=subject, capture_output=True, timeout=60)


def usage(events: bytes) -> dict[str, object]:
    for line in reversed(events.splitlines()):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.completed":
            return event.get("usage") or {}
    return {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--replicates", type=int, default=3)
    args = parser.parse_args()
    cli_identity = runner.require_cli_identity()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    cases = []
    for replicate in range(1, args.replicates + 1):
        case = output / f"replicate_{replicate:02d}"
        subject = case / "subject"
        write(subject / "src" / "__init__.py", "")
        write(subject / "src" / "solution.py", STUB)
        write(subject / "verify.py", VERIFY)
        write(subject / "forbidden.txt", "preserve\n")
        for command in (
            ("init", "-q"),
            ("config", "user.name", "Spark planner handoff probe"),
            ("config", "user.email", "probe@example.invalid"),
            ("add", "."),
            ("commit", "-qm", "probe baseline"),
        ):
            result = git(subject, *command)
            if result.returncode:
                raise RuntimeError(result.stderr.decode(errors="replace"))
        prompt = f'''PLANNER HANDOFF\n\nObjective: Implement summarize(records) in src/solution.py. Include only records whose eligible field is true, sum integer amount values by account, and return a list of objects sorted by account. Do not mutate the input. Empty input returns an empty list.\n\nAllowed edit: src/solution.py\nForbidden edits: verify.py, forbidden.txt, src/__init__.py\nAcceptance command: & "{runner.PREFERRED_PYTHON}" verify.py\n\nExecute the plan now. Use the acceptance command after editing and do not finish until it exits 0. Do not produce a JSON report; give a concise normal final response.'''
        final_path = case / "final_response.txt"
        cli_command = [
            str(runner.CLI), "exec", "--model", "gpt-5.3-codex-spark",
            "--sandbox", "workspace-write", "--ephemeral", "--json",
            "--output-last-message", str(final_path),
            "--config", 'model_reasoning_effort="low"',
            "--config", 'web_search="disabled"',
            "--config", "sandbox_workspace_write.network_access=false",
            "--config", "features.multi_agent=false",
            "--config", 'approval_policy="never"',
            "-C", str(subject), "-",
        ]
        write(case / "prompt.txt", prompt + "\n")
        write(case / "dispatch.json", canon({"replicate": replicate, "free_form": True, "planner_handoff": True, "output_schema": None, "cli_identity": cli_identity, "command": cli_command}))
        started = time.time()
        result = subprocess.run(cli_command, cwd=subject, input=prompt.encode(), capture_output=True, timeout=300)
        duration = round(time.time() - started, 3)
        write(case / "events.jsonl", result.stdout)
        write(case / "stderr.txt", result.stderr)
        validation = subprocess.run([str(runner.PREFERRED_PYTHON), "verify.py"], cwd=subject, capture_output=True, timeout=60)
        changed = sorted(line for line in git(subject, "diff", "--name-only").stdout.decode().splitlines() if line)
        passed = result.returncode == 0 and validation.returncode == 0 and changed == ["src/solution.py"] and (subject / "forbidden.txt").read_bytes() == b"preserve\n"
        receipt = {
            "replicate": replicate,
            "passed": passed,
            "exit_code": result.returncode,
            "duration_seconds": duration,
            "changed": changed,
            "validator_exit_code": validation.returncode,
            "validator_stdout": validation.stdout.decode(errors="replace"),
            "validator_stderr": validation.stderr.decode(errors="replace"),
            "usage": usage(result.stdout),
            "capability_evidence": False,
        }
        write(case / "receipt.json", canon(receipt))
        cases.append(receipt)
    summary = {
        "schema": "luna-sol-anchor-replication/spark-planner-handoff-probe@1",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": "gpt-5.3-codex-spark",
        "surface": "app_inherited",
        "free_form": True,
        "planner_handoff": True,
        "output_schema": None,
        "cli_identity": cli_identity,
        "call_count": len(cases),
        "passed": sum(1 for case in cases if case["passed"]),
        "cases": cases,
        "benchmark_calls": 0,
        "capability_evidence": False,
    }
    write(output / "summary.json", canon(summary))
    print(json.dumps({"output": str(output), "summary": summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
