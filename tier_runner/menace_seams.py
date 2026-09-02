"""CLI for the MENACE donor-pile, seam, and minimal-witness census."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .menace_edge_common import EdgeError, hash_json, load_json, write_json
from .menace_seam_plan import (
    compile_plan,
    compile_report,
    render_markdown,
    validate_bundle,
    verify_plan,
    verify_report,
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="tierseams",
        description=(
            "Compile sanitized donor piles into repeated edge seams, Venn intersections, and an "
            "exact cost-weighted minimal witness set"
        ),
    )
    commands = result.add_subparsers(dest="command", required=True)

    def sources(command: argparse.ArgumentParser) -> None:
        command.add_argument("--donors", type=Path, required=True)
        command.add_argument("--seams", type=Path, required=True)
        command.add_argument("--coverage", type=Path, required=True)

    validate = commands.add_parser("validate")
    sources(validate)

    plan = commands.add_parser("plan")
    sources(plan)
    plan.add_argument("--out", type=Path)

    verify = commands.add_parser("verify")
    sources(verify)
    verify.add_argument("--plan", type=Path, required=True)

    report = commands.add_parser("report")
    sources(report)
    report.add_argument("--out-json", type=Path)
    report.add_argument("--out-markdown", type=Path)

    verify_report_command = commands.add_parser("verify-report")
    sources(verify_report_command)
    verify_report_command.add_argument("--report", type=Path, required=True)
    return result


def _inputs(args: argparse.Namespace) -> tuple[object, object, object]:
    return load_json(args.donors), load_json(args.seams), load_json(args.coverage)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        donors, seams, coverage = _inputs(args)
        if args.command == "validate":
            normalized_donors, normalized_seams, normalized_coverage = validate_bundle(
                donors, seams, coverage
            )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "campaign_id": normalized_donors["campaign_id"],
                        "donor_piles": len(normalized_donors["piles"]),
                        "donors": sum(
                            len(item["donors"]) for item in normalized_donors["piles"]
                        ),
                        "seams": len(normalized_seams["seams"]),
                        "negative_witnesses": len(normalized_seams["negative_witnesses"]),
                        "coverage_witnesses": len(normalized_coverage["witnesses"]),
                        "donor_piles_sha256": hash_json(normalized_donors),
                        "seam_catalog_sha256": hash_json(normalized_seams),
                        "coverage_matrix_sha256": hash_json(normalized_coverage),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "plan":
            write_json(args.out, compile_plan(donors, seams, coverage))
            return 0

        if args.command == "verify":
            errors = verify_plan(donors, seams, coverage, load_json(args.plan))
            print(json.dumps({"ok": not errors, "errors": errors}, indent=2, sort_keys=True))
            return int(bool(errors))

        if args.command == "report":
            report = compile_report(donors, seams, coverage)
            write_json(args.out_json, report)
            markdown = render_markdown(report)
            if args.out_markdown is None:
                print(markdown, end="")
            else:
                args.out_markdown.parent.mkdir(parents=True, exist_ok=True)
                temporary = args.out_markdown.with_suffix(args.out_markdown.suffix + ".tmp")
                temporary.write_text(markdown, encoding="utf-8")
                temporary.replace(args.out_markdown)
            return 0

        if args.command == "verify-report":
            errors = verify_report(donors, seams, coverage, load_json(args.report))
            print(json.dumps({"ok": not errors, "errors": errors}, indent=2, sort_keys=True))
            return int(bool(errors))
    except (EdgeError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"tierseams: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
