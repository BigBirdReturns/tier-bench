"""CLI surface for Frontier Residue Refinery campaigns."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .desk_common import DeskError, resolve_repo, resolve_state_dir
from .desk_store import DeskStore


def _add_commands(commands: argparse._SubParsersAction) -> None:
    def common(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--repo", type=Path, required=True)
        parser.add_argument("--state-dir", type=Path)

    create = commands.add_parser("create", help="create a campaign from a JSON plan")
    common(create)
    create.add_argument("--plan", type=Path, required=True)
    create.add_argument(
        "--start",
        action="store_true",
        help="activate immediately even when the plan says queue_now=false",
    )

    list_parser = commands.add_parser("list", help="list campaigns")
    common(list_parser)
    list_parser.add_argument("--full", action="store_true")

    show = commands.add_parser("show", help="show one campaign")
    common(show)
    show.add_argument("--id", required=True)

    start = commands.add_parser("start", help="start a draft campaign")
    common(start)
    start.add_argument("--id", required=True)

    cancel = commands.add_parser("cancel", help="cancel a campaign with no active running task")
    common(cancel)
    cancel.add_argument("--id", required=True)

    candidates = commands.add_parser("candidates", help="list or inspect residue candidates")
    common(candidates)
    candidates.add_argument("--id")


def add_arguments(subparsers: argparse._SubParsersAction) -> None:
    residue = subparsers.add_parser(
        "residue",
        help="sequence local-first or survey campaigns and preserve frontier residue",
    )
    commands = residue.add_subparsers(dest="residue_command", required=True)
    _add_commands(commands)


def _store(args: argparse.Namespace) -> DeskStore:
    repo = resolve_repo(args.repo)
    state_dir = resolve_state_dir(repo, args.state_dir)
    return DeskStore(state_dir / "desk.sqlite3", repo)


def _print(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def run(args: argparse.Namespace) -> int:
    store = _store(args)
    command = args.residue_command
    if command == "create":
        raw = json.loads(args.plan.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise DeskError("residue campaign plan must be a JSON object")
        if args.start:
            raw = {**raw, "queue_now": True}
        _print(store.create_campaign(raw))
        return 0
    if command == "list":
        _print(store.list_campaigns(full=args.full))
        return 0
    if command == "show":
        campaign = store.get_campaign(args.id)
        if campaign is None:
            raise DeskError(f"unknown campaign: {args.id}")
        _print(campaign)
        return 0
    if command == "start":
        _print(store.start_campaign(args.id))
        return 0
    if command == "cancel":
        task_id = store.campaign_active_task(args.id)
        if task_id:
            task = store.get_task(task_id, False)
            if task and task["state"] == "RUNNING":
                raise DeskError(
                    "campaign has a running task; stop or cancel that task through "
                    "the live Desk first"
                )
            if task and task["state"] in {"DRAFT", "QUEUED"}:
                store.transition(task_id, "cancel")
        _print(store.cancel_campaign(args.id))
        return 0
    if command == "candidates":
        if args.id:
            candidate = store.get_residue_candidate(args.id)
            if candidate is None:
                raise DeskError(f"unknown residue candidate: {args.id}")
            _print(candidate)
        else:
            _print(store.list_residue_candidates())
        return 0
    raise DeskError(f"unknown residue command: {command}")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="tierresidue",
        description="Run local-first and frontier-survey campaigns through Monster Wrangler",
    )
    commands = root.add_subparsers(dest="residue_command", required=True)
    _add_commands(commands)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return run(args)
    except (DeskError, OSError, ValueError, json.JSONDecodeError) as exc:
        import sys

        print(f"tierresidue: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
