from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from .core import RunError, run_task, verify_run
from .events import InterventionError, start, stop, validate_events
from .manifest import ManifestError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tier", description="Fail-closed daily task runner")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run one sealed backend call in a disposable worktree")
    run.add_argument("--repo", type=Path, required=True)
    run.add_argument("--task-id", help="stable id; defaults to a hash of --task")
    run.add_argument("--task", required=True)
    run.add_argument("--files", action="append", required=True,
                     help="allowed file or directory scope; repeat or comma-separate")
    run.add_argument("--acceptance", required=True, help="trusted operator-supplied shell command")
    run.add_argument("--backend-manifest", type=Path,
                     help="defaults to <repo>/pilot_backends.json")
    run.add_argument("--arm", choices=["arm_a", "arm_b", "arm_c"], default="arm_b")
    run.add_argument("--output-dir", type=Path)

    intervention = sub.add_parser("intervention", help="append operator-time start/stop events")
    intervention_sub = intervention.add_subparsers(dest="event", required=True)
    begin = intervention_sub.add_parser("start")
    begin.add_argument("--log", type=Path, required=True)
    begin.add_argument("--task-id", required=True)
    begin.add_argument("--arm", choices=["arm_a", "arm_b", "arm_c"], required=True)
    begin.add_argument("--category", required=True)
    end = intervention_sub.add_parser("stop")
    end.add_argument("--log", type=Path, required=True)
    end.add_argument("--id", required=True)

    verify = sub.add_parser(
        "verify-interventions", help="validate append-only intervention pairing"
    )
    verify.add_argument("--log", type=Path, required=True)
    verify_run_parser = sub.add_parser("verify", help="verify a run's hashes and bindings")
    verify_run_parser.add_argument("--run-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "run":
            task_id = args.task_id or "task-" + hashlib.sha256(args.task.encode()).hexdigest()[:12]
            manifest = args.backend_manifest or (args.repo / "pilot_backends.json")
            receipt = run_task(
                repo=args.repo,
                task_id=task_id,
                task=args.task,
                files=args.files,
                acceptance=args.acceptance,
                manifest=manifest,
                arm=args.arm,
                output_dir=args.output_dir,
            )
            print(json.dumps(receipt, indent=2, sort_keys=True))
            return 0 if receipt["state"] == "ACCEPTED" else 1
        if args.command == "intervention" and args.event == "start":
            print(start(args.log, args.task_id, args.arm, args.category))
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
    except (InterventionError, ManifestError, RunError, OSError) as exc:
        print(f"tier: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
