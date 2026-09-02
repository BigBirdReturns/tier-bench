#!/usr/bin/env python3
"""Command-line interface for the Tier-Bench frontier fingerprint observatory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from frontier_fingerprint.canonical import load_json, write_json_atomic  # noqa: E402
from frontier_fingerprint.contracts import ContractError, validate_manifest  # noqa: E402
from frontier_fingerprint.engine import build_plan, execute_campaign, verify_run  # noqa: E402
from frontier_fingerprint.passive import observe_to_file  # noqa: E402
from frontier_fingerprint.report import compare_summaries, summarize_run  # noqa: E402


def _manifest(path: Path) -> dict:
    value = load_json(path)
    if not isinstance(value, dict):
        raise ContractError("manifest must be a JSON object")
    validate_manifest(value)
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build, execute, verify, and compare text-free frontier fingerprints."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="compile a public text-free execution plan")
    plan.add_argument("--manifest", type=Path, required=True)
    plan.add_argument("--out", type=Path, required=True)
    plan.add_argument(
        "--resolve-model",
        action="store_true",
        help="require and record the resolved model binding",
    )

    run = sub.add_parser("run", help="execute a mock or explicitly authorized live campaign")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--out", type=Path, required=True, help="new or empty run directory")
    run.add_argument("--live", action="store_true")

    verify = sub.add_parser("verify", help="authenticate raw bodies and rederive evidence")
    verify.add_argument("--run-dir", type=Path, required=True)
    verify.add_argument("--out", type=Path)

    summarize = sub.add_parser("summarize", help="emit a public text-free summary")
    summarize.add_argument("--run-dir", type=Path, required=True)
    summarize.add_argument("--out", type=Path, required=True)

    passive = sub.add_parser(
        "passive", help="extract structural and numeric signals from JSON or JSONL"
    )
    passive.add_argument("--input", type=Path, required=True)
    passive.add_argument(
        "--adapter",
        choices=["claude_code_jsonl", "codex_jsonl", "generic_provider_json"],
        required=True,
    )
    passive.add_argument("--out", type=Path, required=True)

    compare = sub.add_parser("compare", help="apply a preregistered comparison matrix")
    compare.add_argument("--matrix", type=Path, required=True)
    compare.add_argument("--summary", type=Path, action="append", required=True)
    compare.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            manifest = _manifest(args.manifest)
            result = build_plan(manifest, resolve=args.resolve_model)
            write_json_atomic(args.out, result)
        elif args.command == "run":
            manifest = _manifest(args.manifest)
            result = execute_campaign(manifest, args.out, cli_live=args.live)
            print(json.dumps(result, sort_keys=True))
        elif args.command == "verify":
            result = verify_run(args.run_dir)
            if args.out:
                write_json_atomic(args.out, result)
            print(json.dumps(result, sort_keys=True))
        elif args.command == "summarize":
            result = summarize_run(args.run_dir, args.out)
            print(json.dumps({"summary_sha256": result["summary_sha256"]}, sort_keys=True))
        elif args.command == "passive":
            result = observe_to_file(args.input, args.out, adapter=args.adapter)
            print(json.dumps({"observation_sha256": result["observation_sha256"]}, sort_keys=True))
        elif args.command == "compare":
            matrix = load_json(args.matrix)
            result = compare_summaries(matrix, args.summary, args.out)
            print(json.dumps({"comparison_sha256": result["comparison_sha256"]}, sort_keys=True))
        else:
            raise AssertionError(args.command)
    except (ContractError, FileNotFoundError, OSError, ValueError) as exc:
        print(f"frontier-fingerprint: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
