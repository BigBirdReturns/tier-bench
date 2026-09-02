"""Command-line interface for the AXM Estate Lab."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from .canonical import load_json, write_json
from .commodities import (
    build_acquisition_plan,
    load_commodity_catalog,
    render_acquisition_plan_markdown,
    select_candidates,
    write_acquisition_plan,
)
from .errors import EstateLabError
from .floor import (
    build_floor_description,
    build_floor_registry,
    initialize_adapter,
    load_floor_adapter,
    load_floor_spec,
    load_floor_submission,
    render_asyncapi,
    render_conformance_summary,
    render_registry_markdown,
    run_floor_conformance,
    validate_floor_registry,
)
from .floor_gaps import (
    build_gap_report,
    load_gap_ledger,
    render_gap_report_markdown,
    write_gap_report,
)
from .manifest import load_manifest, load_scenario
from .routing import choose_route
from .runtime import EstateLab

HERE = Path(__file__).resolve().parent
DEFAULT_MANIFEST = HERE / "fixtures" / "estate.example.json"
DEFAULT_SCENARIO_DIR = HERE / "fixtures" / "scenarios"
DEFAULT_COMMODITY_CATALOG = HERE / "fixtures" / "commodities.example.json"
DEFAULT_FLOOR_SPEC = HERE / "fixtures" / "floor" / "floor.example.json"
DEFAULT_FLOOR_ADAPTER = HERE / "fixtures" / "floor" / "reference-adapter" / "adapter.json"
DEFAULT_FLOOR_GAPS = HERE / "fixtures" / "floor" / "floor-gaps.example.json"


def _add_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--mode", choices=("synthetic", "live"), default="synthetic")
    parser.add_argument(
        "--probe-profile",
        choices=("none", "smoke", "full", "all"),
        default="none",
    )


def _add_floor_spec(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--spec", type=Path, default=DEFAULT_FLOOR_SPEC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="estate-lab",
        description=(
            "Exercise AXM estate routes and expose a public interaction-floor "
            "protocol, conformance suite, supplier ledger, and adapter registry."
        ),
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

    floor = subparsers.add_parser(
        "floor",
        help="Use the public Interaction Floor protocol and conformance surfaces.",
    )
    floor_sub = floor.add_subparsers(dest="floor_command", required=True)

    floor_validate = floor_sub.add_parser(
        "validate",
        help="Validate the floor specification, adapter declaration, and gap ledger.",
    )
    _add_floor_spec(floor_validate)
    floor_validate.add_argument("--adapter", type=Path, default=DEFAULT_FLOOR_ADAPTER)
    floor_validate.add_argument("--gaps", type=Path, default=DEFAULT_FLOOR_GAPS)

    floor_test = floor_sub.add_parser(
        "test",
        help="Run public conformance vectors against one command-json adapter.",
    )
    _add_floor_spec(floor_test)
    floor_test.add_argument("--adapter", type=Path, default=DEFAULT_FLOOR_ADAPTER)
    floor_test.add_argument("--output", type=Path, default=Path(".floor-conformance"))
    floor_test.add_argument("--independent-verifier", action="store_true")
    floor_test.add_argument("--substitution-receipt-sha256")
    floor_test.add_argument("--json", action="store_true", dest="as_json")

    floor_init = floor_sub.add_parser(
        "init-adapter",
        help="Generate a zero-dependency Python adapter starter.",
    )
    _add_floor_spec(floor_init)
    floor_init.add_argument("directory", type=Path)
    floor_init.add_argument("--adapter-id", required=True)
    floor_init.add_argument("--name", required=True)
    floor_init.add_argument("--force", action="store_true")

    floor_registry = floor_sub.add_parser(
        "registry",
        help="Build a deterministic adapter registry from passing submissions.",
    )
    _add_floor_spec(floor_registry)
    floor_registry.add_argument("--submission", action="append", type=Path, required=True)
    floor_registry.add_argument("--format", choices=("json", "markdown"), default="json")
    floor_registry.add_argument("--output", type=Path)

    floor_verify_submission = floor_sub.add_parser(
        "verify-submission",
        help="Verify a content-addressed conformance submission.",
    )
    floor_verify_submission.add_argument("submission", type=Path)

    floor_verify_registry = floor_sub.add_parser(
        "verify-registry",
        help="Verify a registry identity and entry structure.",
    )
    _add_floor_spec(floor_verify_registry)
    floor_verify_registry.add_argument("registry", type=Path)

    floor_describe = floor_sub.add_parser(
        "describe",
        help="Render the public floor as JSON, Markdown, or AsyncAPI YAML.",
    )
    _add_floor_spec(floor_describe)
    floor_describe.add_argument("--format", choices=("json", "markdown", "asyncapi"), default="markdown")
    floor_describe.add_argument("--output", type=Path)

    floor_gaps = floor_sub.add_parser(
        "gaps",
        help="Project the executable interoperability gap ledger.",
    )
    floor_gaps.add_argument("--ledger", type=Path, default=DEFAULT_FLOOR_GAPS)
    floor_gaps.add_argument("--format", choices=("json", "markdown"), default="markdown")
    floor_gaps.add_argument("--output", type=Path)

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


def _write_or_print(path: Path | None, text: str) -> None:
    if path is None:
        print(text, end="" if text.endswith("\n") else "\n")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")


def _floor_main(args: argparse.Namespace) -> int:
    if args.floor_command == "validate":
        spec = load_floor_spec(args.spec)
        adapter = load_floor_adapter(args.adapter, spec)
        gaps = load_gap_ledger(args.gaps)
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "floor_id": spec.floor_id,
                    "floor_version": spec.floor_version,
                    "adapter_id": adapter.adapter_id,
                    "descriptor_id": adapter.descriptor_id,
                    "profiles": list(adapter.profiles),
                    "vectors": len(spec.raw["vectors"]),
                    "gap_ledger_id": gaps.ledger_id,
                    "gaps": len(gaps.gaps),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.floor_command == "test":
        spec = load_floor_spec(args.spec)
        adapter = load_floor_adapter(args.adapter, spec)
        submission = run_floor_conformance(
            spec,
            adapter,
            output_root=args.output,
            independent_verifier=args.independent_verifier,
            substitution_receipt_sha256=args.substitution_receipt_sha256,
        )
        if args.as_json:
            print(json.dumps(submission.raw, indent=2, sort_keys=True))
        else:
            print(render_conformance_summary(submission.raw), end="")
            print(f"bundle: {args.output / submission.submission_id}")
        return 0 if submission.result == "pass" else 1

    if args.floor_command == "init-adapter":
        spec = load_floor_spec(args.spec)
        adapter = initialize_adapter(
            args.directory,
            adapter_id=args.adapter_id,
            name=args.name,
            floor_version=spec.floor_version,
            force=args.force,
        )
        print(
            json.dumps(
                {
                    "status": "CREATED",
                    "directory": str(args.directory),
                    "adapter_id": adapter.adapter_id,
                    "descriptor_id": adapter.descriptor_id,
                    "next": (
                        f"python -m estate_lab floor test --adapter "
                        f"{args.directory / 'adapter.json'} --output {args.directory / 'conformance'}"
                    ),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.floor_command == "registry":
        spec = load_floor_spec(args.spec)
        submissions = [load_floor_submission(path) for path in args.submission]
        registry = build_floor_registry(spec, submissions)
        if args.format == "json":
            if args.output is None:
                print(json.dumps(registry, indent=2, sort_keys=True))
            else:
                write_json(args.output, registry)
        else:
            _write_or_print(args.output, render_registry_markdown(registry))
        return 0

    if args.floor_command == "verify-submission":
        submission = load_floor_submission(args.submission)
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "submission_id": submission.submission_id,
                    "adapter_id": submission.adapter_id,
                    "adapter_version": submission.adapter_version,
                    "result": submission.result,
                    "quality_tier": submission.tier,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.floor_command == "verify-registry":
        spec = load_floor_spec(args.spec)
        raw = load_json(args.registry)
        if not isinstance(raw, dict):
            raise EstateLabError("registry root must be an object")
        registry = validate_floor_registry(raw, spec)
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "registry_id": registry["registry_id"],
                    "floor_id": registry["floor_id"],
                    "entry_count": registry["entry_count"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.floor_command == "describe":
        spec = load_floor_spec(args.spec)
        description = build_floor_description(spec)
        if args.format == "json":
            text = json.dumps(description, indent=2, sort_keys=True) + "\n"
        elif args.format == "asyncapi":
            text = render_asyncapi(spec)
        else:
            text = "\n".join(
                [
                    "# AXM Interaction Floor",
                    "",
                    f"Floor: `{description['floor_id']}`",
                    f"Version: `{description['floor_version']}`",
                    f"Profiles: {', '.join(description['profiles'])}",
                    f"Quality tiers: {', '.join(description['quality_tiers'])}",
                    f"Bindings: {', '.join(description['bindings'])}",
                    f"Conformance vectors: **{description['vector_count']}**",
                    "",
                    "The floor owns portable interaction and conformance shapes. It refuses domain law, "
                    "physical safety authority, human disposition, project priority, and truth claims.",
                    "",
                ]
            )
        _write_or_print(args.output, text)
        return 0

    if args.floor_command == "gaps":
        ledger = load_gap_ledger(args.ledger)
        report = build_gap_report(ledger)
        if args.output is not None:
            write_gap_report(args.output, report, markdown=args.format == "markdown")
        else:
            if args.format == "json":
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                print(render_gap_report_markdown(report), end="")
        return 0

    raise EstateLabError(f"unknown floor command: {args.floor_command}")


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
            elif args.format == "json":
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

        if args.command == "floor":
            return _floor_main(args)

        parser.error(f"unknown command: {args.command}")
    except EstateLabError as exc:
        print(f"estate-lab: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
