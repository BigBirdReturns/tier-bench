#!/usr/bin/env python3
"""CLI for Astra Stage 2 executable-control identity binding."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from astra_stage2.canonical import Stage2Error, strict_json_load, write_json_atomic
from astra_stage2.control_identity import (
    bind_control_set,
    binding_template,
    inventory_binding_config,
    probe_hardware,
    validate_binding_config,
    verify_control_set,
)


def _parse_indices(value: str) -> list[int]:
    if not value.strip():
        return []
    try:
        return [int(item.strip()) for item in value.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("device indices must be comma-separated integers") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bind the complete local executable identities for the three Astra Stage 2 controls."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    template = sub.add_parser("template", help="write the private binding-input template")
    template.add_argument("--out", type=Path, required=True)

    inventory = sub.add_parser(
        "inventory", help="discover checkpoint config, tokenizer, index, and weight paths"
    )
    inventory.add_argument("--config", type=Path, required=True)
    inventory.add_argument("--out", type=Path, required=True)

    probe = sub.add_parser("probe-hardware", help="capture private NVIDIA hardware evidence")
    probe.add_argument("--out", type=Path, required=True)
    probe.add_argument("--nvidia-smi")
    probe.add_argument("--device-indices", type=_parse_indices, default=[])

    bind = sub.add_parser("bind", help="bind all three controls and emit private/public receipts")
    bind.add_argument("--config", type=Path, required=True)
    bind.add_argument("--repo-root", type=Path, default=Path("."))
    bind.add_argument("--out", type=Path, required=True)

    verify = sub.add_parser("verify", help="recompute and verify an existing bound control set")
    verify.add_argument("--config", type=Path, required=True)
    verify.add_argument("--repo-root", type=Path, default=Path("."))
    verify.add_argument("--out", type=Path, required=True)

    validate = sub.add_parser("validate-config", help="validate a populated binding input")
    validate.add_argument("--config", type=Path, required=True)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "template":
            write_json_atomic(args.out, binding_template())
            result = {"state": "TEMPLATE_WRITTEN", "path": str(args.out)}
        elif args.command == "inventory":
            config = inventory_binding_config(strict_json_load(args.config))
            write_json_atomic(args.out, config)
            result = {"state": "INVENTORY_WRITTEN", "path": str(args.out)}
        elif args.command == "probe-hardware":
            result = probe_hardware(
                output_dir=args.out,
                nvidia_smi=args.nvidia_smi,
                device_indices=args.device_indices,
            )
        elif args.command == "bind":
            result = bind_control_set(
                strict_json_load(args.config),
                repo_root=args.repo_root,
                output_dir=args.out,
            )
        elif args.command == "verify":
            result = verify_control_set(
                strict_json_load(args.config),
                repo_root=args.repo_root,
                output_dir=args.out,
            )
        elif args.command == "validate-config":
            validate_binding_config(strict_json_load(args.config))
            result = {"state": "CONFIG_VALID"}
        else:
            parser.error(f"unsupported command: {args.command}")
            return 2
    except (OSError, Stage2Error) as exc:
        parser.exit(2, f"REFUSED: {exc}\n")
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
