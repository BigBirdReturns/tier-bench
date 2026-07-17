#!/usr/bin/env python3
"""Run matched Sol versus Spark validator-gated races."""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--controller", required=True)
    parser.add_argument("--codex-path", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--replicates", type=int, default=3)
    parser.add_argument(
        "--tasks",
        default="",
        help="Optional comma-separated fixture names; default runs all",
    )
    return parser.parse_args()


def controller_command(
    python: str,
    controller: str,
    codex: str,
    repo: Path,
    fixture: dict,
    model: str,
    attempts: int,
) -> list[str]:
    command = [
        python,
        controller,
        "--repo",
        str(repo),
        "--task",
        fixture["task"],
        "--target",
        fixture["target"],
    ]
    for context in fixture["contexts"]:
        command.extend(("--context", context))
    command.extend(
        (
            "--skip-local",
            "--cloud-candidate",
            "--cloud-model",
            model,
            "--cloud-effort",
            "low",
            "--cloud-attempts",
            str(attempts),
            "--codex-path",
            codex,
            "--",
            *fixture["validator"],
        )
    )
    return command


def run_pair(
    python: str,
    controller: str,
    codex: str,
    fixture_root: Path,
    fixture: dict,
    replicate: int,
    output: Path,
) -> list[dict]:
    pair_root = output / fixture["name"] / f"replicate_{replicate:02d}"
    racers = {
        "sol": ("gpt-5.6-sol", 1),
        "spark": ("gpt-5.3-codex-spark", 3),
    }
    processes = {}
    started = time.monotonic()
    for racer, (model, attempts) in racers.items():
        repo = pair_root / racer
        shutil.copytree(fixture_root / fixture["name"], repo)
        process = subprocess.Popen(
            controller_command(python, controller, codex, repo, fixture, model, attempts),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        processes[racer] = (process, repo, model)

    completed = {}
    while len(completed) < len(processes):
        for racer, (process, repo, model) in processes.items():
            if racer not in completed and process.poll() is not None:
                completed[racer] = time.monotonic() - started
        time.sleep(0.01)

    results = []
    for racer, (process, repo, model) in processes.items():
        stdout, stderr = process.communicate()
        (repo / "controller.stdout.json").write_text(stdout, encoding="utf-8")
        (repo / "controller.stderr.txt").write_text(stderr, encoding="utf-8")
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = {"status": "invalid_controller_output"}
        validator = subprocess.run(
            fixture["validator"],
            cwd=repo,
            capture_output=True,
            text=True,
            shell=False,
        )
        (repo / "independent-validator.txt").write_text(
            validator.stdout + validator.stderr,
            encoding="utf-8",
        )
        results.append(
            {
                "task": fixture["name"],
                "replicate": replicate,
                "racer": racer,
                "model": model,
                "elapsed_seconds": round(completed[racer], 3),
                "controller_exit": process.returncode,
                "independent_validator_exit": validator.returncode,
                "passed": process.returncode == 0 and validator.returncode == 0,
                "tokens": payload.get("cloud_tokens"),
                "refinement_attempt": payload.get("refinement_attempt"),
                "payload": payload,
            }
        )
    return results


def summarize(rows: list[dict]) -> dict:
    summary = {"arms": {}, "race": {}}
    for racer in ("sol", "spark"):
        arm = [row for row in rows if row["racer"] == racer]
        passed = [row for row in arm if row["passed"]]
        summary["arms"][racer] = {
            "runs": len(arm),
            "passes": len(passed),
            "pass_rate": len(passed) / len(arm),
            "median_seconds": statistics.median(row["elapsed_seconds"] for row in arm),
            "median_tokens": statistics.median(row["tokens"] for row in arm if row["tokens"] is not None),
            "total_tokens": sum(row["tokens"] or 0 for row in arm),
        }
    pairs = {}
    for row in rows:
        pairs.setdefault((row["task"], row["replicate"]), []).append(row)
    winners = []
    first_pass = []
    for pair in pairs.values():
        valid = [row for row in pair if row["passed"]]
        if valid:
            winner = min(valid, key=lambda row: row["elapsed_seconds"])
            winners.append(winner["racer"])
            first_pass.append(winner["elapsed_seconds"])
    summary["race"] = {
        "pairs": len(pairs),
        "pairs_with_pass": len(first_pass),
        "sol_wins": winners.count("sol"),
        "spark_wins": winners.count("spark"),
        "median_time_to_first_pass": statistics.median(first_pass),
    }
    return summary


def main() -> int:
    args = parse_args()
    here = Path(__file__).resolve().parent
    fixture_root = here / "fixtures"
    fixtures = json.loads((fixture_root / "manifest.json").read_text(encoding="utf-8"))
    if args.tasks:
        selected = {name.strip() for name in args.tasks.split(",") if name.strip()}
        fixtures = [fixture for fixture in fixtures if fixture["name"] in selected]
        missing = selected - {fixture["name"] for fixture in fixtures}
        if missing:
            raise ValueError(f"unknown tasks: {', '.join(sorted(missing))}")
    output = Path(args.output).resolve()
    if output.exists():
        raise ValueError(f"output already exists: {output}")
    output.mkdir(parents=True)
    rows = []
    results_path = output / "results.jsonl"
    for fixture in fixtures:
        for replicate in range(1, args.replicates + 1):
            pair = run_pair(
                sys.executable,
                args.controller,
                args.codex_path,
                fixture_root,
                fixture,
                replicate,
                output,
            )
            rows.extend(pair)
            with results_path.open("a", encoding="utf-8") as handle:
                for row in pair:
                    handle.write(json.dumps(row) + "\n")
            winner = min(
                (row for row in pair if row["passed"]),
                key=lambda row: row["elapsed_seconds"],
                default=None,
            )
            print(
                json.dumps(
                    {
                        "task": fixture["name"],
                        "replicate": replicate,
                        "winner": winner["racer"] if winner else None,
                        "first_pass_seconds": winner["elapsed_seconds"] if winner else None,
                    }
                ),
                flush=True,
            )
    summary = summarize(rows)
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"race benchmark: {exc}", file=sys.stderr)
        raise SystemExit(2)
