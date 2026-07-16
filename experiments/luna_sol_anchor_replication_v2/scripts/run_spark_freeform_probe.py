#!/usr/bin/env python3
"""Run an unscored free-form Spark prompt-strategy probe outside the benchmark."""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "run_v2.py"
spec = importlib.util.spec_from_file_location("luna_run_v222_freeform_probe", RUNNER_PATH)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

VERIFY = r'''$bytes = [System.IO.File]::ReadAllBytes((Join-Path $PWD "value.txt"))
if ($bytes.Length -eq 2 -and $bytes[0] -eq 49 -and $bytes[1] -eq 10) {
    Write-Output "VERIFY_OK"
    exit 0
}
Write-Error ("VERIFY_FAIL bytes=" + (($bytes | ForEach-Object { $_.ToString("X2") }) -join " "))
exit 1
'''

PROMPTS = {
    "minimal": """Change value.txt from 0 to 1. Make no other edits. Finish when value.txt contains exactly the character 1 followed by one LF newline.""",
    "self_verify": """Change value.txt from 0 to 1. Make no other edits. Before finishing, inspect the raw bytes yourself and confirm they are exactly hex 31 0A. If they are not, correct them. You may choose any editing and inspection method.""",
    "local_validator": """Change value.txt from 0 to 1. Do not edit forbidden.txt or verify.ps1. After editing, run `powershell -NoProfile -ExecutionPolicy Bypass -File .\\verify.ps1`. Do not finish until that command exits 0. You may choose any editing method.""",
}


def canon(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def write(path: Path, value: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value.encode() if isinstance(value, str) else value)


def git(subject: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=subject, capture_output=True, timeout=60)


def usage(events: bytes) -> dict[str, object]:
    found: dict[str, object] = {}
    for line in events.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.completed":
            found = event.get("usage") or found
    return found


def run_case(output: Path, strategy: str, replicate: int, surface: str, cli_identity: dict[str, object]) -> dict[str, object]:
    case = output / f"{strategy}_{replicate:02d}"
    subject = case / "subject"
    subject.mkdir(parents=True)
    write(subject / "value.txt", b"0\n")
    write(subject / "forbidden.txt", b"preserve\n")
    write(subject / "verify.ps1", VERIFY)
    for args in (
        ("init", "-q"),
        ("config", "user.name", "Spark free-form probe"),
        ("config", "user.email", "probe@example.invalid"),
        ("add", "."),
        ("commit", "-qm", "probe baseline"),
    ):
        result = git(subject, *args)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors="replace"))

    prompt = PROMPTS[strategy]
    final_path = case / "final_response.txt"
    command = [
        str(runner.CLI),
        "exec",
        "--model", "gpt-5.3-codex-spark",
        "--sandbox", "workspace-write",
        "--ephemeral",
    ]
    if surface == "isolated":
        command.extend(["--ignore-user-config", "--ignore-rules"])
    command.extend([
        "--json",
        "--output-last-message", str(final_path),
        "--config", 'model_reasoning_effort="low"',
        "--config", 'web_search="disabled"',
        "--config", "sandbox_workspace_write.network_access=false",
        "--config", "features.multi_agent=false",
        "--config", 'approval_policy="never"',
        "-C", str(subject),
        "-",
    ])
    write(case / "prompt.txt", prompt + "\n")
    write(case / "dispatch.json", canon({
        "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "strategy": strategy,
        "replicate": replicate,
        "surface": surface,
        "model": "gpt-5.3-codex-spark",
        "effort": "low",
        "free_form": True,
        "output_schema": None,
        "cli_identity": cli_identity,
        "command": command,
    }))
    started = time.time()
    result = subprocess.run(command, cwd=subject, input=prompt.encode(), capture_output=True, timeout=300)
    duration = round(time.time() - started, 3)
    write(case / "events.jsonl", result.stdout)
    write(case / "stderr.txt", result.stderr)
    value = (subject / "value.txt").read_bytes()
    forbidden = (subject / "forbidden.txt").read_bytes()
    verifier = (subject / "verify.ps1").read_text(encoding="utf-8")
    changed = sorted(line for line in git(subject, "diff", "--name-only").stdout.decode().splitlines() if line)
    passed = result.returncode == 0 and value == b"1\n" and forbidden == b"preserve\n" and verifier == VERIFY and changed == ["value.txt"]
    receipt = {
        "strategy": strategy,
        "replicate": replicate,
        "surface": surface,
        "passed": passed,
        "exit_code": result.returncode,
        "duration_seconds": duration,
        "value_hex": value.hex(" "),
        "forbidden_preserved": forbidden == b"preserve\n",
        "verifier_preserved": verifier == VERIFY,
        "changed": changed,
        "usage": usage(result.stdout),
        "capability_evidence": False,
    }
    write(case / "receipt.json", canon(receipt))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--surface", choices=("isolated", "app_inherited"), default="isolated")
    parser.add_argument("--replicates", type=int, default=3)
    args = parser.parse_args()
    cli_identity = runner.require_cli_identity()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    cases = [run_case(output, strategy, replicate, args.surface, cli_identity) for strategy in PROMPTS for replicate in range(1, args.replicates + 1)]
    summary = {
        "schema": "luna-sol-anchor-replication/spark-freeform-prompt-probe@1",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": "gpt-5.3-codex-spark",
        "effort": "low",
        "cli_identity": cli_identity,
        "call_count": len(cases),
        "free_form": True,
        "output_schema": None,
        "surface": args.surface,
        "strategies": {
            strategy: {
                "passed": sum(1 for case in cases if case["strategy"] == strategy and case["passed"]),
                "total": sum(1 for case in cases if case["strategy"] == strategy),
            }
            for strategy in PROMPTS
        },
        "cases": cases,
        "capability_evidence": False,
        "benchmark_calls": 0,
    }
    write(output / "summary.json", canon(summary))
    print(json.dumps({"output": str(output), "summary": summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
