"""CLI for the Universal Model Floor Observatory."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from .model_floor import (
    compute_delta_report,
    compute_floor,
    ingest_waterline_tree,
    load_observations,
    observations_from_waterline,
    validate_floor_config,
    write_observations,
)
from .model_floor_common import (
    ModelFloorError,
    hash_json,
    load_json,
    now_utc,
    read_jsonl,
    write_json,
)
from .model_floor_external import (
    purge_state,
    sync_sources,
    validate_source_config,
)
from .model_identity import (
    audit_identities,
    registry_from_models_json,
    validate_registry,
)


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def windows_schedule_script(
    *,
    repo: Path,
    source_config: Path,
    registry: Path,
    floor_config: Path,
    state_dir: Path,
    protocol_root: Path,
    reports_root: Path,
    frequent_minutes: int,
    nightly_hour: int,
) -> str:
    python_exe = sys.executable
    refresh_args = (
        f'-m tier_runner.model_floor_cli refresh --sources "{source_config.resolve()}" '
        f'--registry "{registry.resolve()}" --config "{floor_config.resolve()}" '
        f'--state-dir "{state_dir.resolve()}" '
        f'--protocol-root "{protocol_root.resolve()}" '
        f'--reports-root "{reports_root.resolve()}"'
    )
    lines = [
        "$ErrorActionPreference = 'Stop'",
        f"$Python = {_powershell_quote(python_exe)}",
        f"$Working = {_powershell_quote(str(repo.resolve()))}",
        "$RefreshName = 'TierFloor-Refresh'",
        "$NightlyName = 'TierFloor-Nightly-Refresh'",
        (
            "$RefreshAction = New-ScheduledTaskAction -Execute $Python "
            f"-Argument {_powershell_quote(refresh_args)} -WorkingDirectory $Working"
        ),
        (
            "$RefreshTrigger = New-ScheduledTaskTrigger -Once "
            "-At (Get-Date).AddMinutes(1) "
            f"-RepetitionInterval (New-TimeSpan -Minutes {frequent_minutes})"
        ),
        (
            "$NightlyTrigger = New-ScheduledTaskTrigger -Daily "
            f"-At ([datetime]::Today.AddHours({nightly_hour}))"
        ),
        (
            "$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable "
            "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
            "-MultipleInstances IgnoreNew"
        ),
        (
            "Register-ScheduledTask -TaskName $RefreshName -Action $RefreshAction "
            "-Trigger $RefreshTrigger -Settings $Settings -Force | Out-Null"
        ),
        (
            "Register-ScheduledTask -TaskName $NightlyName -Action $RefreshAction "
            "-Trigger $NightlyTrigger -Settings $Settings -Force | Out-Null"
        ),
        'Write-Host "Installed $RefreshName and $NightlyName"',
        "",
    ]
    return "\n".join(lines)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="tierfloor",
        description=(
            "Build runtime-attested internal model waterlines and provenance-bound "
            "external benchmark baselines without averaging incompatible evaluations."
        ),
    )
    commands = root.add_subparsers(dest="command", required=True)

    registry_validate = commands.add_parser("registry-validate")
    registry_validate.add_argument("--registry", type=Path, required=True)

    registry_convert = commands.add_parser("registry-from-models")
    registry_convert.add_argument("--models", type=Path, required=True)
    registry_convert.add_argument("--id", default="tier-bench-models")
    registry_convert.add_argument("--overrides", type=Path)
    registry_convert.add_argument("--out", type=Path, required=True)

    source_validate = commands.add_parser("sources-validate")
    source_validate.add_argument("--sources", type=Path, required=True)

    sync = commands.add_parser("sync")
    sync.add_argument("--sources", type=Path, required=True)
    sync.add_argument("--state-dir", type=Path, required=True)

    purge = commands.add_parser("purge")
    purge.add_argument("--sources", type=Path, required=True)
    purge.add_argument("--state-dir", type=Path, required=True)

    ingest = commands.add_parser("ingest-waterline")
    ingest.add_argument("--protocol", type=Path, required=True)
    ingest.add_argument("--report", type=Path, required=True)
    ingest.add_argument("--out", type=Path, required=True)
    ingest.add_argument("--append", action="store_true")

    ingest_root = commands.add_parser("ingest-root")
    ingest_root.add_argument("--protocol-root", type=Path, required=True)
    ingest_root.add_argument("--reports-root", type=Path, required=True)
    ingest_root.add_argument("--out", type=Path, required=True)
    ingest_root.add_argument("--receipt", type=Path)

    identity = commands.add_parser("identity-audit")
    identity.add_argument("--registry", type=Path, required=True)
    identity.add_argument("--observations", type=Path, action="append", required=True)
    identity.add_argument("--out", type=Path)

    compute = commands.add_parser("compute")
    compute.add_argument("--registry", type=Path, required=True)
    compute.add_argument("--config", type=Path, required=True)
    compute.add_argument("--observations", type=Path, action="append", required=True)
    compute.add_argument("--out", type=Path)

    delta = commands.add_parser("delta")
    delta.add_argument("--registry", type=Path, required=True)
    delta.add_argument("--protocol", type=Path, required=True)
    delta.add_argument("--waterline-report", type=Path, required=True)
    delta.add_argument("--external-observations", type=Path, action="append", default=[])
    delta.add_argument("--out", type=Path)

    refresh = commands.add_parser("refresh")
    refresh.add_argument("--sources", type=Path, required=True)
    refresh.add_argument("--registry", type=Path, required=True)
    refresh.add_argument("--config", type=Path, required=True)
    refresh.add_argument("--state-dir", type=Path, required=True)
    refresh.add_argument("--protocol-root", type=Path, required=True)
    refresh.add_argument("--reports-root", type=Path, required=True)
    refresh.add_argument("--opus-protocol", type=Path)
    refresh.add_argument("--opus-report", type=Path)

    status = commands.add_parser("status")
    status.add_argument("--state-dir", type=Path, required=True)

    schedule = commands.add_parser("schedule-windows")
    schedule.add_argument("--repo", type=Path, required=True)
    schedule.add_argument("--sources", type=Path, required=True)
    schedule.add_argument("--registry", type=Path, required=True)
    schedule.add_argument("--config", type=Path, required=True)
    schedule.add_argument("--state-dir", type=Path, required=True)
    schedule.add_argument("--protocol-root", type=Path, required=True)
    schedule.add_argument("--reports-root", type=Path, required=True)
    schedule.add_argument("--frequent-minutes", type=int, default=60)
    schedule.add_argument("--nightly-hour", type=int, default=3)
    schedule.add_argument("--out", type=Path, required=True)
    return root


def _registry(path: Path):
    return validate_registry(load_json(path))


def _print(value: Any) -> None:
    write_json(None, value)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "registry-validate":
            registry = _registry(args.registry)
            _print(
                {
                    "ok": True,
                    "registry_id": registry.registry["id"],
                    "registry_sha256": hash_json(registry.registry),
                    "models": len(registry.models),
                    "aliases": len(registry.aliases),
                    "surfaces": len(registry.surfaces),
                }
            )
            return 0

        if args.command == "registry-from-models":
            registry = registry_from_models_json(
                load_json(args.models),
                registry_id=args.id,
                overrides=load_json(args.overrides) if args.overrides else None,
            )
            write_json(args.out, registry)
            _print(
                {
                    "ok": True,
                    "out": str(args.out.resolve()),
                    "registry_id": registry["id"],
                    "registry_sha256": hash_json(registry),
                    "models": len(registry["models"]),
                }
            )
            return 0

        if args.command == "sources-validate":
            config = validate_source_config(
                load_json(args.sources), config_path=args.sources.resolve()
            )
            _print(
                {
                    "ok": True,
                    "config_id": config["id"],
                    "config_sha256": hash_json(config),
                    "sources": len(config["sources"]),
                    "enabled": sum(1 for row in config["sources"] if row["enabled"]),
                }
            )
            return 0

        if args.command == "sync":
            receipt = sync_sources(
                load_json(args.sources),
                config_path=args.sources.resolve(),
                state_dir=args.state_dir.resolve(),
            )
            _print(receipt)
            return 0 if not receipt["errors"] else 1

        if args.command == "purge":
            config = validate_source_config(
                load_json(args.sources), config_path=args.sources.resolve()
            )
            receipt = purge_state(
                args.state_dir.resolve(), retention_days=config["retention_days"]
            )
            _print(receipt)
            return 0

        if args.command == "ingest-waterline":
            rows = observations_from_waterline(
                load_json(args.protocol), load_json(args.report)
            )
            if args.append and args.out.exists():
                existing = read_jsonl(args.out)
                by_id = {row["id"]: row for row in existing}
                for row in rows:
                    by_id[row["id"]] = row
                rows = [by_id[key] for key in sorted(by_id)]
            write_observations(args.out, rows)
            _print(
                {
                    "ok": True,
                    "observations": len(rows),
                    "out": str(args.out.resolve()),
                }
            )
            return 0

        if args.command == "ingest-root":
            rows, receipt = ingest_waterline_tree(
                args.protocol_root.resolve(), args.reports_root.resolve()
            )
            write_observations(args.out, rows)
            write_json(args.receipt, receipt)
            _print(receipt)
            return 0 if not receipt["unmatched_reports"] else 1

        if args.command == "identity-audit":
            registry = _registry(args.registry)
            observations = load_observations(args.observations)
            report = audit_identities(observations, registry)
            write_json(args.out, report)
            return 0 if report["counts"].get("conflicted", 0) == 0 else 1

        if args.command == "compute":
            registry = _registry(args.registry)
            config = validate_floor_config(load_json(args.config))
            observations = load_observations(args.observations)
            report = compute_floor(registry, config, observations)
            write_json(args.out, report)
            return 0

        if args.command == "delta":
            registry = _registry(args.registry)
            external = (
                load_observations(args.external_observations)
                if args.external_observations
                else []
            )
            report = compute_delta_report(
                registry,
                load_json(args.protocol),
                load_json(args.waterline_report),
                external,
            )
            write_json(args.out, report)
            return 0

        if args.command == "refresh":
            state_dir = args.state_dir.resolve()
            state_dir.mkdir(parents=True, exist_ok=True)
            sync_receipt = sync_sources(
                load_json(args.sources),
                config_path=args.sources.resolve(),
                state_dir=state_dir / "external",
            )
            internal_rows, ingest_receipt = ingest_waterline_tree(
                args.protocol_root.resolve(), args.reports_root.resolve()
            )
            internal_path = state_dir / "internal-observations.jsonl"
            write_observations(internal_path, internal_rows)
            write_json(state_dir / "internal-ingest.json", ingest_receipt)
            external_path = state_dir / "external" / "observations.jsonl"
            observation_paths = [internal_path]
            if external_path.exists():
                observation_paths.append(external_path)
            registry = _registry(args.registry)
            observations = load_observations(observation_paths)
            report = compute_floor(
                registry,
                validate_floor_config(load_json(args.config)),
                observations,
            )
            write_json(state_dir / "floor-report.json", report)
            delta_report = None
            if bool(args.opus_protocol) != bool(args.opus_report):
                raise ModelFloorError(
                    "--opus-protocol and --opus-report must be supplied together"
                )
            if args.opus_protocol and args.opus_report:
                external = (
                    load_observations([external_path])
                    if external_path.exists()
                    else []
                )
                delta_report = compute_delta_report(
                    registry,
                    load_json(args.opus_protocol),
                    load_json(args.opus_report),
                    external,
                )
                write_json(state_dir / "opus-fable-delta.json", delta_report)
            receipt = {
                "schema": "tier-bench/model-floor-refresh@1",
                "created_at": now_utc(),
                "sync_sha256": sync_receipt["sync_sha256"],
                "ingest_sha256": ingest_receipt["ingest_sha256"],
                "floor_report_sha256": report["report_sha256"],
                "delta_report_sha256": (
                    delta_report["report_sha256"] if delta_report else None
                ),
                "counts": report["counts"],
                "source_errors": sync_receipt["errors"],
                "unmatched_reports": ingest_receipt["unmatched_reports"],
            }
            receipt["refresh_sha256"] = hash_json(
                {
                    key: value
                    for key, value in receipt.items()
                    if key != "refresh_sha256"
                }
            )
            write_json(state_dir / "last-refresh.json", receipt)
            _print(receipt)
            return 0 if not receipt["source_errors"] and not receipt["unmatched_reports"] else 1

        if args.command == "status":
            root = args.state_dir.resolve()
            paths = {
                "last_sync": root / "last-sync.json",
                "floor_report": root / "floor-report.json",
                "observations": root / "observations.jsonl",
                "community": root / "community.jsonl",
            }
            _print(
                {
                    "schema": "tier-bench/model-floor-status@1",
                    "created_at": now_utc(),
                    "state_dir": str(root),
                    "last_sync": (
                        load_json(paths["last_sync"])
                        if paths["last_sync"].exists()
                        else None
                    ),
                    "floor_report": (
                        load_json(paths["floor_report"])
                        if paths["floor_report"].exists()
                        else None
                    ),
                    "observation_count": (
                        len(read_jsonl(paths["observations"]))
                        if paths["observations"].exists()
                        else 0
                    ),
                    "community_item_count": (
                        len(read_jsonl(paths["community"]))
                        if paths["community"].exists()
                        else 0
                    ),
                }
            )
            return 0

        if args.command == "schedule-windows":
            if not 5 <= args.frequent_minutes <= 1440:
                raise ModelFloorError("--frequent-minutes must be between 5 and 1440")
            if not 0 <= args.nightly_hour <= 23:
                raise ModelFloorError("--nightly-hour must be between 0 and 23")
            script = windows_schedule_script(
                repo=args.repo,
                source_config=args.sources,
                registry=args.registry,
                floor_config=args.config,
                state_dir=args.state_dir,
                protocol_root=args.protocol_root,
                reports_root=args.reports_root,
                frequent_minutes=args.frequent_minutes,
                nightly_hour=args.nightly_hour,
            )
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(script, encoding="utf-8")
            _print(
                {
                    "ok": True,
                    "script": str(args.out.resolve()),
                    "frequent_minutes": args.frequent_minutes,
                    "nightly_hour": args.nightly_hour,
                }
            )
            return 0
    except (ModelFloorError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"tierfloor: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
