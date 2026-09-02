"""CLI for desktop coordination and <dual-3090-node> dual-3090 workers."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .conditional_memory_common import MemoryLabError, load_json, write_json
from .conditional_memory_exchange import (
    collect_flight,
    exchange_status,
    publish_flight,
    run_worker_node,
    run_worker_seat,
    validate_cluster,
    worker_loop,
)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="tiermemorycluster",
        description=(
            "Coordinate a desktop 4060 control node with an <dual-3090-node> dual-eGPU 3090 "
            "worker through immutable work packets and returned receipts."
        ),
    )
    commands = root.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate-cluster")
    validate.add_argument("--cluster", type=Path, required=True)

    publish = commands.add_parser("publish")
    publish.add_argument("--lab", type=Path, required=True)
    publish.add_argument("--profile", default="smoke")
    publish.add_argument("--cluster", type=Path, required=True)
    publish.add_argument("--exchange-root", type=Path)
    publish.add_argument("--flight-id", required=True)
    publish.add_argument("--force-cpu", action="store_true")

    status = commands.add_parser("status")
    status.add_argument("--flight-root", type=Path, required=True)

    seat = commands.add_parser("worker-seat")
    seat.add_argument("--flight-root", type=Path, required=True)
    seat.add_argument("--node", required=True)
    seat.add_argument("--seat", required=True)
    seat.add_argument("--work-root", type=Path, required=True)
    seat.add_argument("--force-cpu", action="store_true")
    seat.add_argument("--reclaim-stale", action="store_true")
    seat.add_argument("--max-wait-seconds", type=float, default=86400.0)

    node = commands.add_parser("worker-node")
    node.add_argument("--flight-root", type=Path, required=True)
    node.add_argument("--node", required=True)
    node.add_argument("--work-root", type=Path, required=True)
    node.add_argument("--force-cpu", action="store_true")
    node.add_argument("--reclaim-stale", action="store_true")
    node.add_argument("--max-wait-seconds", type=float, default=86400.0)

    watch = commands.add_parser("worker-loop")
    watch.add_argument("--exchange-root", type=Path)
    watch.add_argument("--node", required=True)
    watch.add_argument("--work-root", type=Path, required=True)
    watch.add_argument("--once", action="store_true")
    watch.add_argument("--poll-seconds", type=float, default=5.0)
    watch.add_argument("--force-cpu", action="store_true")
    watch.add_argument("--reclaim-stale", action="store_true")
    watch.add_argument("--max-wait-seconds", type=float, default=86400.0)

    collect = commands.add_parser("collect")
    collect.add_argument("--flight-root", type=Path, required=True)
    collect.add_argument("--coordinator-state", type=Path, required=True)
    collect.add_argument("--force-cpu", action="store_true")
    return root


def _exchange_root(value: Path | None, cluster: dict | None = None) -> Path:
    if value is not None:
        return value
    env_name = (
        cluster["exchange"]["root_env"] if cluster is not None else "TIER_EXCHANGE_ROOT"
    )
    raw = os.environ.get(env_name)
    if not raw:
        raise MemoryLabError(f"exchange root requires --exchange-root or {env_name}")
    return Path(raw)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "validate-cluster":
            cluster = validate_cluster(load_json(args.cluster))
            write_json(None, {"ok": True, "cluster": cluster})
            return 0
        if args.command == "publish":
            raw_cluster = load_json(args.cluster)
            cluster = validate_cluster(raw_cluster)
            result = publish_flight(
                raw_lab=load_json(args.lab),
                profile=args.profile,
                raw_cluster=raw_cluster,
                exchange_root=_exchange_root(args.exchange_root, cluster),
                flight_id=args.flight_id,
                force_cpu=args.force_cpu,
            )
            write_json(None, result)
            return 0
        if args.command == "status":
            result = exchange_status(args.flight_root)
            write_json(None, result)
            counts = result["counts"]
            return 0 if not counts["failed"] else 1
        if args.command == "worker-seat":
            result = run_worker_seat(
                root=args.flight_root,
                node_id=args.node,
                seat_id=args.seat,
                work_root=args.work_root,
                force_cpu=args.force_cpu,
                reclaim_stale=args.reclaim_stale,
                max_wait_seconds=args.max_wait_seconds,
            )
            write_json(None, result)
            return 0 if result["ok"] else 1
        if args.command == "worker-node":
            result = run_worker_node(
                root=args.flight_root,
                node_id=args.node,
                work_root=args.work_root,
                force_cpu=args.force_cpu,
                reclaim_stale=args.reclaim_stale,
                max_wait_seconds=args.max_wait_seconds,
            )
            write_json(None, result)
            return 0 if result["ok"] else 1
        if args.command == "worker-loop":
            result = worker_loop(
                exchange_root=_exchange_root(args.exchange_root),
                node_id=args.node,
                work_root=args.work_root,
                once=args.once,
                poll_seconds=args.poll_seconds,
                force_cpu=args.force_cpu,
                reclaim_stale=args.reclaim_stale,
                max_wait_seconds=args.max_wait_seconds,
            )
            write_json(None, result)
            return 0 if result["ok"] else 1
        if args.command == "collect":
            result = collect_flight(
                root=args.flight_root,
                coordinator_state=args.coordinator_state,
                force_cpu=args.force_cpu,
            )
            write_json(None, result)
            return 0 if result["ok"] else 1
    except (MemoryLabError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"tiermemorycluster: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
