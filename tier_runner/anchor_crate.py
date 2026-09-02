"""CLI for the Community Home Lab Anchor Crate floor."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .anchor_crate_common import AnchorError, load_json, write_json
from .anchor_crate_plan import compare_backend_bindings, compile_plan, verify_plan
from .anchor_crate_runtime import backend_conformance, run_cartridge
from .anchor_crate_schema import validate_backend_registry, validate_cartridge, validate_floor


def _bindings(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise AnchorError(f"binding must be NODE=BACKEND: {value}")
        node, backend = value.split("=", 1)
        if not node or not backend or node in result:
            raise AnchorError(f"invalid or duplicate binding: {value}")
        result[node] = backend
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="tieranchor",
        description=(
            "Compile and execute backend-neutral task DAGs as durable anchors and bounded crates"
        ),
    )
    commands = result.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate")
    validate.add_argument("--floor", type=Path, required=True)
    validate.add_argument("--cartridge", type=Path, required=True)
    validate.add_argument("--backends", type=Path, required=True)

    plan = commands.add_parser("plan")
    plan.add_argument("--floor", type=Path, required=True)
    plan.add_argument("--cartridge", type=Path, required=True)
    plan.add_argument("--backends", type=Path, required=True)
    plan.add_argument("--bind", action="append", default=[])
    plan.add_argument("--out", type=Path)

    verify = commands.add_parser("verify")
    verify.add_argument("--floor", type=Path, required=True)
    verify.add_argument("--cartridge", type=Path, required=True)
    verify.add_argument("--backends", type=Path, required=True)
    verify.add_argument("--bind", action="append", default=[])
    verify.add_argument("--plan", type=Path, required=True)


    compare = commands.add_parser("compare")
    compare.add_argument("--floor", type=Path, required=True)
    compare.add_argument("--cartridge", type=Path, required=True)
    compare.add_argument("--backends", type=Path, required=True)
    compare.add_argument("--node", required=True)
    compare.add_argument("--backend-a", required=True)
    compare.add_argument("--backend-b", required=True)
    compare.add_argument("--out", type=Path)

    run = commands.add_parser("run")
    run.add_argument("--floor", type=Path, required=True)
    run.add_argument("--cartridge", type=Path, required=True)
    run.add_argument("--backends", type=Path, required=True)
    run.add_argument("--bind", action="append", default=[])
    run.add_argument("--run-root", type=Path, required=True)
    run.add_argument("--controller-cwd", type=Path, default=Path("."))
    run.add_argument("--resume-anchor", type=Path)
    run.add_argument("--stop-after-node")
    run.add_argument("--out", type=Path)

    conformance = commands.add_parser("conformance")
    conformance.add_argument("--backends", type=Path, required=True)
    conformance.add_argument("--backend", required=True)
    conformance.add_argument("--controller-cwd", type=Path, default=Path("."))
    conformance.add_argument("--out", type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "validate":
            floor = validate_floor(load_json(args.floor))
            cartridge = validate_cartridge(load_json(args.cartridge))
            backends = validate_backend_registry(load_json(args.backends))
            print(
                json.dumps(
                    {
                        "ok": True,
                        "floor_id": floor["id"],
                        "cartridge_id": cartridge["id"],
                        "nodes": len(cartridge["nodes"]),
                        "backends": len(backends["backends"]),
                        "physical_backends": sum(
                            row["physical_qualification"] for row in backends["backends"]
                        ),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "plan":
            write_json(
                args.out,
                compile_plan(
                    load_json(args.floor),
                    load_json(args.cartridge),
                    load_json(args.backends),
                    bindings=_bindings(args.bind),
                ),
            )
            return 0
        if args.command == "verify":
            errors = verify_plan(
                load_json(args.floor),
                load_json(args.cartridge),
                load_json(args.backends),
                load_json(args.plan),
                bindings=_bindings(args.bind),
            )
            print(json.dumps({"ok": not errors, "errors": errors}, indent=2, sort_keys=True))
            return int(bool(errors))
        if args.command == "compare":
            write_json(
                args.out,
                compare_backend_bindings(
                    load_json(args.floor),
                    load_json(args.cartridge),
                    load_json(args.backends),
                    node_id=args.node,
                    backend_a=args.backend_a,
                    backend_b=args.backend_b,
                ),
            )
            return 0
        if args.command == "run":
            result = run_cartridge(
                load_json(args.floor),
                load_json(args.cartridge),
                load_json(args.backends),
                run_root=args.run_root.resolve(),
                controller_cwd=args.controller_cwd.resolve(),
                bindings=_bindings(args.bind),
                resume_anchor=args.resume_anchor.resolve() if args.resume_anchor else None,
                stop_after_node=args.stop_after_node,
            )
            write_json(args.out, result)
            return 0
        if args.command == "conformance":
            write_json(
                args.out,
                backend_conformance(
                    load_json(args.backends),
                    backend_id=args.backend,
                    controller_cwd=args.controller_cwd.resolve(),
                ),
            )
            return 0
    except (AnchorError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"tieranchor: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
