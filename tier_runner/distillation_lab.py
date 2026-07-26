"""CLI for the Desktop Distillation Lab."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .distillation_plan import compile_lab_plan, verify_lab_plan, work_orders
from .distillation_schema import LabError, hash_json, validate_lab


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LabError(f"cannot read {path}: {exc}") from exc


def emit(value, out: Path | None) -> None:
    rendered = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if out is None:
        print(rendered, end="")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_suffix(out.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(out)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="tierdistill",
        description="Plan source-bound desktop distillation from frontier residue",
    )
    commands = result.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate")
    validate.add_argument("--lab", type=Path, required=True)

    plan = commands.add_parser("plan")
    plan.add_argument("--lab", type=Path, required=True)
    plan.add_argument("--out", type=Path)

    verify = commands.add_parser("verify")
    verify.add_argument("--lab", type=Path, required=True)
    verify.add_argument("--plan", type=Path, required=True)

    orders = commands.add_parser("work-orders")
    orders.add_argument("--lab", type=Path, required=True)
    orders.add_argument("--out", type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        raw = load(args.lab)
        if args.command == "validate":
            lab = validate_lab(raw)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "lab_id": lab["id"],
                        "candidates": len(lab["candidates"]),
                        "lab_sha256": hash_json(lab),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "plan":
            emit(compile_lab_plan(raw), args.out)
            return 0
        if args.command == "verify":
            errors = verify_lab_plan(raw, load(args.plan))
            print(json.dumps({"ok": not errors, "errors": errors}, indent=2, sort_keys=True))
            return int(bool(errors))
        if args.command == "work-orders":
            emit(work_orders(raw), args.out)
            return 0
    except (LabError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"tierdistill: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
