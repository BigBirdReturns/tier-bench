#!/usr/bin/env python3
"""Build the offline cross-repository model residue index from real evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

LOCAL_FIRST_FILES = (
    "BENCHMARKS.md",
    "benchmarks/ROBUST_BASELINE.md",
    "benchmarks/REPO_RELAY.md",
    "benchmarks/REVIEW_QUALITY.md",
    "local_first.py",
    "benchmarks/run_races.py",
)
TOKEN_PARITY_FILES = (
    "RESULT.md",
    "robust-race-20260717T1340/results.jsonl",
    "robust-race-hard-20260717T1350/results.jsonl",
    "relay-run-eager-20260717T1450/summary.json",
    "relay-review-run-20260717T1520/summary.json",
    "review-quality-run-20260717T1550/summary.json",
    "review-quality-run-r2-20260717T1610/summary.json",
)


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def tracked_repo_file(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f"missing residue file: {path}")
    relative = path.relative_to(REPO).as_posix()
    if subprocess.run(
        ["git", "-c", f"safe.directory={REPO.as_posix()}", "-C", str(REPO),
         "ls-files", "--error-unmatch", relative],
        capture_output=True,
    ).returncode != 0:
        raise ValueError(f"residue file is present but not tracked: {path}")
    return {"path": relative, "sha256": sha_file(path), "bytes": path.stat().st_size}


def git_commit(repo: Path) -> str:
    return subprocess.run(
        ["git", "-c", f"safe.directory={repo.as_posix()}", "-C", str(repo),
         "rev-parse", "HEAD"], check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def snapshot_source(root: Path, rel: str, namespace: str, write: bool) -> dict:
    source = root / rel
    data = source.read_bytes()
    destination = REPO / "data/model_residue/sources" / namespace / rel
    if write:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    elif not destination.is_file() or destination.read_bytes() != data:
        raise ValueError(f"snapshot drift: {destination}")
    elif subprocess.run(
        ["git", "-c", f"safe.directory={REPO.as_posix()}", "-C", str(REPO),
         "ls-files", "--error-unmatch", destination.relative_to(REPO).as_posix()],
        capture_output=True,
    ).returncode != 0:
        raise ValueError(f"snapshot is present but not tracked: {destination}")
    return {
        "source_id": f"{namespace}:{rel.replace(chr(92), '/')}",
        "snapshot_path": destination.relative_to(REPO).as_posix(),
        "sha256": sha_bytes(data),
        "bytes": len(data),
    }


def robust_result(rows: list[dict]) -> dict:
    arms = {}
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["racer"]].append(row)
    for racer, values in sorted(grouped.items()):
        arms[racer] = {
            "model": values[0]["model"],
            "runs": len(values),
            "passes": sum(bool(row["passed"]) for row in values),
            "median_seconds": statistics.median(row["elapsed_seconds"] for row in values),
            "median_tokens": statistics.median(row["tokens"] for row in values),
            "total_tokens": sum(row["tokens"] for row in values),
            "refinement_attempts": sorted(set(row["refinement_attempt"] for row in values)),
        }
    pairs = defaultdict(dict)
    for row in rows:
        pairs[(row["task"], row["replicate"])][row["racer"]] = row
    wins = Counter()
    for pair in pairs.values():
        valid = [row for row in pair.values() if row["passed"]]
        if valid:
            wins[min(valid, key=lambda row: row["elapsed_seconds"])["racer"]] += 1
    spark = arms["spark"]
    sol = arms["sol"]
    return {
        "design": "six deterministic single-file Python tasks, three matched replicates",
        "arms": arms,
        "paired_wins": dict(wins),
        "pairs": len(pairs),
        "spark_median_wall_reduction_percent": round(
            (1 - spark["median_seconds"] / sol["median_seconds"]) * 100, 2
        ),
        "spark_median_token_reduction_percent": round(
            (1 - spark["median_tokens"] / sol["median_tokens"]) * 100, 2
        ),
        "scope": "first-pass bounded execution; no measured repair-loop quality",
    }


def route_rows(report: str) -> list[dict]:
    rows = []
    in_table = False
    for line in report.splitlines():
        if line.startswith("| Route |"):
            in_table = True
            continue
        if in_table and line.startswith("| ---"):
            continue
        if in_table and line.startswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) == 5:
                rows.append(dict(zip(
                    ("route", "model_tokens", "cloud_tokens", "observed_wall", "gain_vs_direct"),
                    cells,
                )))
            continue
        if in_table:
            break
    return rows


def summarize_run(path: Path) -> dict:
    run = json.loads(path.read_text(encoding="utf-8"))
    outcomes = Counter(
        trial.get("verdict", {}).get("outcome", "missing") for trial in run.get("trials", [])
    )
    tokens = {
        "input": sum(trial.get("spend", {}).get("input_tokens", 0) for trial in run.get("trials", [])),
        "output": sum(trial.get("spend", {}).get("output_tokens", 0) for trial in run.get("trials", [])),
    }
    summary = {
        "run_id": run["run_id"],
        "run_path": path.relative_to(REPO).as_posix(),
        "run_sha256": sha_file(path),
        "status": run["status"],
        "measurement_claim": run["measurement_claim"],
        "engine": run["engine"],
        "source_commit": run["pairing"]["source_commit"],
        "rung_bindings": run["rung_bindings"],
        "trial_count": len(run.get("trials", [])),
        "outcomes": dict(outcomes),
        "tokens": tokens,
        "decisions": run.get("decisions", []),
        "gap": run["burden"]["gap"],
    }
    report = REPO / "data/orchestration/runs" / run["run_id"] / "REPORT.md"
    if report.is_file():
        summary["report"] = {
            "path": report.relative_to(REPO).as_posix(),
            "sha256": sha_file(report),
            "text": report.read_text(encoding="utf-8"),
        }
    return summary


def spark_effort_matrix() -> dict:
    root = REPO / "data/model_residue/spark_effort_public_v1"
    summary_path = root / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    cells = []
    for result_path in sorted((root / "runs").glob("*/*/r*/result.json")):
        result = json.loads(result_path.read_text(encoding="utf-8"))
        cell_dir = result_path.parent
        artifacts = [
            tracked_repo_file(cell_dir / name)
            for name in (
                "result.json", "events.jsonl", "stderr.txt", "candidate.py",
                "validator_stdout.txt", "validator_stderr.txt",
            )
        ]
        cells.append({
            "effort": result["effort"],
            "task": result["task"],
            "replicate": result["replicate"],
            "passed": result["passed"],
            "thread_id": result["thread_id"],
            "usage": result["usage"],
            "wall_seconds": result["wall_seconds"],
            "artifacts": artifacts,
        })
    if len(cells) != 27:
        raise ValueError(f"Spark effort matrix incomplete: {len(cells)}/27")
    administrative = []
    for failure_dir in sorted((root / "administrative_failures").glob("*")):
        if not failure_dir.is_dir():
            continue
        administrative.extend(
            tracked_repo_file(failure_dir / name)
            for name in (
                "result.json", "events.jsonl", "stderr.txt", "candidate.py",
                "validator_stdout.txt", "validator_stderr.txt",
            )
        )
    canary_dir = root / "administrative_canary/literal_ok_001"
    canary = [
        tracked_repo_file(canary_dir / name)
        for name in ("manifest.json", "prompt.txt", "events.jsonl", "response.txt", "stderr.txt")
    ]
    return {
        "summary_receipt": tracked_repo_file(summary_path),
        "summary": summary,
        "cells": cells,
        "administrative_failure_artifacts": administrative,
        "administrative_canary_artifacts": canary,
    }


def fable_effort_canary() -> dict:
    root = REPO / "data/model_residue/fable_effort_public_v1"
    canary = root / "canary_20260718T012100Z/replicate_001/fable_hand"
    surface_path = root / "FABLE_EXECUTION_SURFACE_FREEZE.json"
    boundary_path = canary / "boundary_observation.json"
    completion_path = canary / "call/completion.json"
    outcome_path = canary / "outcome.json"
    surface = json.loads(surface_path.read_text(encoding="utf-8"))
    boundary = json.loads(boundary_path.read_text(encoding="utf-8"))
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
    relative_files = (
        "FABLE_EXECUTION_SURFACE_FREEZE.json",
        "canary_20260718T012100Z/replicate_001/fable_hand/boundary_observation.json",
        "canary_20260718T012100Z/replicate_001/fable_hand/call/completion.json",
        "canary_20260718T012100Z/replicate_001/fable_hand/call/dispatch.json",
        "canary_20260718T012100Z/replicate_001/fable_hand/call/final_response.txt",
        "canary_20260718T012100Z/replicate_001/fable_hand/call/prompt.txt",
        "canary_20260718T012100Z/replicate_001/fable_hand/call/stderr.txt",
        "canary_20260718T012100Z/replicate_001/fable_hand/call/stdout_raw.txt",
        "canary_20260718T012100Z/replicate_001/fable_hand/candidate.patch",
        "canary_20260718T012100Z/replicate_001/fable_hand/outcome.json",
    )
    return {
        "measurement_class": "administrative_transport_canary",
        "model": surface["model"],
        "effort": "low",
        "surface": surface["surface"],
        "passed": outcome["verdict"] == "pass" and all(outcome["checks"].values()),
        "provider_calls": outcome["provider_calls"],
        "scientific_observations": outcome["scientific_observations"],
        "session_id": completion["session_id"],
        "total_cost_usd": completion["total_cost_usd"],
        "model_usage": completion["modelUsage"],
        "boundary_observation": boundary,
        "artifacts": [tracked_repo_file(root / relative) for relative in relative_files],
    }


def build(local_first: Path, token_parity: Path, write_snapshots: bool) -> dict:
    sources = []
    for rel in LOCAL_FIRST_FILES:
        sources.append(snapshot_source(local_first, rel, "local-first", write_snapshots))
    for rel in TOKEN_PARITY_FILES:
        sources.append(snapshot_source(token_parity, rel, "token-parity-proof", write_snapshots))

    rows = []
    for rel in TOKEN_PARITY_FILES[1:3]:
        rows.extend(
            json.loads(line) for line in (token_parity / rel).read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    robust = robust_result(rows)
    spark_matrix = spark_effort_matrix()
    fable_canary = fable_effort_canary()
    runs = [summarize_run(path) for path in sorted((REPO / "data/orchestration").glob("*.json"))]
    by_model = defaultdict(list)
    for run in runs:
        by_model[run["engine"]["model"]].append(run["run_id"])

    benchmarks_text = (local_first / "BENCHMARKS.md").read_text(encoding="utf-8")
    cards = {
        "gpt-5.6-sol": {
            "evidence": ["robust_sol_vs_spark", *by_model.get("gpt-5.6-sol", [])],
            "residue": "18/18 robust first-pass clears; use after Spark validator failure or for high-risk cross-checks",
        },
        "gpt-5.3-codex-spark": {
            "evidence": ["robust_sol_vs_spark", "spark_effort_public_v1", "repo_relay", "blind_review_quality", *by_model.get("gpt-5.3-codex-spark", [])],
            "residue": "18/18 robust first-pass clears and 17/18 race wins; on the public effort matrix medium cleared 9/9 while low and high each cleared 8/9, with both misses caused by Markdown-fenced otherwise plausible source",
        },
        "terra:version-unspecified": {
            "evidence": ["route_discovery"],
            "residue": "bounded target generation sharply reduced tokens on one small task; planner handoff added cost",
            "identity_gap": "the retained report does not preserve a Terra version",
        },
        "qwen2.5:7b": {
            "evidence": ["route_discovery"],
            "residue": "955-token integrated-controller success on the one-task mechanism probe only",
        },
        "qwen3.5:9b-q4_K_M": {
            "evidence": by_model.get("qwen3.5:9b-q4_K_M", []),
            "residue": "default thinking emitted empty finals; think:false exposed a repeatable record-binding bug; one visible-error full-file repair diagnosed but did not integrate the fix",
        },
        "claude-fable-5": {
            "evidence": [*by_model.get("claude-fable-5", []), "fable_effort_public_v1_canary"],
            "residue": "sealed hidden-graded ARC-C receipts plus one green native-CLI low-effort administrative canary; the public low/medium/high matrix has zero scientific cells so far",
        },
    }
    return {
        "schema_version": 1,
        "artifact": "offline_model_residue_index",
        "local_first_commit": git_commit(local_first),
        "sources": sources,
        "coverage": {
            "models": cards,
            "orchestration_runs": runs,
            "route_discovery": route_rows(benchmarks_text),
            "robust_sol_vs_spark": robust,
            "spark_effort_public_v1": spark_matrix,
            "fable_effort_public_v1_canary": fable_canary,
            "repo_relay": {
                "planner_model_tokens": 0,
                "eager_final_validator": "5/5",
                "review_selected_slower_candidate_stages": "2/3",
                "review_added_spark_tokens": 21895,
                "source": "local-first:benchmarks/REPO_RELAY.md",
            },
            "blind_review_quality": {
                "result": "sometimes useful critique, not a correctness oracle",
                "generated_validator_result": "missed shared defects or introduced a false failure",
                "authority": "repository-owned validators",
                "source": "local-first:benchmarks/REVIEW_QUALITY.md",
            },
        },
        "gaps": [
            "The Spark hidden-graded Tier-Bench run is unmeasured because tenant policy blocked external packet transfer; zero Spark calls were made there.",
            "Early Terra and Qwen 2.5 route discovery is retained as report-level evidence, not a K=3 hidden-graded capability map.",
            "The original token-parity-proof tree was not a Git repository; selected raw results and summaries are now snapshotted byte-for-byte here.",
            "This index covers models evidenced by the selected committed reports and sealed orchestration runs; it does not claim unobserved configurations.",
            "The Fable public effort matrix has one green administrative canary and zero scientific cells; its 27-call low/medium/high matrix remains pending.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-first", type=Path, required=True)
    parser.add_argument("--token-parity", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    artifact = build(args.local_first.resolve(), args.token_parity.resolve(), not args.check)
    rendered = json.dumps(artifact, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not args.out.is_file() or args.out.read_text(encoding="utf-8") != rendered:
            raise SystemExit("model residue index drifted")
        print(f"OK — {len(artifact['coverage']['models'])} model cards and {len(artifact['coverage']['orchestration_runs'])} runs")
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered, encoding="utf-8")
    print(f"wrote {args.out} with {len(artifact['coverage']['models'])} model cards")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
