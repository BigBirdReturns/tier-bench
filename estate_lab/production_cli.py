"""Production command line for Surface Interop."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .errors import EstateLabError
from .floor import (
    build_floor_registry,
    initialize_adapter,
    load_floor_adapter,
    load_floor_spec,
    load_floor_submission,
    render_registry_markdown,
    validate_floor_registry,
)
from .floor_gaps import build_gap_report, load_gap_ledger, render_gap_report_markdown
from .production import (
    ProductionError,
    build_release_archive,
    build_support_bundle,
    load_production_policy,
    production_doctor,
    run_production_conformance,
    verify_release_archive,
    verify_submission_bundle,
)

HERE = Path(__file__).resolve().parent
DEFAULT_SPEC = HERE / "fixtures" / "floor" / "floor.example.json"
DEFAULT_VECTORS = HERE / "fixtures" / "floor" / "vectors"
DEFAULT_GAPS = HERE / "fixtures" / "floor" / "floor-gaps.example.json"
DEFAULT_REFERENCE_ADAPTER = HERE / "fixtures" / "floor" / "reference-adapter" / "adapter.json"

EXIT_OK = 0
EXIT_CONFORMANCE = 1
EXIT_USAGE_OR_INPUT = 2
EXIT_OPERATIONAL = 3
EXIT_INTERNAL = 70


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"


def _emit(value: Any, *, output: Path | None = None) -> None:
    text = _json(value)
    if output is None:
        sys.stdout.write(text)
    else:
        from .production import atomic_write_text

        atomic_write_text(output, text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="surface-interop",
        description=(
            "Production-grade semantic adapter conformance, diagnostics, registry, "
            "and deterministic release tooling."
        ),
    )
    parser.add_argument("--version", action="store_true", dest="show_version")
    sub = parser.add_subparsers(dest="command")

    doctor = sub.add_parser("doctor", help="Run offline installation and source-integrity diagnostics.")
    doctor.add_argument("--root", type=Path)
    doctor.add_argument("--output", type=Path)

    validate_spec = sub.add_parser("validate-spec", help="Validate a floor specification.")
    validate_spec.add_argument("spec", type=Path, nargs="?", default=DEFAULT_SPEC)

    validate_adapter = sub.add_parser("validate-adapter", help="Validate an adapter declaration and supply pins.")
    validate_adapter.add_argument("adapter", type=Path, nargs="?", default=DEFAULT_REFERENCE_ADAPTER)
    validate_adapter.add_argument("--spec", type=Path, default=DEFAULT_SPEC)

    init = sub.add_parser("init", help="Generate a dependency-free command-json adapter starter.")
    init.add_argument("directory", type=Path)
    init.add_argument("--adapter-id", required=True)
    init.add_argument("--name", required=True)
    init.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    init.add_argument("--force", action="store_true")

    conform = sub.add_parser("conform", help="Run production-hardened conformance and emit a detached bundle.")
    conform.add_argument("adapter", type=Path, nargs="?", default=DEFAULT_REFERENCE_ADAPTER)
    conform.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    conform.add_argument("--output", type=Path, required=True)
    conform.add_argument("--policy", type=Path)
    conform.add_argument(
        "--allow-exec",
        action="store_true",
        help="Explicitly allow the adapter command declared by the descriptor to execute.",
    )
    conform.add_argument("--independent-verifier", action="store_true")
    conform.add_argument("--substitution-receipt-sha256")

    verify_submission = sub.add_parser(
        "verify-submission",
        help="Verify a detached submission file or a complete checksummed bundle.",
    )
    verify_submission.add_argument("submission", type=Path)
    verify_submission.add_argument("--policy", type=Path)

    registry = sub.add_parser("registry", help="Build a deterministic registry from admitted submissions.")
    registry.add_argument("submissions", type=Path, nargs="+")
    registry.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    registry.add_argument("--output", type=Path)
    registry.add_argument("--markdown", action="store_true")

    verify_registry = sub.add_parser("verify-registry", help="Verify a detached registry.")
    verify_registry.add_argument("registry", type=Path)
    verify_registry.add_argument("--spec", type=Path, default=DEFAULT_SPEC)

    gaps = sub.add_parser("gaps", help="Inspect the machine-readable production gap ledger.")
    gaps.add_argument("--ledger", type=Path, default=DEFAULT_GAPS)
    gaps.add_argument("--output", type=Path)
    gaps.add_argument("--markdown", action="store_true")

    release = sub.add_parser("build-release", help="Build a deterministic offline-verifiable release ZIP.")
    release.add_argument("--root", type=Path, default=HERE.parent)
    release.add_argument("--output", type=Path, required=True)
    release.add_argument("--version")
    release.add_argument("--policy", type=Path)

    verify_release = sub.add_parser("verify-release", help="Verify a release ZIP without extracting it.")
    verify_release.add_argument("archive", type=Path)
    verify_release.add_argument("--policy", type=Path)
    verify_release.add_argument("--output", type=Path)

    support = sub.add_parser("support-bundle", help="Create a redacted diagnostic receipt for support.")
    support.add_argument("--root", type=Path)
    support.add_argument("--output", type=Path, required=True)
    support.add_argument("--report", type=Path, action="append", default=[])

    return parser


def _version() -> str:
    return (HERE / "VERSION").read_text(encoding="utf-8").strip()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.show_version and args.command is None:
        print(_version())
        return EXIT_OK
    if args.command is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE_OR_INPUT
    try:
        if args.command == "doctor":
            report = production_doctor(args.root)
            _emit(report, output=args.output)
            return EXIT_OK if report["status"] == "PASS" else EXIT_OPERATIONAL

        if args.command == "validate-spec":
            spec = load_floor_spec(args.spec)
            _emit(
                {
                    "status": "PASS",
                    "floor_id": spec.floor_id,
                    "floor_version": spec.floor_version,
                    "profiles": sorted(spec.raw["profiles"]),
                    "vectors": len(spec.raw["vectors"]),
                }
            )
            return EXIT_OK

        if args.command == "validate-adapter":
            from .production import verify_pinned_entrypoint

            spec = load_floor_spec(args.spec)
            adapter = load_floor_adapter(args.adapter, spec)
            command = [
                token.replace("{python}", sys.executable)
                .replace("{adapter_dir}", str(adapter.source_path.parent))
                .replace("{descriptor}", str(adapter.source_path))
                for token in adapter.command
                if "{request}" not in token and "{response}" not in token
            ]
            pins = verify_pinned_entrypoint(adapter, command)
            _emit(
                {
                    "status": "PASS",
                    "adapter_id": adapter.adapter_id,
                    "adapter_version": adapter.adapter_version,
                    "descriptor_id": adapter.descriptor_id,
                    "profiles": list(adapter.profiles),
                    "pinned_entrypoints": pins,
                }
            )
            return EXIT_OK

        if args.command == "init":
            spec = load_floor_spec(args.spec)
            adapter = initialize_adapter(
                args.directory,
                adapter_id=args.adapter_id,
                name=args.name,
                floor_version=spec.floor_version,
                force=args.force,
            )
            _emit(
                {
                    "status": "PASS",
                    "adapter_id": adapter.adapter_id,
                    "adapter_version": adapter.adapter_version,
                    "descriptor_id": adapter.descriptor_id,
                    "directory": str(args.directory),
                }
            )
            return EXIT_OK

        if args.command == "conform":
            if not args.allow_exec:
                raise ProductionError(
                    "adapter_execution_not_authorized",
                    {"required_flag": "--allow-exec"},
                )
            spec = load_floor_spec(args.spec)
            adapter = load_floor_adapter(args.adapter, spec)
            policy = load_production_policy(args.policy)
            submission = run_production_conformance(
                spec,
                adapter,
                output_root=args.output,
                independent_verifier=args.independent_verifier,
                substitution_receipt_sha256=args.substitution_receipt_sha256,
                policy=policy,
            )
            _emit(submission.raw)
            return EXIT_OK if submission.result == "pass" else EXIT_CONFORMANCE

        if args.command == "verify-submission":
            if args.submission.is_dir():
                result = verify_submission_bundle(
                    args.submission,
                    policy=load_production_policy(args.policy),
                )
                _emit(result)
                return EXIT_OK
            submission = load_floor_submission(args.submission)
            _emit(
                {
                    "status": "PASS",
                    "scope": "submission-object-only",
                    "submission_id": submission.submission_id,
                    "adapter_id": submission.adapter_id,
                    "adapter_version": submission.adapter_version,
                    "result": submission.result,
                    "quality_tier": submission.tier,
                }
            )
            return EXIT_OK if submission.result == "pass" else EXIT_CONFORMANCE

        if args.command == "registry":
            spec = load_floor_spec(args.spec)
            submissions = [load_floor_submission(path) for path in args.submissions]
            value = build_floor_registry(spec, submissions)
            if args.markdown:
                text = render_registry_markdown(value)
                if args.output:
                    from .production import atomic_write_text

                    atomic_write_text(args.output, text)
                else:
                    sys.stdout.write(text)
            else:
                _emit(value, output=args.output)
            return EXIT_OK

        if args.command == "verify-registry":
            spec = load_floor_spec(args.spec)
            raw = json.loads(args.registry.read_text(encoding="utf-8"))
            value = validate_floor_registry(raw, spec)
            _emit(
                {
                    "status": "PASS",
                    "registry_id": value["registry_id"],
                    "entry_count": value["entry_count"],
                }
            )
            return EXIT_OK

        if args.command == "gaps":
            report = build_gap_report(load_gap_ledger(args.ledger))
            if args.markdown:
                text = render_gap_report_markdown(report)
                if args.output:
                    from .production import atomic_write_text

                    atomic_write_text(args.output, text)
                else:
                    sys.stdout.write(text)
            else:
                _emit(report, output=args.output)
            open_count = report["counts_by_status"].get("open", 0) + report["counts_by_status"].get(
                "in-progress", 0
            )
            return EXIT_OK if open_count == 0 else EXIT_OPERATIONAL

        if args.command == "build-release":
            version = args.version or (args.root / "estate_lab" / "VERSION").read_text(
                encoding="utf-8"
            ).strip()
            result = build_release_archive(
                args.root,
                args.output,
                version=version,
                policy=load_production_policy(args.policy),
            )
            _emit(result)
            return EXIT_OK

        if args.command == "verify-release":
            result = verify_release_archive(
                args.archive,
                policy=load_production_policy(args.policy),
            )
            _emit(result, output=args.output)
            return EXIT_OK

        if args.command == "support-bundle":
            result = build_support_bundle(
                args.output,
                source_root=args.root,
                report_paths=args.report,
            )
            _emit(result)
            return EXIT_OK

        parser.error(f"unknown command: {args.command}")
    except (EstateLabError, ProductionError, OSError, ValueError, json.JSONDecodeError) as exc:
        reason = getattr(exc, "reason", type(exc).__name__)
        details = getattr(exc, "details", {})
        sys.stderr.write(_json({"status": "ERROR", "reason": reason, "details": details, "message": str(exc)}))
        return EXIT_USAGE_OR_INPUT if isinstance(exc, (ValueError, json.JSONDecodeError)) else EXIT_OPERATIONAL
    except Exception as exc:  # pragma: no cover - last-resort crash boundary
        sys.stderr.write(
            _json(
                {
                    "status": "ERROR",
                    "reason": "internal_error",
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            )
        )
        return EXIT_INTERNAL


if __name__ == "__main__":
    raise SystemExit(main())
