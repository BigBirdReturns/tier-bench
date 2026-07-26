"""CLI for the Sovereign Theory Lab."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .sovereign_common import PlaneError, hash_json, load_json, write_json
from .sovereign_theory_analysis import analyze, load_observations
from .sovereign_theory_plan import compile_plan, observation_templates, verify_plan
from .sovereign_theory_schema import validate_lab


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="tiertheory",
        description="Freeze, plan, and adjudicate testable sovereign desktop theories",
    )
    commands = result.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate")
    validate.add_argument("--lab", type=Path, required=True)

    plan = commands.add_parser("plan")
    plan.add_argument("--lab", type=Path, required=True)
    plan.add_argument("--theory", action="append", default=[])
    plan.add_argument("--out", type=Path)

    verify = commands.add_parser("verify")
    verify.add_argument("--lab", type=Path, required=True)
    verify.add_argument("--plan", type=Path, required=True)

    templates = commands.add_parser("templates")
    templates.add_argument("--lab", type=Path, required=True)
    templates.add_argument("--plan", type=Path, required=True)
    templates.add_argument("--out", type=Path)

    analyze_cmd = commands.add_parser("analyze")
    analyze_cmd.add_argument("--lab", type=Path, required=True)
    analyze_cmd.add_argument("--observations", type=Path, required=True)
    analyze_cmd.add_argument("--out", type=Path)

    catalog = commands.add_parser("catalog")
    catalog.add_argument("--lab", type=Path, required=True)
    catalog.add_argument("--status")
    catalog.add_argument("--family")
    return result


def _catalog(lab: dict[str, Any], status: str | None, family: str | None) -> dict[str, Any]:
    theories = [
        theory
        for theory in lab["theories"]
        if (status is None or theory["status"] == status)
        and (family is None or family in theory["task_families"])
    ]
    tasks_by_family: dict[str, dict[str, int]] = {}
    for task in lab["tasks"]:
        row = tasks_by_family.setdefault(
            task["family"], {"ready": 0, "operator_task_required": 0, "blocked": 0}
        )
        row[task["status"]] += 1
    return {
        "schema": lab["schema"],
        "lab_id": lab["id"],
        "lab_sha256": hash_json(lab),
        "filters": {"status": status, "family": family},
        "tasks_by_family": dict(sorted(tasks_by_family.items())),
        "theories": [
            {
                "id": theory["id"],
                "title": theory["title"],
                "priority": theory["priority"],
                "status": theory["status"],
                "task_families": theory["task_families"],
                "prediction": theory["prediction"],
                "falsifier": theory["falsifier"],
                "arms": [
                    {"id": arm["id"], "role": arm["role"], "label": arm["label"]}
                    for arm in theory["arms"]
                ],
            }
            for theory in theories
        ],
    }


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        raw = load_json(args.lab)
        if args.command == "validate":
            lab = validate_lab(raw)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "lab_id": lab["id"],
                        "lab_sha256": hash_json(lab),
                        "metrics": len(lab["metrics"]),
                        "tasks": len(lab["tasks"]),
                        "theories": len(lab["theories"]),
                        "ready_tasks": sum(task["status"] == "ready" for task in lab["tasks"]),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "plan":
            include = set(args.theory) or None
            write_json(args.out, compile_plan(raw, include=include))
            return 0
        if args.command == "verify":
            errors = verify_plan(raw, load_json(args.plan))
            print(json.dumps({"ok": not errors, "errors": errors}, indent=2, sort_keys=True))
            return int(bool(errors))
        if args.command == "templates":
            plan = load_json(args.plan)
            rows = observation_templates(raw, plan)
            if args.out is None:
                for row in rows:
                    print(json.dumps(row, sort_keys=True))
            else:
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(
                    "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
                    encoding="utf-8",
                )
            return 0
        if args.command == "analyze":
            write_json(args.out, analyze(raw, load_observations(args.observations)))
            return 0
        if args.command == "catalog":
            lab = validate_lab(raw)
            write_json(None, _catalog(lab, args.status, args.family))
            return 0
    except (PlaneError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"tiertheory: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
