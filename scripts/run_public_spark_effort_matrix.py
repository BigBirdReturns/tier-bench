#!/usr/bin/env python3
"""Run and reduce the fixed public-synthetic Spark 5.3 effort matrix."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import py_compile
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
ROOT = REPO / "data/model_residue/spark_effort_public_v1"
TASK_ROOT = ROOT / "tasks"
RUN_ROOT = ROOT / "runs"
MODEL = "gpt-5.3-codex-spark"
TASKS = ("stable_unique", "merge_closed_ranges", "dependency_batches")
EFFORTS = ("low", "medium", "high")
REPLICATES = (1, 2, 3)
CODEX_DEFAULT = Path(os.environ.get(
    "SPARK_MATRIX_CODEX",
    r"C:\Users\BAM-Desktop\AppData\Local\Programs\OpenAI\Codex\bin\codex.exe",
))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_local_validator(task: str, candidate: Path) -> dict:
    validator = TASK_ROOT / task / "validator.py"
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    compile_result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(candidate)],
        capture_output=True,
        env=environment,
    )
    if compile_result.returncode == 0:
        validation = subprocess.run(
            [sys.executable, str(validator), str(candidate)],
            capture_output=True,
            env=environment,
        )
    else:
        validation = subprocess.CompletedProcess([], 99, b"", b"compile failed")
    return {
        "compile_exit_code": compile_result.returncode,
        "compile_stdout": compile_result.stdout.decode("utf-8", errors="replace"),
        "compile_stderr": compile_result.stderr.decode("utf-8", errors="replace"),
        "validator_exit_code": validation.returncode,
        "validator_stdout": validation.stdout.decode("utf-8", errors="replace"),
        "validator_stderr": validation.stderr.decode("utf-8", errors="replace"),
        "passed": compile_result.returncode == 0 and validation.returncode == 0,
    }


def self_test() -> None:
    expected_files = []
    for task in TASKS:
        directory = TASK_ROOT / task
        prompt = directory / "PROMPT.md"
        reference = directory / "reference.py"
        validator = directory / "validator.py"
        expected_files.extend((prompt, reference, validator))
        assert prompt.read_text(encoding="utf-8").startswith("Return only one complete Python source file")
        assert len(prompt.read_bytes()) < 2_000
        py_compile.compile(str(reference), doraise=True)
        py_compile.compile(str(validator), doraise=True)
        result = run_local_validator(task, reference)
        assert result["passed"], (task, result)
        with tempfile.TemporaryDirectory(prefix="spark-matrix-negative-") as temp:
            bad = Path(temp) / "candidate.py"
            bad.write_text("def wrong_name(value):\n    return value\n", encoding="utf-8")
            assert not run_local_validator(task, bad)["passed"], task
    assert all(path.is_file() for path in expected_files)
    assert len({sha256((TASK_ROOT / task / "PROMPT.md").read_bytes()) for task in TASKS}) == 3
    print("PASS public Spark matrix contract: 3 prompts, 3 reference passes, 3 negative controls")


def command(codex: Path, effort: str, cwd: Path, response_path: Path) -> list[str]:
    return [
        str(codex), "exec", "-",
        "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules",
        "--model", MODEL,
        "--config", f'model_reasoning_effort="{effort}"',
        "--config", 'web_search="disabled"',
        "--config", 'history.persistence="none"',
        "--config", 'approval_policy="never"',
        "--disable", "apps", "--disable", "plugins", "--disable", "browser_use",
        "--disable", "in_app_browser", "--disable", "computer_use",
        "--disable", "image_generation", "--disable", "goals",
        "--disable", "tool_suggest", "--disable", "multi_agent",
        "--sandbox", "read-only", "--ephemeral", "--json", "--color", "never",
        "--output-last-message", str(response_path), "--cd", str(cwd),
    ]


def parse_events(raw: bytes) -> dict:
    thread_id = None
    usage = {}
    event_count = 0
    parse_errors = 0
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            parse_errors += 1
            continue
        event_count += 1
        if event.get("type") == "thread.started":
            thread_id = event.get("thread_id")
        if event.get("type") == "turn.completed":
            usage = event.get("usage", {})
    return {
        "thread_id": thread_id,
        "usage": usage,
        "event_count": event_count,
        "event_parse_errors": parse_errors,
    }


def run_cell(codex: Path, task: str, effort: str, replicate: int) -> dict:
    prompt_path = TASK_ROOT / task / "PROMPT.md"
    prompt = prompt_path.read_bytes()
    cell = RUN_ROOT / effort / task / f"r{replicate}"
    if cell.exists():
        raise FileExistsError(f"refusing to overwrite sealed cell: {cell}")
    cell.mkdir(parents=True)
    started_at = utc_now()
    with tempfile.TemporaryDirectory(prefix=f"spark-public-{effort}-{task}-") as temp:
        cwd = Path(temp)
        response_path = cwd / "response.py"
        started = time.perf_counter()
        process = subprocess.run(
            command(codex, effort, cwd, response_path),
            input=prompt,
            capture_output=True,
        )
        wall_seconds = time.perf_counter() - started
        raw_response = response_path.read_bytes() if response_path.is_file() else b""
        events = parse_events(process.stdout)
        (cell / "events.jsonl").write_bytes(process.stdout)
        (cell / "stderr.txt").write_bytes(process.stderr)
        (cell / "candidate.py").write_bytes(raw_response)
    validation = run_local_validator(task, cell / "candidate.py")
    (cell / "validator_stdout.txt").write_text(validation["validator_stdout"], encoding="utf-8")
    (cell / "validator_stderr.txt").write_text(
        validation["compile_stderr"] + validation["validator_stderr"], encoding="utf-8"
    )
    result = {
        "schema_version": 1,
        "suite": "spark_effort_public_v1",
        "model": MODEL,
        "effort": effort,
        "task": task,
        "replicate": replicate,
        "started_at": started_at,
        "completed_at": utc_now(),
        "prompt_path": prompt_path.relative_to(REPO).as_posix(),
        "prompt_sha256": sha256(prompt),
        "prompt_bytes": len(prompt),
        "thread_id": events["thread_id"],
        "cli_exit_code": process.returncode,
        "wall_seconds": round(wall_seconds, 6),
        "usage": events["usage"],
        "event_count": events["event_count"],
        "event_parse_errors": events["event_parse_errors"],
        "candidate_sha256": sha256(raw_response),
        "candidate_bytes": len(raw_response),
        "compile_exit_code": validation["compile_exit_code"],
        "validator_exit_code": validation["validator_exit_code"],
        "passed": process.returncode == 0 and validation["passed"],
        "retry_count": 0,
        "cost_basis": "subscription-derived",
    }
    (cell / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def load_results(require_complete: bool = True) -> list[dict]:
    results = []
    expected = []
    for effort in EFFORTS:
        for task in TASKS:
            for replicate in REPLICATES:
                path = RUN_ROOT / effort / task / f"r{replicate}" / "result.json"
                expected.append(path)
                if path.is_file():
                    results.append(json.loads(path.read_text(encoding="utf-8")))
    if require_complete and len(results) != len(expected):
        missing = [path.relative_to(REPO).as_posix() for path in expected if not path.is_file()]
        raise ValueError(f"matrix incomplete: {len(results)}/27; missing {missing}")
    return results


def summarize() -> dict:
    results = load_results(require_complete=True)
    prompt_hashes = defaultdict(set)
    for row in results:
        prompt_hashes[row["task"]].add(row["prompt_sha256"])
    if any(len(values) != 1 for values in prompt_hashes.values()):
        raise ValueError("prompt bytes differed across cells")
    efforts = {}
    for effort in EFFORTS:
        rows = [row for row in results if row["effort"] == effort]
        total_tokens = [
            row.get("usage", {}).get("input_tokens", 0) + row.get("usage", {}).get("output_tokens", 0)
            for row in rows
        ]
        efforts[effort] = {
            "calls": len(rows),
            "passes": sum(row["passed"] for row in rows),
            "pass_rate": round(sum(row["passed"] for row in rows) / len(rows), 4),
            "per_task_passes": {
                task: sum(row["passed"] for row in rows if row["task"] == task) for task in TASKS
            },
            "median_wall_seconds": round(statistics.median(row["wall_seconds"] for row in rows), 6),
            "total_wall_seconds": round(sum(row["wall_seconds"] for row in rows), 6),
            "median_total_tokens": statistics.median(total_tokens),
            "total_tokens": sum(total_tokens),
            "input_tokens": sum(row.get("usage", {}).get("input_tokens", 0) for row in rows),
            "cached_input_tokens": sum(row.get("usage", {}).get("cached_input_tokens", 0) for row in rows),
            "output_tokens": sum(row.get("usage", {}).get("output_tokens", 0) for row in rows),
            "reasoning_output_tokens": sum(row.get("usage", {}).get("reasoning_output_tokens", 0) for row in rows),
            "cli_failures": sum(row["cli_exit_code"] != 0 for row in rows),
            "validator_failures": sum(row["validator_exit_code"] != 0 for row in rows),
        }
    failure_shapes = Counter()
    for row in results:
        if row["passed"]:
            continue
        if row["cli_exit_code"] != 0:
            failure_shapes["provider_or_cli_failure"] += 1
        elif row["compile_exit_code"] != 0:
            candidate = RUN_ROOT / row["effort"] / row["task"] / f"r{row['replicate']}" / "candidate.py"
            if candidate.read_bytes().lstrip().startswith(b"```"):
                failure_shapes["markdown_fence_protocol_violation"] += 1
            else:
                failure_shapes["non_compiling_candidate"] += 1
        else:
            failure_shapes["validator_rejection"] += 1
    low = efforts["low"]
    effort_vs_low = {}
    for effort in ("medium", "high"):
        item = efforts[effort]
        effort_vs_low[effort] = {
            "pass_delta": item["passes"] - low["passes"],
            "median_wall_delta_percent": round(
                (item["median_wall_seconds"] / low["median_wall_seconds"] - 1) * 100, 2
            ),
            "median_total_tokens_delta_percent": round(
                (item["median_total_tokens"] / low["median_total_tokens"] - 1) * 100, 2
            ),
            "total_tokens_delta_percent": round(
                (item["total_tokens"] / low["total_tokens"] - 1) * 100, 2
            ),
        }
    summary = {
        "schema_version": 1,
        "suite": "spark_effort_public_v1",
        "model": MODEL,
        "design": "3 clean-room public-synthetic tasks x 3 efforts x 3 fresh replicates; no retries",
        "scientific_calls": len(results),
        "prompt_hashes": {task: next(iter(prompt_hashes[task])) for task in TASKS},
        "efforts": efforts,
        "effort_vs_low": effort_vs_low,
        "failure_shapes": dict(failure_shapes),
        "scope": "public-synthetic effort comparison; not private Tier-Bench hidden-grade capability evidence",
    }
    (ROOT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    rows = [
        "# Spark 5.3 public effort matrix v1",
        "",
        summary["design"] + ".",
        "",
        "| Effort | Passes | Median wall | Median tokens | Total tokens |",
        "|---|---:|---:|---:|---:|",
    ]
    for effort in EFFORTS:
        item = efforts[effort]
        rows.append(
            f"| {effort} | {item['passes']}/9 | {item['median_wall_seconds']:.3f}s | "
            f"{item['median_total_tokens']:.1f} | {item['total_tokens']:,} |"
        )
    rows.extend((
        "",
        "All task prompts were byte-identical across efforts and replicates. Every cell is first-pass only with zero retries.",
        "",
        "This is public-synthetic evidence and remains separate from the blocked private hidden-grade Spark cell.",
        "",
    ))
    (ROOT / "SUMMARY.md").write_text("\n".join(rows), encoding="utf-8")
    return summary


def verify() -> None:
    results = load_results(require_complete=True)
    thread_ids = set()
    for row in results:
        prompt = TASK_ROOT / row["task"] / "PROMPT.md"
        cell = RUN_ROOT / row["effort"] / row["task"] / f"r{row['replicate']}"
        candidate = cell / "candidate.py"
        raw_events = (cell / "events.jsonl").read_bytes()
        events = parse_events(raw_events)
        assert sha256(prompt.read_bytes()) == row["prompt_sha256"], row
        assert sha256(candidate.read_bytes()) == row["candidate_sha256"], row
        assert events["thread_id"] == row["thread_id"], row
        assert events["usage"] == row["usage"], row
        assert events["event_count"] == row["event_count"], row
        assert events["event_parse_errors"] == row["event_parse_errors"] == 0, row
        assert row["thread_id"] and row["thread_id"] not in thread_ids, row
        thread_ids.add(row["thread_id"])
        validation = run_local_validator(row["task"], candidate)
        actual_pass = row["cli_exit_code"] == 0 and validation["passed"]
        assert actual_pass == row["passed"], row
        assert row["retry_count"] == 0, row
    assert len(thread_ids) == 27
    print("PASS sealed Spark matrix: 27 cells, 27 unique threads, hashes and grades reproduced")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--summarize", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--max-new-calls", type=int, default=None)
    parser.add_argument("--codex", type=Path, default=CODEX_DEFAULT)
    args = parser.parse_args()
    if not (args.self_test or args.run or args.summarize or args.verify):
        parser.error("choose --self-test, --run, --summarize, or --verify")
    if args.self_test:
        self_test()
    if args.verify:
        verify()
    if args.run:
        if not args.codex.is_file() and shutil.which(str(args.codex)) is None:
            raise FileNotFoundError(args.codex)
        new_calls = 0
        stop = False
        for effort in EFFORTS:
            for task in TASKS:
                for replicate in REPLICATES:
                    result_path = RUN_ROOT / effort / task / f"r{replicate}" / "result.json"
                    if result_path.exists() and args.resume:
                        print(f"SKIP sealed {effort}/{task}/r{replicate}", flush=True)
                        continue
                    if args.max_new_calls is not None and new_calls >= args.max_new_calls:
                        stop = True
                        break
                    result = run_cell(args.codex, task, effort, replicate)
                    new_calls += 1
                    tokens = result.get("usage", {}).get("input_tokens", 0) + result.get("usage", {}).get("output_tokens", 0)
                    print(
                        f"DONE {effort}/{task}/r{replicate} pass={result['passed']} "
                        f"wall={result['wall_seconds']:.3f}s tokens={tokens}",
                        flush=True,
                    )
                if stop:
                    break
            if stop:
                break
        if len(load_results(require_complete=False)) == 27:
            summary = summarize()
            print(json.dumps(summary["efforts"], indent=2), flush=True)
        else:
            print(f"PARTIAL sealed={len(load_results(require_complete=False))}/27", flush=True)
    elif args.summarize:
        print(json.dumps(summarize(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
