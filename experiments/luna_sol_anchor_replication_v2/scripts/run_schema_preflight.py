#!/usr/bin/env python3
"""Run the single administrative production-schema acceptance proof."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "prompts" / "schemas"
CLI = Path(r"C:\Users\BAM-Desktop\AppData\Local\OpenAI\Codex\bin\3135b80b111fd431\codex.exe")
PROMPT = "Return the smallest neutral object satisfying all three required properties: initial_planner, continuation_planner, and spark_report. Use the exact action values required by their embedded schemas and empty arrays where allowed."

sys.path.insert(0, str(ROOT.parents[1] / "scripts"))
from validate_strict_output_schemas import validate_instance, validate_schema  # noqa: E402


def canon(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def usage(stdout: bytes) -> dict[str, object]:
    found: dict[str, object] = {}
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.completed":
            found = event.get("usage") or found
        if event.get("type") == "event_msg" and (event.get("payload") or {}).get("type") == "token_count":
            found = ((event.get("payload") or {}).get("info") or {}).get("total_token_usage") or found
    return found


def main(argv: list[str] | None = None) -> int:
    if not CLI.is_file():
        raise SystemExit(f"missing pinned CLI: {CLI}")
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) != 1:
        raise SystemExit("usage: run_schema_preflight.py OUTPUT_DIR")
    output = Path(argv[0]).resolve()
    output.mkdir(parents=True, exist_ok=False)
    empty_repo = output / "empty_git_repo"
    empty_repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=empty_repo, check=True)

    defs = {
        "initial_planner": json.loads((SCHEMAS / "planner_initial.schema.json").read_text(encoding="utf-8")),
        "continuation_planner": json.loads((SCHEMAS / "planner_continuation.schema.json").read_text(encoding="utf-8")),
        "spark_report": json.loads((SCHEMAS / "spark.schema.json").read_text(encoding="utf-8")),
    }
    union = {
        "$defs": defs,
        "additionalProperties": False,
        "properties": {
            "initial_planner": {"$ref": "#/$defs/initial_planner"},
            "continuation_planner": {"$ref": "#/$defs/continuation_planner"},
            "spark_report": {"$ref": "#/$defs/spark_report"},
        },
        "required": ["initial_planner", "continuation_planner", "spark_report"],
        "type": "object",
    }
    union_path = output / "union.schema.json"
    union_path.write_bytes(canon(union))
    strict_errors = validate_schema(union, str(union_path))
    (output / "prompt.txt").write_text(PROMPT, encoding="utf-8", newline="\n")
    final_path = output / "final.json"
    command = [
        str(CLI), "exec", "--model", "gpt-5.3-codex-spark", "--sandbox", "read-only", "--ephemeral", "--json",
        "--output-last-message", str(final_path), "--output-schema", str(union_path),
        "--config", 'model_reasoning_effort="low"', "--config", 'model_reasoning_summary="none"',
        "--config", "model_supports_reasoning_summaries=false", "--config", 'web_search="disabled"',
        "--config", "sandbox_workspace_write.network_access=false", "--config", "agents.max_depth=0",
        "--config", "agents.max_threads=1", "--config", 'history.persistence="none"',
        "--config", "hide_agent_reasoning=true", "--config", 'approval_policy="never"', "-C", str(empty_repo), "-",
    ]
    (output / "dispatch.json").write_bytes(canon({
        "started_at": now(), "model": "gpt-5.3-codex-spark", "effort": "low", "sandbox": "read-only",
        "cwd": str(empty_repo), "command": command, "prompt_sha256": sha(output / "prompt.txt"),
        "schema_sha256": sha(union_path), "schema": "union.schema.json", "strict_schema_errors": strict_errors,
    }))
    result = subprocess.run(command, cwd=empty_repo, input=PROMPT.encode(), capture_output=True, timeout=900)
    (output / "events.jsonl").write_bytes(result.stdout)
    (output / "stderr.txt").write_bytes(result.stderr)
    final_bytes = final_path.read_bytes() if final_path.is_file() else b""
    parsed: object | None = None
    parse_error: str | None = None
    if final_bytes:
        try:
            parsed = json.loads(final_bytes)
        except Exception as exc:
            parse_error = str(exc)
    instance_errors = validate_instance(parsed, union) if parsed is not None else ["no final JSON"]
    completion = {
        "completed_at": now(), "exit_code": result.returncode, "timed_out": False,
        "stdout_sha256": sha(output / "events.jsonl"), "stderr_sha256": sha(output / "stderr.txt"),
        "final_response_sha256": sha_bytes(final_bytes), "usage": usage(result.stdout),
        "final_present": bool(final_bytes), "parse_error": parse_error, "schema_valid": not strict_errors and not instance_errors,
        "schema_errors": strict_errors, "instance_errors": instance_errors,
    }
    (output / "completion.json").write_bytes(canon(completion))
    if parsed is not None:
        (output / "final_parsed.json").write_bytes(canon(parsed))
    print(json.dumps({"output": str(output), "completion": completion}, indent=2, sort_keys=True))
    return 0 if completion["schema_valid"] and result.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
