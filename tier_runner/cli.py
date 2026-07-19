from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from .core import RunError, run_task, verify_run
from .events import InterventionError, start, stop, validate_events
from .manifest import ManifestError
from .pilot import PilotError, canonical_json, close_pilot, derive_schedule, validate_plan


RUN_ENVELOPE_SCHEMA = "tier-bench/tier-run-envelope@1"
RUN_ENVELOPE_FIELDS = {
    "schema",
    "repo",
    "task_id",
    "task",
    "files",
    "acceptance",
    "manifest",
    "arm",
    "output_dir",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tier", description="Fail-closed daily task runner")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run one sealed backend call in a disposable worktree")
    run.add_argument(
        "--envelope",
        type=Path,
        help="read the exact run inputs from a tier-bench/tier-run-envelope@1 JSON file",
    )
    run.add_argument("--repo", type=Path)
    run.add_argument("--task-id", help="stable id; defaults to a hash of --task")
    run.add_argument("--task")
    run.add_argument(
        "--files",
        action="append",
        help="allowed file or directory scope; repeat or comma-separate",
    )
    run.add_argument("--acceptance", help="trusted operator-supplied shell command")
    run.add_argument("--backend-manifest", type=Path, help="defaults to <repo>/pilot_backends.json")
    run.add_argument("--arm", choices=["arm_a", "arm_b", "arm_c"])
    run.add_argument("--output-dir", type=Path)

    desk = sub.add_parser(
        "desk", help="open Monster Wrangler, the persistent local agent control desk"
    )
    desk.add_argument("--repo", type=Path, required=True)
    desk.add_argument("--host", default="127.0.0.1")
    desk.add_argument("--port", type=int, default=8765)
    desk.add_argument("--state-dir", type=Path)
    desk.add_argument("--no-open", action="store_true")
    desk.add_argument("--daemon", action="store_true")
    desk.add_argument("--stop", action="store_true")
    desk.add_argument("--status", action="store_true")
    desk.add_argument("--unsafe-network", action="store_true")
    desk.add_argument("--max-workers", type=int, choices=range(1, 5))
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


def _envelope(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RunError("run envelope must be a JSON object")
    missing = RUN_ENVELOPE_FIELDS - set(raw)
    unknown = set(raw) - RUN_ENVELOPE_FIELDS
    if missing or unknown:
        raise RunError(
            f"run envelope fields mismatch; missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    if raw.get("schema") != RUN_ENVELOPE_SCHEMA:
        raise RunError(f"run envelope schema must be {RUN_ENVELOPE_SCHEMA}")
    for key in ("repo", "task_id", "task", "acceptance", "manifest", "arm", "output_dir"):
        if not isinstance(raw.get(key), str) or not raw[key]:
            raise RunError(f"run envelope {key} must be a non-empty string")
    files = raw.get("files")
    if not isinstance(files, list) or not files or not all(isinstance(item, str) for item in files):
        raise RunError("run envelope files must be a non-empty string list")
    if raw["arm"] not in {"arm_a", "arm_b", "arm_c"}:
        raise RunError("run envelope arm is invalid")
    return raw


def _run_inputs(args: argparse.Namespace) -> dict[str, Any]:
    direct = {
        "repo": args.repo,
        "task_id": args.task_id,
        "task": args.task,
        "files": args.files,
        "acceptance": args.acceptance,
        "backend_manifest": args.backend_manifest,
        "arm": args.arm,
        "output_dir": args.output_dir,
    }
    if args.envelope:
        if any(value is not None for value in direct.values()):
            raise RunError("--envelope cannot be combined with direct run arguments")
        raw = _envelope(args.envelope)
        repo = Path(raw["repo"])
        manifest = Path(raw["manifest"])
        if not manifest.is_absolute():
            manifest = repo / manifest
        return {
            "repo": repo,
            "task_id": raw["task_id"],
            "task": raw["task"],
            "files": raw["files"],
            "acceptance": raw["acceptance"],
            "manifest": manifest,
            "arm": raw["arm"],
            "output_dir": Path(raw["output_dir"]),
        }
    missing = [
        flag
        for flag, value in (
            ("--repo", args.repo),
            ("--task", args.task),
            ("--files", args.files),
            ("--acceptance", args.acceptance),
        )
        if value is None
    ]
    if missing:
        raise RunError(f"direct run is missing required arguments: {', '.join(missing)}")
    task_id = args.task_id or "task-" + hashlib.sha256(args.task.encode()).hexdigest()[:12]
    manifest = args.backend_manifest or (args.repo / "pilot_backends.json")
    return {
        "repo": args.repo,
        "task_id": task_id,
        "task": args.task,
        "files": args.files,
        "acceptance": args.acceptance,
        "manifest": manifest,
        "arm": args.arm or "arm_b",
        "output_dir": args.output_dir,
    }


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
            receipt = run_task(**_run_inputs(args))
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
            print(
                json.dumps(
                    {
                        "ok": True,
                        "events": len(rows),
                        "head_sha256": rows[-1]["event_sha256"] if rows else None,
                    },
                    sort_keys=True,
                )
            )
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
