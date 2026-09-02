"""CLI for MENACE edge workload, survival, and thermodynamic qualification."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .menace_edge_analysis import analyze
from .menace_edge_common import EdgeError, hash_json, load_json, write_json
from .menace_edge_plan import compile_plan, observation_templates, verify_plan
from .menace_edge_schema import validate_manifest


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="tiermenace",
        description=(
            "Qualify a detachable edge judgment node across connectivity, fault, human-authority, "
            "and complete wall-energy treatments"
        ),
    )
    commands = result.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate")
    validate.add_argument("--manifest", type=Path, required=True)

    plan = commands.add_parser("plan")
    plan.add_argument("--manifest", type=Path, required=True)
    plan.add_argument("--out", type=Path)

    verify = commands.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--plan", type=Path, required=True)

    templates = commands.add_parser("templates")
    templates.add_argument("--plan", type=Path, required=True)
    templates.add_argument("--out", type=Path)

    report = commands.add_parser("analyze")
    report.add_argument("--manifest", type=Path, required=True)
    report.add_argument("--plan", type=Path, required=True)
    report.add_argument("--observations", type=Path, required=True)
    report.add_argument("--out", type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "validate":
            manifest = validate_manifest(load_json(args.manifest))
            print(
                json.dumps(
                    {
                        "ok": True,
                        "campaign_id": manifest["id"],
                        "manifest_sha256": hash_json(manifest),
                        "profiles": len(manifest["connectivity_profiles"]),
                        "roles": len(manifest["roles"]),
                        "streams": len(manifest["stream_families"]),
                        "workloads": len(manifest["workloads"]),
                        "treatments": len(manifest["treatments"]),
                        "faults": len(manifest["faults"]),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "plan":
            write_json(args.out, compile_plan(load_json(args.manifest)))
            return 0

        if args.command == "verify":
            errors = verify_plan(load_json(args.manifest), load_json(args.plan))
            print(json.dumps({"ok": not errors, "errors": errors}, indent=2, sort_keys=True))
            return int(bool(errors))

        if args.command == "templates":
            plan = load_json(args.plan)
            write_json(args.out, observation_templates(plan))
            return 0

        if args.command == "analyze":
            write_json(
                args.out,
                analyze(
                    load_json(args.manifest),
                    load_json(args.plan),
                    load_json(args.observations),
                ),
            )
            return 0
    except (EdgeError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"tiermenace: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
