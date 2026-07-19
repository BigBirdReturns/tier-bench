from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

from .core import RunError, run_task, verify_run
from .events import InterventionError, start, stop, validate_events
from .manifest import ManifestError
from .pilot import (
    PilotError,
    canonical_json,
    close_pilot,
    derive_schedule,
    validate_plan,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tier", description="Fail-closed daily task runner")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run one sealed backend call in a disposable worktree")
    run.add_argument("--repo", type=Path, required=True)
    run.add_argument("--task-id", help="stable id; defaults to a hash of the task text")
    task_source = run.add_mutually_exclusive_group(required=True)
    task_source.add_argument("--task")
    task_source.add_argument("--task-file", type=Path)
    files_source = run.add_mutually_exclusive_group(required=True)
    files_source.add_argument(
        "--files", action="append",
        help="allowed file or directory scope; repeat or comma-separate",
    )
    files_source.add_argument(
        "--files-file", type=Path,
        help="UTF-8 JSON array of allowed repository-relative scopes",
    )
    acceptance_source = run.add_mutually_exclusive_group(required=True)
    acceptance_source.add_argument(
        "--acceptance", help="trusted operator-supplied shell command"
    )
    acceptance_source.add_argument(
        "--acceptance-file", type=Path,
        help="UTF-8 file containing the trusted operator-supplied shell command",
    )
    run.add_argument("--backend-manifest", type=Path,
                     help="defaults to <repo>/pilot_backends.json")
    run.add_argument("--arm", choices=["arm_a", "arm_b", "arm_c"], default="arm_b")
    run.add_argument("--output-dir", type=Path)

    desk = sub.add_parser(
        "desk", help="open Monster Wrangler, the persistent local agent control desk"
    )
    desk.add_argument("--repo", type=Path, required=True, help="repository managed by the desk")
    desk.add_argument("--host", default="127.0.0.1")
    desk.add_argument("--port", type=int, default=8765)
    desk.add_argument("--state-dir", type=Path)
    desk.add_argument("--no-open", action="store_true", help="do not open a browser")
    desk.add_argument("--daemon", action="store_true", help="start detached and return")
    desk.add_argument("--stop", action="store_true", help="stop the detached desk")
    desk.add_argument("--status", action="store_true", help="print detached desk status")
    desk.add_argument("--unsafe-network", action="store_true", help="allow a non-loopback bind")
    desk.add_argument("--max-workers", type=int, choices=range(1, 9))
    desk.add_argument("--foreground-child", action="store_true", help=argparse.SUPPRESS)

    intervention = sub.add_parser("intervention", help="append operator-time start/stop events")
    intervention_sub = intervention.add_subparsers(dest="event", required=True)
    begin = intervention_sub.add_parser("start")
    begin.add_argument("--log", type=Path, required=True)
    begin.add_argument("--task-id", required=True)
    begin.add_argument("--arm", choices=["arm_a", "arm_b", "arm_c"], required=True)
    begin.add_argument("--category", required=True)
    begin.add_argument("--reference-id")
    end = intervention_sub.add_parser("stop")
    end.add_argument("--log", type=Path, required=True)
    end.add_argument("--id", required=True)

    verify = sub.add_parser(
        "verify-interventions", help="validate append-only intervention pairing"
    )
    verify.add_argument("--log", type=Path, required=True)
    verify_run_parser = sub.add_parser("verify", help="verify a run's hashes and bindings")
    verify_run_parser.add_argument("--run-dir", type=Path, required=True)

    pilot = sub.add_parser(
        "pilot", help="validate and close the proposal-only driver-boundary administration"
    )
    pilot_sub = pilot.add_subparsers(dest="pilot_command", required=True)
    pilot_schedule = pilot_sub.add_parser(
        "schedule", help="derive the frozen three-arm schedule from a draft plan"
    )
    pilot_schedule.add_argument("--plan", type=Path, required=True)
    pilot_validate = pilot_sub.add_parser(
        "validate", help="validate an exact ten-task plan without dispatching anything"
    )
    pilot_validate.add_argument("--plan", type=Path, required=True)
    pilot_close = pilot_sub.add_parser(
        "close", help="fail closed over sealed pilot administration evidence"
    )
    pilot_close.add_argument("--plan", type=Path, required=True)
    pilot_close.add_argument("--evidence", type=Path, required=True)
    pilot_close.add_argument(
        "--as-of", help="ISO-8601 verification instant; defaults to current UTC time"
    )
    pilot_close.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "desk":
        from .desk import DeskError, run_cli

        try:
            return run_cli(args)
        except (DeskError, OSError, ValueError) as exc:
            print(f"monster-wrangler: {exc}", file=sys.stderr)
            return 2
    try:
        if args.command == "run":
            task = (
                args.task
                if args.task is not None
                else args.task_file.read_text(encoding="utf-8")
            )
            acceptance = (
                args.acceptance
                if args.acceptance is not None
                else args.acceptance_file.read_text(encoding="utf-8")
            )
            if args.files is not None:
                files = args.files
            else:
                files_value = json.loads(args.files_file.read_text(encoding="utf-8"))
                if not isinstance(files_value, list) or not all(
                    isinstance(item, str) for item in files_value
                ):
                    raise ValueError("--files-file must contain a JSON array of strings")
                files = files_value
            task_id = args.task_id or "task-" + hashlib.sha256(task.encode()).hexdigest()[:12]
            manifest = args.backend_manifest or (args.repo / "pilot_backends.json")
            receipt = run_task(
                repo=args.repo,
                task_id=task_id,
                task=task,
                files=files,
                acceptance=acceptance,
                manifest=manifest,
                arm=args.arm,
                output_dir=args.output_dir,
            )
            print(json.dumps(receipt, indent=2, sort_keys=True))
            return 0 if receipt["state"] == "ACCEPTED" else 1
        if args.command == "intervention" and args.event == "start":
            print(start(args.log, args.task_id, args.arm, args.category, args.reference_id))
            return 0
        if args.command == "intervention" and args.event == "stop":
            stop(args.log, args.id)
            return 0
        if args.command == "verify-interventions":
            rows = validate_events(args.log)
            print(json.dumps({
                "ok": True,
                "events": len(rows),
                "head_sha256": rows[-1]["event_sha256"] if rows else None,
            }, sort_keys=True))
            return 0
        if args.command == "verify":
            errors = verify_run(args.run_dir)
            print(json.dumps({"ok": not errors, "errors": errors}, indent=2, sort_keys=True))
            return int(bool(errors))
        if args.command == "pilot" and args.pilot_command == "schedule":
            raw = json.loads(args.plan.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise PilotError("pilot plan must be a JSON object")
            schedule = derive_schedule(raw.get("tasks", []), raw.get("protocol_commit", ""))
            print(json.dumps(schedule, indent=2, sort_keys=True))
            return 0
        if args.command == "pilot" and args.pilot_command == "validate":
            raw = json.loads(args.plan.read_text(encoding="utf-8"))
            errors = validate_plan(raw)
            print(json.dumps({"ok": not errors, "errors": errors}, indent=2, sort_keys=True))
            return int(bool(errors))
        if args.command == "pilot" and args.pilot_command == "close":
            as_of = None
            if args.as_of:
                as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
                if as_of.tzinfo is None:
                    raise PilotError("--as-of must include a timezone")
            receipt = close_pilot(args.plan, args.evidence, as_of=as_of)
            output = canonical_json(receipt)
            if args.output:
                if args.output.exists():
                    raise PilotError("--output already exists; closeout receipts are immutable")
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_bytes(output)
            print(json.dumps(receipt, indent=2, sort_keys=True))
            return 0
    except (
        InterventionError,
        ManifestError,
        PilotError,
        RunError,
        OSError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        print(f"tier: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
