"""Operator CLI for the Tier Bench Conditional Memory Lab."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .conditional_memory_common import MemoryLabError, hash_json, load_json, write_json
from .conditional_memory_hardware import (
    monitor,
    probe_hardware,
    resolve_seat_environment,
    resolve_service_gpu,
)
from .conditional_memory_plan import (
    compile_plan,
    trial_by_id,
    trials_for_seat,
    verify_plan,
)
from .conditional_memory_report import (
    build_report,
    discover_receipts,
    status_report,
    validate_receipt,
)
from .conditional_memory_schema import resolve_profile


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="tiermemory",
        description=(
            "Run matched dense, PLE, fat-embedding, and n-gram-memory experiments "
            "with GPU UUID custody and append-only promotion receipts."
        ),
    )
    commands = root.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate")
    validate.add_argument("--lab", type=Path, required=True)
    validate.add_argument("--profile")

    plan = commands.add_parser("plan")
    plan.add_argument("--lab", type=Path, required=True)
    plan.add_argument("--profile")
    plan.add_argument("--out", type=Path)

    verify = commands.add_parser("verify-plan")
    verify.add_argument("--lab", type=Path, required=True)
    verify.add_argument("--plan", type=Path, required=True)

    probe = commands.add_parser("probe")
    probe.add_argument("--out", type=Path)

    watch = commands.add_parser("monitor")
    watch.add_argument("--out", type=Path, required=True)
    watch.add_argument("--stop-file", type=Path, required=True)
    watch.add_argument("--interval-seconds", type=float, default=1.0)
    watch.add_argument("--max-seconds", type=float)

    run = commands.add_parser("run")
    run.add_argument("--lab", type=Path, required=True)
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--trial", required=True)
    run.add_argument("--state-dir", type=Path, required=True)
    run.add_argument("--attempt", type=int, default=1)
    run.add_argument("--force-cpu", action="store_true")

    run_seat = commands.add_parser("run-seat")
    run_seat.add_argument("--lab", type=Path, required=True)
    run_seat.add_argument("--plan", type=Path, required=True)
    run_seat.add_argument("--seat", required=True)
    run_seat.add_argument("--state-dir", type=Path, required=True)
    run_seat.add_argument("--force-cpu", action="store_true")
    run_seat.add_argument("--stop-on-failure", action="store_true")
    run_seat.add_argument("--limit", type=int)

    status = commands.add_parser("status")
    status.add_argument("--lab", type=Path, required=True)
    status.add_argument("--plan", type=Path, required=True)
    status.add_argument("--state-dir", type=Path, required=True)

    report = commands.add_parser("report")
    report.add_argument("--lab", type=Path, required=True)
    report.add_argument("--plan", type=Path, required=True)
    report.add_argument("--state-dir", type=Path, required=True)
    report.add_argument("--out", type=Path)

    receipt = commands.add_parser("verify-receipt")
    receipt.add_argument("--plan", type=Path, required=True)
    receipt.add_argument("--receipt", type=Path, required=True)

    pack_export = commands.add_parser("pack-export")
    pack_export.add_argument("--receipt", type=Path, required=True)
    pack_export.add_argument("--out-dir", type=Path, required=True)
    pack_export.add_argument(
        "--dtype", choices=("fp32", "fp16", "bf16", "int8", "int4"), required=True
    )
    pack_export.add_argument("--group-size", type=int, default=128)

    pack_validate = commands.add_parser("pack-validate")
    pack_validate.add_argument("--manifest", type=Path, required=True)

    pack_profile = commands.add_parser("pack-profile")
    pack_profile.add_argument("--lab", type=Path, required=True)
    pack_profile.add_argument("--plan", type=Path, required=True)
    pack_profile.add_argument("--seat", required=True)
    pack_profile.add_argument("--manifest", type=Path, required=True)
    pack_profile.add_argument(
        "--placement", choices=("vram", "host_ram", "pinned_ram", "mmap"), required=True
    )
    pack_profile.add_argument("--out", type=Path, required=True)
    pack_profile.add_argument("--batch-rows", type=int, default=128)
    pack_profile.add_argument("--iterations", type=int, default=200)
    pack_profile.add_argument("--warmup", type=int, default=20)
    pack_profile.add_argument("--seed", type=int, default=1729)
    pack_profile.add_argument(
        "--pattern", choices=("random", "hotset", "sequential"), default="random"
    )
    pack_profile.add_argument("--force-cpu", action="store_true")

    pack_evaluate = commands.add_parser("pack-evaluate")
    pack_evaluate.add_argument("--lab", type=Path, required=True)
    pack_evaluate.add_argument("--plan", type=Path, required=True)
    pack_evaluate.add_argument("--receipt", type=Path, required=True)
    pack_evaluate.add_argument("--manifest", type=Path, required=True)
    pack_evaluate.add_argument("--seat", required=True)
    pack_evaluate.add_argument("--out", type=Path, required=True)
    pack_evaluate.add_argument("--chunk-rows", type=int, default=4096)
    pack_evaluate.add_argument("--force-cpu", action="store_true")
    return root


def _plan(lab_path: Path, plan_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    raw_lab = load_json(lab_path)
    raw_plan = load_json(plan_path)
    profile = raw_plan.get("profile") if isinstance(raw_plan, dict) else None
    errors = verify_plan(raw_lab, raw_plan, profile)
    if errors:
        raise MemoryLabError("plan verification failed: " + "; ".join(errors))
    return raw_lab, raw_plan


def _resolve_execution_seat(
    plan: dict[str, Any], seat: dict[str, Any], *, force_cpu: bool
) -> dict[str, Any]:
    service = resolve_service_gpu(
        plan["resolved"]["topology"], allow_cpu_override=force_cpu
    )
    resolution = resolve_seat_environment(seat, allow_cpu_override=force_cpu)
    if service is not None:
        selected_uuid = (resolution.get("gpu") or {}).get("uuid")
        service_uuid = (service.get("gpu") or {}).get("uuid")
        if selected_uuid and selected_uuid == service_uuid:
            raise MemoryLabError(
                f"execution seat {seat['id']} resolves to the declared service GPU"
            )
        resolution["service_gpu"] = service
    return resolution


def _torch_runner():
    try:
        from .conditional_memory_runner import execute_trial
    except ImportError as exc:
        raise MemoryLabError(
            "physical trials require PyTorch; install the CUDA build used by this bench"
        ) from exc
    return execute_trial


def _torch_pack():
    try:
        import torch
        from .conditional_memory_pack import (
            evaluate_pack,
            export_pack,
            profile_pack,
            validate_pack,
        )
    except ImportError as exc:
        raise MemoryLabError(
            "memory-pack export and profiling require PyTorch"
        ) from exc
    return torch, evaluate_pack, export_pack, profile_pack, validate_pack


def _attempt_state(
    state_dir: Path, plan: dict[str, Any]
) -> tuple[set[str], dict[str, int]]:
    completed: set[str] = set()
    maximum: dict[str, int] = {}
    for _, receipt in discover_receipts(state_dir, plan):
        errors = validate_receipt(receipt, plan)
        if errors:
            continue
        trial_id = receipt["trial_id"]
        maximum[trial_id] = max(maximum.get(trial_id, 0), int(receipt["attempt"]))
        if receipt["status"] == "completed":
            completed.add(trial_id)
    return completed, maximum


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "validate":
            lab = resolve_profile(load_json(args.lab), args.profile)
            write_json(
                None,
                {
                    "ok": True,
                    "lab_id": lab["id"],
                    "profile": lab["profile"],
                    "lab_sha256": hash_json(lab),
                    "arms": [arm["id"] for arm in lab["arms"]],
                    "seeds": lab["training"]["seeds"],
                    "seats": [seat["id"] for seat in lab["topology"]["seats"]],
                },
            )
            return 0
        if args.command == "plan":
            plan = compile_plan(load_json(args.lab), args.profile)
            write_json(args.out, plan)
            return 0
        if args.command == "verify-plan":
            raw_lab = load_json(args.lab)
            raw_plan = load_json(args.plan)
            profile = raw_plan.get("profile") if isinstance(raw_plan, dict) else None
            errors = verify_plan(raw_lab, raw_plan, profile)
            write_json(None, {"ok": not errors, "errors": errors})
            return int(bool(errors))
        if args.command == "probe":
            value = probe_hardware()
            write_json(args.out, value)
            return 0 if not value["errors"] else 1
        if args.command == "monitor":
            summary = monitor(
                out=args.out,
                stop_file=args.stop_file,
                interval_seconds=args.interval_seconds,
                max_seconds=args.max_seconds,
            )
            write_json(None, summary)
            return 0 if summary["ok"] else 1
        if args.command == "run":
            _, plan = _plan(args.lab, args.plan)
            trial = trial_by_id(plan, args.trial)
            seat_resolution = _resolve_execution_seat(
                plan, trial["seat"], force_cpu=args.force_cpu
            )
            execute_trial = _torch_runner()
            receipt = execute_trial(
                plan=plan,
                trial=trial,
                state_dir=args.state_dir,
                seat_resolution=seat_resolution,
                attempt=args.attempt,
                force_cpu=args.force_cpu,
            )
            write_json(None, receipt)
            return 0 if receipt["status"] == "completed" else 1
        if args.command == "run-seat":
            _, plan = _plan(args.lab, args.plan)
            trials = trials_for_seat(plan, args.seat)
            if args.limit is not None:
                trials = trials[: args.limit]
            seat = trials[0]["seat"]
            seat_resolution = _resolve_execution_seat(
                plan, seat, force_cpu=args.force_cpu
            )
            execute_trial = _torch_runner()
            completed, maximum = _attempt_state(args.state_dir, plan)
            results: list[dict[str, Any]] = []
            for trial in trials:
                if trial["id"] in completed:
                    results.append({"trial_id": trial["id"], "status": "skipped_completed"})
                    continue
                attempt = maximum.get(trial["id"], 0) + 1
                receipt = execute_trial(
                    plan=plan,
                    trial=trial,
                    state_dir=args.state_dir,
                    seat_resolution=seat_resolution,
                    attempt=attempt,
                    force_cpu=args.force_cpu,
                )
                results.append(
                    {
                        "trial_id": trial["id"],
                        "status": receipt["status"],
                        "attempt": attempt,
                        "receipt_sha256": receipt["receipt_sha256"],
                    }
                )
                if receipt["status"] != "completed" and args.stop_on_failure:
                    break
            summary = {
                "ok": all(row["status"] in {"completed", "skipped_completed"} for row in results),
                "seat": args.seat,
                "plan_sha256": plan["plan_sha256"],
                "results": results,
            }
            write_json(None, summary)
            return 0 if summary["ok"] else 1
        if args.command == "status":
            _, plan = _plan(args.lab, args.plan)
            value = status_report(plan, args.state_dir)
            write_json(None, value)
            return 0 if value["ok"] else 1
        if args.command == "report":
            _, plan = _plan(args.lab, args.plan)
            value = build_report(plan, args.state_dir)
            write_json(args.out, value)
            return 0 if value["status"]["ok"] else 1
        if args.command == "verify-receipt":
            plan = load_json(args.plan)
            errors = validate_receipt(load_json(args.receipt), plan)
            write_json(None, {"ok": not errors, "errors": errors})
            return int(bool(errors))
        if args.command == "pack-export":
            _, _, export_pack, _, _ = _torch_pack()
            value = export_pack(
                receipt_path=args.receipt,
                out_dir=args.out_dir,
                dtype=args.dtype,
                group_size=args.group_size,
            )
            write_json(None, value)
            return 0
        if args.command == "pack-validate":
            _, _, _, _, validate_pack = _torch_pack()
            manifest, root = validate_pack(args.manifest)
            write_json(
                None,
                {
                    "ok": True,
                    "pack_sha256": manifest["pack_sha256"],
                    "manifest_sha256": manifest["manifest_sha256"],
                    "root": str(root),
                    "dtype": manifest["quantization"]["dtype"],
                    "rows": manifest["table"]["rows"],
                    "width": manifest["table"]["width"],
                    "artifact_bytes": manifest["artifact"]["bytes"],
                    "quality": manifest["quality"],
                },
            )
            return 0
        if args.command == "pack-profile":
            _, plan = _plan(args.lab, args.plan)
            seat = trials_for_seat(plan, args.seat)[0]["seat"]
            seat_resolution = _resolve_execution_seat(
                plan, seat, force_cpu=args.force_cpu
            )
            torch, _, _, profile_pack, _ = _torch_pack()
            device = torch.device(
                "cpu" if args.force_cpu or seat["kind"] == "cpu" else "cuda:0"
            )
            value = profile_pack(
                manifest_path=args.manifest,
                placement=args.placement,
                device=device,
                batch_rows=args.batch_rows,
                iterations=args.iterations,
                warmup=args.warmup,
                seed=args.seed,
                pattern=args.pattern,
                out=args.out,
                seat_resolution=seat_resolution,
            )
            write_json(None, value)
            return 0
        if args.command == "pack-evaluate":
            _, plan = _plan(args.lab, args.plan)
            seat = trials_for_seat(plan, args.seat)[0]["seat"]
            seat_resolution = _resolve_execution_seat(
                plan, seat, force_cpu=args.force_cpu
            )
            torch, evaluate_pack, _, _, _ = _torch_pack()
            device = torch.device(
                "cpu" if args.force_cpu or seat["kind"] == "cpu" else "cuda:0"
            )
            value = evaluate_pack(
                plan=plan,
                receipt_path=args.receipt,
                manifest_path=args.manifest,
                device=device,
                out=args.out,
                seat_resolution=seat_resolution,
                chunk_rows=args.chunk_rows,
            )
            write_json(None, value)
            return 0
    except (MemoryLabError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"tiermemory: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
