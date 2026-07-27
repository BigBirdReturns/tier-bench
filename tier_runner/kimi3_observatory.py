"""CLI for the Kimi K3 Open-Weight Observatory."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

from .kimi3_common import (
    OBSERVATORY_SCHEMA,
    EXECUTION_BUNDLE_SCHEMA,
    KimiObservatoryError,
    exclusive_lock,
    hash_json,
    load_json,
    need_array,
    need_bool,
    need_int,
    need_object,
    need_text,
    now_utc,
    safe_id,
    write_json,
)
from .kimi3_community import (
    extract_claims,
    fuse_claims_with_plan,
    purge_community,
    sync_community,
    validate_community_config,
)
from .kimi3_probe import reduce_router_trace, simulate_expert_cache
from .kimi3_weights import (
    DEFAULT_CHUNK_BYTES,
    build_dissection_plan,
    freeze_baseline,
    numeric_sample,
    scan_model,
)


def _resolve(base: Path, value: str) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(value)))
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def validate_observatory_config(raw: Any, *, config_path: Path) -> dict[str, Any]:
    value = need_object(raw, "observatory config")
    if value.get("schema") != OBSERVATORY_SCHEMA:
        raise KimiObservatoryError(f"observatory schema must be {OBSERVATORY_SCHEMA}")
    unknown = set(value) - {
        "schema",
        "id",
        "model_root",
        "state_dir",
        "grid_root",
        "community_config",
        "stable_age_seconds",
        "chunk_mib",
        "frequent_interval_minutes",
        "nightly_hour",
        "numeric_patterns",
        "numeric_max_tensors",
        "numeric_samples_per_tensor",
        "defer_heavy_when_exists",
    }
    if unknown:
        raise KimiObservatoryError(f"unknown observatory config fields: {sorted(unknown)}")
    base = config_path.parent.resolve()
    config: dict[str, Any] = {
        "schema": OBSERVATORY_SCHEMA,
        "id": safe_id(value.get("id"), "observatory id"),
        "model_root": str(_resolve(base, need_text(value.get("model_root"), "model_root", limit=2000))),
        "state_dir": str(_resolve(base, need_text(value.get("state_dir"), "state_dir", limit=2000))),
        "stable_age_seconds": need_int(
            value.get("stable_age_seconds", 120),
            "stable_age_seconds",
            low=0,
            high=7 * 24 * 3600,
        ),
        "chunk_mib": need_int(value.get("chunk_mib", 256), "chunk_mib", low=1, high=8192),
        "frequent_interval_minutes": need_int(
            value.get("frequent_interval_minutes", 30),
            "frequent_interval_minutes",
            low=5,
            high=1440,
        ),
        "nightly_hour": need_int(value.get("nightly_hour", 2), "nightly_hour", low=0, high=23),
        "numeric_patterns": [
            need_text(item, "numeric_patterns[]", limit=500)
            for item in need_array(value.get("numeric_patterns", []), "numeric_patterns")
        ],
        "numeric_max_tensors": need_int(
            value.get("numeric_max_tensors", 256),
            "numeric_max_tensors",
            low=1,
            high=100000,
        ),
        "numeric_samples_per_tensor": need_int(
            value.get("numeric_samples_per_tensor", 64),
            "numeric_samples_per_tensor",
            low=1,
            high=4096,
        ),
        "defer_heavy_when_exists": [
            str(_resolve(base, need_text(item, "defer_heavy_when_exists[]", limit=2000)))
            for item in need_array(
                value.get("defer_heavy_when_exists", []),
                "defer_heavy_when_exists",
            )
        ],
    }
    for key in ("grid_root", "community_config"):
        raw_path = value.get(key)
        config[key] = str(_resolve(base, raw_path)) if isinstance(raw_path, str) and raw_path else None
    return config


def _config(path: Path) -> dict[str, Any]:
    return validate_observatory_config(load_json(path), config_path=path.resolve())


def _state_paths(config: dict[str, Any]) -> dict[str, Path]:
    root = Path(config["state_dir"])
    return {
        "root": root,
        "scan": root / "model",
        "hash_state": root / "hash-state",
        "community": root / "community",
        "baselines": root / "baselines",
        "logs": root / "logs",
        "lock": root / "observatory.lock",
    }


def _load_scan_bundle(paths: dict[str, Path]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return (
        load_json(paths["scan"] / "model-scan.json"),
        load_json(paths["scan"] / "tensor-census.json"),
        load_json(paths["scan"] / "dissection-plan.json"),
    )


def _run_scan(config: dict[str, Any], *, profile: str) -> tuple[dict[str, Any], dict[str, Any]]:
    paths = _state_paths(config)
    hash_large = profile in {"nightly", "full"}
    full_hash = profile == "full"
    scan = scan_model(
        Path(config["model_root"]),
        out_dir=paths["scan"],
        state_dir=paths["hash_state"],
        stable_age_seconds=config["stable_age_seconds"],
        chunk_bytes=config["chunk_mib"] * 1024 * 1024,
        hash_large_files=hash_large,
        full_hash_large_files=full_hash,
    )
    census = load_json(paths["scan"] / "tensor-census.json")
    plan = build_dissection_plan(scan, census)
    write_json(paths["scan"] / "dissection-plan.json", plan)
    if profile in {"nightly", "full"} and config["numeric_patterns"]:
        sample = numeric_sample(
            Path(config["model_root"]),
            tensor_index=paths["scan"] / "tensors.jsonl",
            patterns=config["numeric_patterns"],
            max_tensors=config["numeric_max_tensors"],
            samples_per_tensor=config["numeric_samples_per_tensor"],
        )
        write_json(paths["scan"] / "numeric-sample.json", sample)
    return scan, plan


def _run_community(config: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    community_config = config.get("community_config")
    if not community_config:
        return None, None
    paths = _state_paths(config)
    raw = load_json(Path(community_config))
    sync = sync_community(raw, state_dir=paths["community"])
    claims = extract_claims(state_dir=paths["community"])
    fusion = fuse_claims_with_plan(
        claims_path=paths["community"] / "claims.jsonl",
        dissection_plan_path=paths["scan"] / "dissection-plan.json",
    )
    write_json(paths["community"] / "hypothesis-queue.json", fusion)
    return sync, fusion


def _heavy_defer_reasons(config: dict[str, Any]) -> list[str]:
    return [
        path
        for path in config.get("defer_heavy_when_exists", [])
        if Path(path).exists()
    ]


def _work_order_activation(order_id: str) -> dict[str, Any]:
    automatic = {
        "K3-A00-download-convergence": ["frequent", "nightly", "full"],
        "K3-A01-byte-custody": ["nightly", "full"],
        "K3-A02-index-concordance": ["frequent", "nightly", "full"],
        "K3-B01-source-architecture-map": ["frequent", "nightly", "full"],
        "K3-B02-layer-topology": ["frequent", "nightly", "full"],
        "K3-B03-expert-estate": ["frequent", "nightly", "full"],
        "K3-B04-precision-map": ["frequent", "nightly", "full"],
        "K3-C01-numeric-fingerprints": ["nightly", "full"],
    }
    templates = {
        "K3-C02-expert-redundancy": "candidate worker: compare independent numeric samples by layer and expert",
        "K3-D01-runtime-module-trace": "wrap the exact open-weight runtime with tier_runner.kimi3_probe.ProbeSession",
        "K3-D02-router-utilization-grid": "tierkimi probe-reduce --config <config> --trace <trace.jsonl>",
        "K3-D03-long-context-state": "run the frozen context-length grid under the exact full-runtime revision",
        "K3-E01-expert-offload-simulator": "tierkimi offload-simulate --config <config> --trace <trace.jsonl> ...",
        "K3-E02-ablation-grid": "rerun the frozen baseline with one bounded intervention per arm",
        "K3-F01-desktop-capture": "send accepted residue into tierdistill and the capture ledger",
    }
    if order_id in automatic:
        return {
            "dispatch_state": "AUTOMATED",
            "automatic_profiles": automatic[order_id],
            "command_template": "tierkimi observe --config <config> --profile <profile>",
        }
    return {
        "dispatch_state": "READY_MANUAL",
        "automatic_profiles": [],
        "command_template": templates.get(order_id, "operator work order"),
    }


def build_execution_bundle(
    config: dict[str, Any],
    plan: dict[str, Any],
    fusion: dict[str, Any] | None,
) -> dict[str, Any]:
    claims_by_order: dict[str, list[str]] = {}
    if fusion:
        for hypothesis in fusion.get("hypotheses", []):
            for order_id in hypothesis.get("work_orders", []):
                claims_by_order.setdefault(order_id, []).append(hypothesis["id"])
    rows = []
    order_ids = {row["id"] for row in plan.get("work_orders", [])}
    for order in plan.get("work_orders", []):
        activation = _work_order_activation(order["id"])
        missing = [item for item in order.get("prerequisites", []) if item not in order_ids]
        rows.append(
            {
                **order,
                **activation,
                "community_hypotheses": sorted(claims_by_order.get(order["id"], [])),
                "missing_prerequisites": missing,
            }
        )
    bundle = {
        "schema": EXECUTION_BUNDLE_SCHEMA,
        "created_at": now_utc(),
        "config_id": config["id"],
        "config_sha256": hash_json(config),
        "model_estate_sha256": plan.get("model_estate_sha256"),
        "dissection_plan_sha256": plan["plan_sha256"],
        "hypothesis_queue_sha256": fusion.get("queue_sha256") if fusion else None,
        "work_orders": rows,
        "totals": {
            "orders": len(rows),
            "automated": sum(1 for row in rows if row["dispatch_state"] == "AUTOMATED"),
            "manual": sum(1 for row in rows if row["dispatch_state"] == "READY_MANUAL"),
            "community_linked": sum(1 for row in rows if row["community_hypotheses"]),
        },
        "laws": [
            "The canonical downloaded weight estate remains read-only.",
            "Community claims may reprioritize a work order but cannot close it.",
            "The frozen baseline is never rewritten by later discoveries.",
            "Interventions execute against derived copies, adapters, or runtime hooks.",
        ],
    }
    bundle["bundle_sha256"] = hash_json(
        {key: value for key, value in bundle.items() if key != "bundle_sha256"}
    )
    return bundle


def observe(config: dict[str, Any], *, profile: str) -> dict[str, Any]:
    paths = _state_paths(config)
    paths["root"].mkdir(parents=True, exist_ok=True)
    with exclusive_lock(paths["lock"]):
        defer_reasons = _heavy_defer_reasons(config) if profile in {"nightly", "full"} else []
        executed_profile = "frequent" if defer_reasons else profile
        scan, plan = _run_scan(config, profile=executed_profile)
        community_sync, fusion = _run_community(config)
        bundle = build_execution_bundle(config, plan, fusion)
        write_json(paths["root"] / "execution-bundle.json", bundle)
        receipt = {
            "schema": "tier-bench/kimi3-observation-cycle@1",
            "id": config["id"],
            "created_at": now_utc(),
            "requested_profile": profile,
            "executed_profile": executed_profile,
            "deferred_heavy_scan": bool(defer_reasons),
            "defer_reasons": defer_reasons,
            "config_sha256": hash_json(config),
            "model": {
                "scan_sha256": scan["scan_sha256"],
                "pending_files": scan["totals"]["pending_files"],
                "files": scan["totals"]["files"],
                "bytes": scan["totals"]["bytes"],
                "tensors": scan["totals"]["tensors"],
                "model_estate_sha256": scan["model_estate_sha256"],
                "dissection_plan_sha256": plan["plan_sha256"],
                "execution_bundle_sha256": bundle["bundle_sha256"],
            },
            "community": (
                {
                    "sync_sha256": community_sync["sync_sha256"],
                    "blocked_sources": community_sync["totals"]["blocked_sources"],
                    "hypothesis_queue_sha256": fusion["queue_sha256"],
                    "hypotheses": fusion["totals"]["hypotheses"],
                }
                if community_sync and fusion
                else None
            ),
        }
        receipt["cycle_sha256"] = hash_json(
            {key: value for key, value in receipt.items() if key != "cycle_sha256"}
        )
        paths["logs"].mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        write_json(paths["logs"] / f"cycle-{stamp}.json", receipt)
        write_json(paths["root"] / "last-cycle.json", receipt)
        return receipt


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def windows_schedule_script(config_path: Path, config: dict[str, Any]) -> str:
    repo = config_path.resolve().parents[2] if len(config_path.resolve().parents) >= 3 else Path.cwd()
    python_exe = sys.executable
    frequent = config["frequent_interval_minutes"]
    nightly_hour = config["nightly_hour"]
    frequent_name = f"TierKimi-{config['id']}-Frequent"
    nightly_name = f"TierKimi-{config['id']}-Nightly"
    config_argument = str(config_path.resolve()).replace('"', '\\"')
    command_base = (
        f'-m tier_runner.kimi3_observatory observe --config "{config_argument}"'
    )
    lines = [
        "$ErrorActionPreference = 'Stop'",
        f"$Python = {_powershell_quote(python_exe)}",
        f"$Working = {_powershell_quote(str(repo))}",
        f"$FrequentName = {_powershell_quote(frequent_name)}",
        f"$NightlyName = {_powershell_quote(nightly_name)}",
        (
            "$FrequentAction = New-ScheduledTaskAction -Execute $Python "
            f"-Argument {_powershell_quote(command_base + ' --profile frequent')} "
            "-WorkingDirectory $Working"
        ),
        (
            "$NightlyAction = New-ScheduledTaskAction -Execute $Python "
            f"-Argument {_powershell_quote(command_base + ' --profile nightly')} "
            "-WorkingDirectory $Working"
        ),
        (
            "$FrequentTrigger = New-ScheduledTaskTrigger -Once "
            "-At (Get-Date).AddMinutes(1) "
            f"-RepetitionInterval (New-TimeSpan -Minutes {frequent})"
        ),
        (
            f"$NightlyTrigger = New-ScheduledTaskTrigger -Daily "
            f"-At ([datetime]::Today.AddHours({nightly_hour}))"
        ),
        "$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable "
        "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        "-MultipleInstances IgnoreNew",
        "Register-ScheduledTask -TaskName $FrequentName -Action $FrequentAction "
        "-Trigger $FrequentTrigger -Settings $Settings -Force | Out-Null",
        "Register-ScheduledTask -TaskName $NightlyName -Action $NightlyAction "
        "-Trigger $NightlyTrigger -Settings $Settings -Force | Out-Null",
        "Write-Host \"Installed $FrequentName and $NightlyName\"",
        "",
    ]
    return "\n".join(lines)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="tierkimi",
        description=(
            "Index, dissect, baseline, and continuously observe the Kimi K3 open-weight estate"
        ),
    )
    commands = root.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate")
    validate.add_argument("--config", type=Path, required=True)

    scan = commands.add_parser("scan")
    scan.add_argument("--config", type=Path, required=True)
    scan.add_argument("--profile", choices=["frequent", "nightly", "full"], default="frequent")

    plan = commands.add_parser("plan")
    plan.add_argument("--config", type=Path, required=True)
    plan.add_argument("--out", type=Path)

    bundle = commands.add_parser("work-bundle")
    bundle.add_argument("--config", type=Path, required=True)
    bundle.add_argument("--out", type=Path)

    sample = commands.add_parser("numeric-sample")
    sample.add_argument("--config", type=Path, required=True)
    sample.add_argument("--pattern", action="append", default=[])
    sample.add_argument("--max-tensors", type=int)
    sample.add_argument("--samples-per-tensor", type=int)
    sample.add_argument("--out", type=Path)

    freeze = commands.add_parser("baseline-freeze")
    freeze.add_argument("--config", type=Path, required=True)
    freeze.add_argument("--label", required=True)
    freeze.add_argument("--out", type=Path)

    community_validate = commands.add_parser("community-validate")
    community_validate.add_argument("--config", type=Path, required=True)

    community_sync = commands.add_parser("community-sync")
    community_sync.add_argument("--config", type=Path, required=True)

    claims = commands.add_parser("community-claims")
    claims.add_argument("--config", type=Path, required=True)
    claims.add_argument("--minimum-score", type=int, default=0)

    fuse = commands.add_parser("community-fuse")
    fuse.add_argument("--config", type=Path, required=True)
    fuse.add_argument("--out", type=Path)

    purge = commands.add_parser("community-purge")
    purge.add_argument("--config", type=Path, required=True)

    observe_parser = commands.add_parser("observe")
    observe_parser.add_argument("--config", type=Path, required=True)
    observe_parser.add_argument(
        "--profile",
        choices=["frequent", "nightly", "full"],
        default="frequent",
    )
    observe_parser.add_argument("--loop", action="store_true")
    observe_parser.add_argument("--interval-seconds", type=int, default=1800)

    schedule = commands.add_parser("schedule-windows")
    schedule.add_argument("--config", type=Path, required=True)
    schedule.add_argument("--out", type=Path, required=True)

    probe_reduce = commands.add_parser("probe-reduce")
    probe_reduce.add_argument("--config", type=Path, required=True)
    probe_reduce.add_argument("--trace", type=Path, required=True)
    probe_reduce.add_argument("--out", type=Path)

    offload = commands.add_parser("offload-simulate")
    offload.add_argument("--config", type=Path, required=True)
    offload.add_argument("--trace", type=Path, required=True)
    offload.add_argument("--expert-bytes", type=int, required=True)
    offload.add_argument("--gpu-experts", type=int, required=True)
    offload.add_argument("--ram-experts", type=int, required=True)
    offload.add_argument("--pcie-gbps", type=float, required=True)
    offload.add_argument("--nvme-gbps", type=float, required=True)
    offload.add_argument("--prewarm-experts", type=int, default=0)
    offload.add_argument("--out", type=Path)

    status = commands.add_parser("status")
    status.add_argument("--config", type=Path, required=True)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        config = _config(args.config)
        paths = _state_paths(config)
        if args.command == "validate":
            community = None
            if config["community_config"]:
                community = validate_community_config(load_json(Path(config["community_config"])))
            write_json(
                None,
                {
                    "ok": True,
                    "config": config,
                    "config_sha256": hash_json(config),
                    "community_config_sha256": hash_json(community) if community else None,
                },
            )
            return 0
        if args.command == "scan":
            scan, plan = _run_scan(config, profile=args.profile)
            write_json(
                None,
                {
                    "ok": True,
                    "scan_sha256": scan["scan_sha256"],
                    "plan_sha256": plan["plan_sha256"],
                    "totals": scan["totals"],
                },
            )
            return 0
        if args.command == "plan":
            _, _, plan = _load_scan_bundle(paths)
            write_json(args.out, plan)
            return 0
        if args.command == "work-bundle":
            _, _, plan = _load_scan_bundle(paths)
            fusion_path = paths["community"] / "hypothesis-queue.json"
            fusion = load_json(fusion_path) if fusion_path.exists() else None
            bundle = build_execution_bundle(config, plan, fusion)
            write_json(args.out or paths["root"] / "execution-bundle.json", bundle)
            return 0
        if args.command == "numeric-sample":
            patterns = args.pattern or config["numeric_patterns"]
            report = numeric_sample(
                Path(config["model_root"]),
                tensor_index=paths["scan"] / "tensors.jsonl",
                patterns=patterns,
                max_tensors=args.max_tensors or config["numeric_max_tensors"],
                samples_per_tensor=(
                    args.samples_per_tensor or config["numeric_samples_per_tensor"]
                ),
            )
            write_json(args.out, report)
            return 0
        if args.command == "baseline-freeze":
            if not config["grid_root"]:
                raise KimiObservatoryError("grid_root is required to freeze a baseline")
            baseline = freeze_baseline(
                scan_path=paths["scan"] / "model-scan.json",
                census_path=paths["scan"] / "tensor-census.json",
                plan_path=paths["scan"] / "dissection-plan.json",
                grid_root=Path(config["grid_root"]),
                label=args.label,
            )
            destination = args.out or paths["baselines"] / f"{args.label}.json"
            if destination.exists():
                raise KimiObservatoryError(f"baseline already exists: {destination}")
            write_json(destination, baseline)
            write_json(None, baseline)
            return 0
        if args.command == "community-validate":
            if not config["community_config"]:
                raise KimiObservatoryError("community_config is not set")
            community = validate_community_config(load_json(Path(config["community_config"])))
            write_json(None, {"ok": True, "config": community, "sha256": hash_json(community)})
            return 0
        if args.command == "community-sync":
            if not config["community_config"]:
                raise KimiObservatoryError("community_config is not set")
            receipt = sync_community(
                load_json(Path(config["community_config"])),
                state_dir=paths["community"],
            )
            write_json(None, receipt)
            return 0 if not receipt["errors"] else 1
        if args.command == "community-claims":
            report = extract_claims(
                state_dir=paths["community"],
                minimum_score=args.minimum_score,
            )
            write_json(None, report)
            return 0
        if args.command == "community-fuse":
            queue = fuse_claims_with_plan(
                claims_path=paths["community"] / "claims.jsonl",
                dissection_plan_path=paths["scan"] / "dissection-plan.json",
            )
            write_json(args.out or paths["community"] / "hypothesis-queue.json", queue)
            return 0
        if args.command == "community-purge":
            if not config["community_config"]:
                raise KimiObservatoryError("community_config is not set")
            community = validate_community_config(load_json(Path(config["community_config"])))
            receipt = purge_community(
                state_dir=paths["community"],
                retention_days=community["retention_days"],
            )
            write_json(None, receipt)
            return 0
        if args.command == "observe":
            if args.interval_seconds < 60:
                raise KimiObservatoryError("--interval-seconds must be at least 60")
            while True:
                receipt = observe(config, profile=args.profile)
                write_json(None, receipt)
                if not args.loop:
                    return 0
                time.sleep(args.interval_seconds)
        if args.command == "schedule-windows":
            script = windows_schedule_script(args.config, config)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(script, encoding="utf-8")
            write_json(
                None,
                {
                    "ok": True,
                    "script": str(args.out.resolve()),
                    "frequent_interval_minutes": config["frequent_interval_minutes"],
                    "nightly_hour": config["nightly_hour"],
                },
            )
            return 0
        if args.command == "probe-reduce":
            report = reduce_router_trace(args.trace)
            write_json(args.out or paths["scan"] / "router-report.json", report)
            return 0
        if args.command == "offload-simulate":
            report = simulate_expert_cache(
                args.trace,
                expert_bytes=args.expert_bytes,
                gpu_experts=args.gpu_experts,
                ram_experts=args.ram_experts,
                pcie_gbps=args.pcie_gbps,
                nvme_gbps=args.nvme_gbps,
                prewarm_experts=args.prewarm_experts,
            )
            write_json(args.out or paths["scan"] / "expert-offload-simulation.json", report)
            return 0
        if args.command == "status":
            status_value = {
                "schema": "tier-bench/kimi3-observatory-status@1",
                "created_at": now_utc(),
                "config_id": config["id"],
                "state_dir": str(paths["root"]),
                "last_cycle": (
                    load_json(paths["root"] / "last-cycle.json")
                    if (paths["root"] / "last-cycle.json").exists()
                    else None
                ),
                "model_scan": (
                    load_json(paths["scan"] / "model-scan.json")
                    if (paths["scan"] / "model-scan.json").exists()
                    else None
                ),
                "community_sync": (
                    load_json(paths["community"] / "last-sync.json")
                    if (paths["community"] / "last-sync.json").exists()
                    else None
                ),
            }
            write_json(None, status_value)
            return 0
    except (
        KimiObservatoryError,
        OSError,
        ValueError,
        json.JSONDecodeError,
        re.error,
    ) as exc:
        print(f"tierkimi: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
