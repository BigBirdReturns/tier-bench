"""Public Task Floor conformance, interoperability, replay, and gap CLI."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .playwright_computer_common import (
    PlaywrightComputerError,
    load_json,
    write_json,
)
from .task_floor_conformance import assess_bundle, gap_report, validate_registry
from .task_floor_driver import CommandDriver, run_driver_conformance
from .task_floor_export import (
    attach_exports,
    build_bundle,
    verify_bundle,
    write_bundle_directory,
)
from .task_floor_protocol import (
    profile_requirement_map,
    validate_action,
    validate_approval,
    validate_cartridge,
    validate_manifest,
    validate_skill_package,
)
from .task_floor_replay import compile_replay_plan, propose_skill_package


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="tiertaskfloor",
        description=(
            "Validate Task Floor manifests and cartridges, test runtime drivers, "
            "build protocol-neutral evidence bundles, export compatibility views, "
            "assess conformance, and report OSS ecosystem gaps."
        ),
    )
    commands = root.add_subparsers(dest="command", required=True)

    commands.add_parser("profiles")

    manifest = commands.add_parser("manifest-validate")
    manifest.add_argument("--manifest", type=Path, required=True)
    manifest.add_argument("--out", type=Path)

    cartridge = commands.add_parser("cartridge-validate")
    cartridge.add_argument("--cartridge", type=Path, required=True)
    cartridge.add_argument("--out", type=Path)

    action = commands.add_parser("action-validate")
    action.add_argument("--action", type=Path, required=True)
    action.add_argument("--out", type=Path)

    approval = commands.add_parser("approval-validate")
    approval.add_argument("--approval", type=Path, required=True)
    approval.add_argument("--out", type=Path)

    driver = commands.add_parser("driver-test")
    driver.add_argument("--command", dest="driver_command", required=True)
    driver.add_argument("--timeout-seconds", type=float, default=120.0)
    driver.add_argument("--cwd", type=Path)
    driver.add_argument("--out", type=Path)

    build = commands.add_parser("bundle-build")
    build.add_argument("--run-dir", type=Path, required=True)
    build.add_argument("--manifest", type=Path, required=True)
    build.add_argument("--out-dir", type=Path, required=True)
    build.add_argument("--a2a-endpoint", default="https://example.invalid/a2a")

    verify = commands.add_parser("bundle-verify")
    verify.add_argument("--bundle", type=Path, required=True)
    verify.add_argument("--artifact-root", type=Path)

    assess = commands.add_parser("bundle-assess")
    assess.add_argument("--bundle", type=Path, required=True)
    assess.add_argument("--out", type=Path)

    registry = commands.add_parser("registry-validate")
    registry.add_argument("--registry", type=Path, required=True)
    registry.add_argument("--out", type=Path)

    gaps = commands.add_parser("gap-report")
    gaps.add_argument("--registry", type=Path, required=True)
    gaps.add_argument("--out", type=Path)

    replay = commands.add_parser("replay-plan")
    replay.add_argument("--bundle", type=Path, required=True)
    replay.add_argument(
        "--mode", choices=("simulate", "counterfactual", "execute"), default="simulate"
    )
    replay.add_argument("--allow-effect", action="append")
    replay.add_argument("--out", type=Path)

    skill = commands.add_parser("skill-propose")
    skill.add_argument("--bundle", type=Path, required=True)
    skill.add_argument("--skill-id", required=True)
    skill.add_argument("--version", required=True)
    skill.add_argument("--name", required=True)
    skill.add_argument("--entrypoint", required=True)
    skill.add_argument("--artifact", type=Path, required=True)
    skill.add_argument("--runtime-kind", default="unspecified")
    skill.add_argument("--runtime-version", default="unspecified")
    skill.add_argument("--out", type=Path, required=True)

    skill_validate = commands.add_parser("skill-validate")
    skill_validate.add_argument("--skill", type=Path, required=True)
    skill_validate.add_argument("--out", type=Path)
    return root


def _bundle(path: Path) -> dict:
    value = load_json(path)
    if not isinstance(value, dict):
        raise PlaywrightComputerError("bundle file must contain an object")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "profiles":
            write_json(None, {"profiles": profile_requirement_map()})
            return 0
        if args.command == "manifest-validate":
            value = validate_manifest(load_json(args.manifest))
            write_json(args.out, {"ok": True, "manifest": value})
            return 0
        if args.command == "cartridge-validate":
            value = validate_cartridge(load_json(args.cartridge))
            write_json(args.out, {"ok": True, "cartridge": value})
            return 0
        if args.command == "action-validate":
            value = validate_action(load_json(args.action))
            write_json(args.out, {"ok": True, "action": value})
            return 0
        if args.command == "approval-validate":
            value = validate_approval(load_json(args.approval))
            write_json(args.out, {"ok": True, "approval": value})
            return 0
        if args.command == "driver-test":
            environment = dict(os.environ)
            result = run_driver_conformance(
                CommandDriver(
                    args.driver_command,
                    timeout_seconds=args.timeout_seconds,
                    cwd=args.cwd,
                    environment=environment,
                )
            )
            write_json(args.out, result)
            return 0 if result["passed"] else 1
        if args.command == "bundle-build":
            base = build_bundle(args.run_dir, load_json(args.manifest))
            complete = write_bundle_directory(
                args.out_dir,
                base,
                a2a_endpoint=args.a2a_endpoint,
                artifact_source_root=args.run_dir,
            )
            report = assess_bundle(complete)
            write_json(
                None,
                {
                    "ok": not verify_bundle(complete),
                    "out_dir": str(args.out_dir.resolve()),
                    "bundle_sha256": complete["bundle_sha256"],
                    "highest_contiguous_profile": report[
                        "highest_contiguous_profile"
                    ],
                    "overclaimed_profiles": report["claims"][
                        "overclaimed_profiles"
                    ],
                },
            )
            return 0 if not report["claims"]["overclaimed_profiles"] else 1
        if args.command == "bundle-verify":
            value = _bundle(args.bundle)
            errors = verify_bundle(value, root=args.artifact_root)
            write_json(None, {"ok": not errors, "errors": errors})
            return 0 if not errors else 1
        if args.command == "bundle-assess":
            report = assess_bundle(_bundle(args.bundle))
            write_json(args.out, report)
            return 0 if not report["claims"]["overclaimed_profiles"] else 1
        if args.command == "registry-validate":
            value = validate_registry(load_json(args.registry))
            write_json(args.out, {"ok": True, "registry": value})
            return 0
        if args.command == "gap-report":
            report = gap_report(load_json(args.registry))
            write_json(args.out, report)
            return 0
        if args.command == "replay-plan":
            value = compile_replay_plan(
                _bundle(args.bundle),
                mode=args.mode,
                allow_effects=args.allow_effect,
            )
            write_json(args.out, value)
            return 0 if args.mode != "execute" or value["execution_authorized"] else 1
        if args.command == "skill-propose":
            value = propose_skill_package(
                _bundle(args.bundle),
                skill_id=args.skill_id,
                version=args.version,
                name=args.name,
                entrypoint=args.entrypoint,
                artifact_path=args.artifact,
                runtime={
                    "kind": args.runtime_kind,
                    "version": args.runtime_version,
                },
            )
            write_json(args.out, value)
            return 0
        if args.command == "skill-validate":
            value = validate_skill_package(load_json(args.skill))
            write_json(args.out, {"ok": True, "skill": value})
            return 0
    except (PlaywrightComputerError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"tiertaskfloor: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
