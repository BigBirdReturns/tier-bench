"""CLI for project-native Task Computer fixtures, planners, and receipts."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

from .playwright_computer_common import PlaywrightComputerError, write_json
from .task_computer_fixtures import ProjectFixtureServer
from .task_computer_lab import TaskComputerRunner, load_catalog, run_suite, verify_run
from .task_computer_planner import CommandPlanner, FileExchangePlanner, ReferencePlanner
from .task_computer_protocol import scenario_by_id

DEFAULT_CATALOG = Path("experiments/task_computer/project_scenarios.json")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="tiertaskcomputer",
        description=(
            "Run project-native browser-computer fixtures with reference, command, or "
            "shared-file planners and externally verified receipts."
        ),
    )
    commands = root.add_subparsers(dest="command", required=True)

    listing = commands.add_parser("list")
    listing.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)

    run = commands.add_parser("run")
    run.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    run.add_argument("--scenario", required=True)
    run.add_argument("--variant", default="base")
    run.add_argument("--out-root", type=Path, default=Path("task-computer-runs"))
    run.add_argument("--headed", action="store_true")
    run.add_argument("--no-trace", action="store_true")
    run.add_argument("--no-approval", action="store_true")
    run.add_argument("--planner-command")
    run.add_argument("--planner-exchange", type=Path)
    run.add_argument("--planner-timeout", type=float, default=1800.0)

    suite = commands.add_parser("suite")
    suite.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    suite.add_argument("--out-root", type=Path, default=Path("task-computer-runs"))
    suite.add_argument("--scenario", action="append")
    suite.add_argument("--variant", action="append")
    suite.add_argument("--headed", action="store_true")
    suite.add_argument("--trace", action="store_true")

    verify = commands.add_parser("verify")
    verify.add_argument("--run-dir", type=Path, required=True)

    fixture = commands.add_parser("serve-fixture")
    fixture.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    fixture.add_argument("--scenario", required=True)
    fixture.add_argument("--variant", default="base")
    fixture.add_argument("--seconds", type=float, default=3600.0)
    return root


def _planner(args: argparse.Namespace, scenario: dict):
    if args.planner_command:
        return CommandPlanner(args.planner_command, timeout_seconds=args.planner_timeout)
    if args.planner_exchange:
        return FileExchangePlanner(
            args.planner_exchange,
            timeout_seconds=args.planner_timeout,
        )
    return ReferencePlanner(scenario)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "list":
            catalog = load_catalog(args.catalog)
            write_json(
                None,
                {
                    "catalog_id": catalog["id"],
                    "scenarios": [
                        {
                            "id": scenario["id"],
                            "project": scenario["project"],
                            "title": scenario["title"],
                            "variants": scenario["variants"],
                            "surface_order": scenario["surface_order"],
                        }
                        for scenario in catalog["scenarios"]
                    ],
                },
            )
            return 0
        if args.command == "run":
            catalog = load_catalog(args.catalog)
            scenario = scenario_by_id(catalog, args.scenario)
            runner = TaskComputerRunner(
                catalog=catalog,
                scenario_id=args.scenario,
                variant=args.variant,
                out_root=args.out_root,
                planner=_planner(args, scenario),
                headless=not args.headed,
                trace=not args.no_trace,
                approval_enabled=not args.no_approval,
            )
            receipt = asyncio.run(runner.run())
            result = {
                "ok": receipt["status"] == "ACCEPTED",
                "run_dir": str(runner.run_dir),
                "receipt": receipt,
                "verification": verify_run(runner.run_dir),
            }
            write_json(None, result)
            return 0 if result["ok"] and result["verification"]["ok"] else 1
        if args.command == "suite":
            catalog = load_catalog(args.catalog)
            result = asyncio.run(
                run_suite(
                    catalog=catalog,
                    out_root=args.out_root,
                    scenario_ids=args.scenario,
                    variants=args.variant,
                    headless=not args.headed,
                    trace=args.trace,
                )
            )
            write_json(None, result)
            return 0 if result["ok"] else 1
        if args.command == "verify":
            result = verify_run(args.run_dir)
            write_json(None, result)
            return 0 if result["ok"] else 1
        if args.command == "serve-fixture":
            import time
            import webbrowser

            catalog = load_catalog(args.catalog)
            scenario = scenario_by_id(catalog, args.scenario)
            if args.variant not in scenario["variants"]:
                raise PlaywrightComputerError("unknown fixture variant")
            server = ProjectFixtureServer(args.scenario, args.variant).start()
            print(server.url, flush=True)
            webbrowser.open(server.url)
            try:
                time.sleep(args.seconds)
            finally:
                server.stop()
            return 0
    except (PlaywrightComputerError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"tiertaskcomputer: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
