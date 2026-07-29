"""Command-line interface for the AXM Estate Lab."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from .commodities import (
    build_acquisition_plan,
    load_commodity_catalog,
    render_acquisition_plan_markdown,
    select_candidates,
    write_acquisition_plan,
)
from .errors import EstateLabError
from .manifest import load_manifest, load_scenario
from .routing import choose_route
from .runtime import EstateLab

HERE = Path(__file__).resolve().parent
DEFAULT_MANIFEST = HERE / "fixtures" / "estate.example.json"
DEFAULT_SCENARIO_DIR = HERE / "fixtures" / "scenarios"
DEFAULT_COMMODITY_CATALOG = HERE / "fixtures" / "commodities.example.json"


def _add_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--mode", choices=("synthetic", "live"), default="synthetic")
    parser.add_argument(
        "--probe-profile",
        choices=("none", "smoke", "full", "all"),
        default="none",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="estate-lab",
        description="Exercise AXM estate routes, authority, equivalence, faults, and project probes.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate the manifest and scenario contracts.")
    validate.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    validate.add_argument("scenarios", type=Path, nargs="*")

    discover = subparsers.add_parser("discover", help="Resolve estate repositories and adapter availability.")
    _add_runtime_args(discover)

    run = subparsers.add_parser("run", help="Run one scenario and emit a receipt bundle.")
    _add_runtime_args(run)
    run.add_argument("scenario", type=Path)
    run.add_argument("--output", type=Path, default=Path(".estate-lab-runs"))
    run.add_argument("--json", action="store_true", dest="as_json")

    run_all = subparsers.add_parser("run-all", help="Run every reference scenario.")
    _add_runtime_args(run_all)
    run_all.add_argument("--scenario-dir", type=Path, default=DEFAULT_SCENARIO_DIR)
    run_all.add_argument("--output", type=Path, default=Path(".estate-lab-runs"))
    run_all.add_argument("--json", action="store_true", dest="as_json")

    route = subparsers.add_parser("route", help="Inspect one route decision without executing an action.")
    _add_runtime_args(route)
    route.add_argument("action_id")
    route.add_argument("--role", required=True)
    route.add_argument("--mandate", required=True)
    route.add_argument("--candidate", action="append", default=[])
    route.add_argument("--unavailable", action="append", default=[])
    route.add_argument("--require-tag", action="append", default=[])
    route.add_argument("--forbid-tag", action="append", default=[])
    route.add_argument("--minimum-evidence", type=int)
    route.add_argument("--max-latency-ms", type=int)
    route.add_argument("--max-cost-microunits", type=int)
    route.add_argument("--require-local", action="store_true")

    commodities = subparsers.add_parser(
        "commodities",
        help="Inspect the reviewed OSS, community, and commodity acquisition ledger.",
    )
    commodities.add_argument("--catalog", type=Path, default=DEFAULT_COMMODITY_CATALOG)
    commodities.add_argument("--decision", action="append", default=[])
    commodities.add_argument("--category", action="append", default=[])
    commodities.add_argument("--priority", action="append", default=[])
    commodities.add_argument("--target", action="append", default=[])
    commodities.add_argument("--format", choices=("markdown", "json"), default="markdown")
    commodities.add_argument("--output", type=Path)

    return parser


def _lab_from_args(args: argparse.Namespace) -> EstateLab:
    manifest = load_manifest(args.manifest)
    return EstateLab(
        manifest,
        workspace=args.workspace,
        execution_mode=args.mode,
        probe_profile=args.probe_profile,
    )


def _outcome_json(outcome) -> dict:
    data = asdict(outcome)
    if data.get("receipt_dir") is not None:
        data["receipt_dir"] = str(data["receipt_dir"])
    return data


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            manifest = load_manifest(args.manifest)
            scenarios = args.scenarios or sorted(DEFAULT_SCENARIO_DIR.glob("*.json"))
            loaded = [load_scenario(path, manifest) for path in scenarios]
            print(
                json.dumps(
                    {
                        "status": "PASS",
                        "manifest": str(args.manifest),
                        "estate_id": manifest.estate_id,
                        "organs": len(manifest.organs),
                        "adapters": len(manifest.adapters),
                        "routes": len(manifest.routes),
                        "scenarios": [scenario.scenario_id for scenario in loaded],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "discover":
            lab = _lab_from_args(args)
            print(
                json.dumps(
                    {
                        "manifest_id": lab.manifest_id,
                        "repositories": {
                            organ_id: {
                                "present": path is not None,
                                "local_name": path.name if path else None,
                            }
                            for organ_id, path in sorted(lab.repositories.items())
                        },
                        "adapter_status": dict(sorted(lab.adapter_status.items())),
                        "probes": [asdict(result) for result in lab.probe_results],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "run":
            lab = _lab_from_args(args)
            scenario = load_scenario(args.scenario, lab.manifest)
            outcome = lab.run_scenario(scenario, output_root=args.output)
            if args.as_json:
                print(json.dumps(_outcome_json(outcome), indent=2, sort_keys=True))
            else:
                print(f"{outcome.status.upper()} {outcome.scenario_id} {outcome.run_id}")
                print(f"receipt: {outcome.receipt_dir}")
                for failure in outcome.failures:
                    print(f"FAIL: {failure}")
            return 0 if outcome.status == "passed" else 1

        if args.command == "run-all":
            lab = _lab_from_args(args)
            paths = sorted(args.scenario_dir.glob("*.json"))
            if not paths:
                parser.error(f"no scenarios found under {args.scenario_dir}")
            outcomes = [
                lab.run_scenario(load_scenario(path, lab.manifest), output_root=args.output)
                for path in paths
            ]
            passed = all(outcome.status == "passed" for outcome in outcomes)
            if args.as_json:
                print(json.dumps([_outcome_json(outcome) for outcome in outcomes], indent=2, sort_keys=True))
            else:
                for outcome in outcomes:
                    print(f"{outcome.status.upper()} {outcome.scenario_id} {outcome.run_id}")
                    print(f"  receipt: {outcome.receipt_dir}")
                    for failure in outcome.failures:
                        print(f"  FAIL: {failure}")
            return 0 if passed else 1

        if args.command == "commodities":
            catalog = load_commodity_catalog(args.catalog)
            candidates = select_candidates(
                catalog,
                decisions=args.decision,
                categories=args.category,
                priorities=args.priority,
                targets=args.target,
            )
            plan = build_acquisition_plan(catalog, candidates)
            if args.output is not None:
                write_acquisition_plan(args.output, plan, markdown=args.format == "markdown")
            else:
                if args.format == "json":
                    print(json.dumps(plan, indent=2, sort_keys=True))
                else:
                    print(render_acquisition_plan_markdown(plan), end="")
            return 0

        if args.command == "route":
            lab = _lab_from_args(args)
            constraints: dict[str, object] = {
                "require_tags": args.require_tag,
                "forbid_tags": args.forbid_tag,
                "require_local": args.require_local,
            }
            if args.minimum_evidence is not None:
                constraints["minimum_evidence"] = args.minimum_evidence
            if args.max_latency_ms is not None:
                constraints["max_latency_ms"] = args.max_latency_ms
            if args.max_cost_microunits is not None:
                constraints["max_cost_microunits"] = args.max_cost_microunits
            decision = choose_route(
                lab.manifest,
                action_id=args.action_id,
                required_role=args.role,
                required_mandate=args.mandate,
                candidate_route_ids=args.candidate or None,
                constraints=constraints,
                unavailable_route_ids=args.unavailable,
                adapter_status=lab.adapter_status,
            )
            print(
                json.dumps(
                    {
                        "selected_route_id": decision.route_id,
                        "score": decision.score,
                        "evaluations": [
                            {
                                "route_id": item.route_id,
                                "eligible": item.eligible,
                                "score": item.score,
                                "refusal_reasons": list(item.refusal_reasons),
                                "metrics": asdict(item.metrics),
                            }
                            for item in decision.evaluations
                        ],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        parser.error(f"unknown command: {args.command}")
    except EstateLabError as exc:
        print(f"estate-lab: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
