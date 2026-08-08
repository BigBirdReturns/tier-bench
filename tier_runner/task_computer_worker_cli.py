"""CLI for persistent Task Computer planner and critic seats."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .conditional_memory_hardware import query_nvidia
from .playwright_computer_common import PlaywrightComputerError, write_json
from .task_computer_worker import ExchangeWorker


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="tiertaskworker",
        description=(
            "Claim Task Computer planner or critic packets from a shared exchange and "
            "invoke one local model wrapper under an optional exact GPU UUID."
        ),
    )
    root.add_argument("--exchange-root", type=Path, required=True)
    root.add_argument("--role", choices=("planner", "critic"), required=True)
    root.add_argument("--seat-id", required=True)
    root.add_argument("--command", required=True)
    root.add_argument("--gpu-uuid-env")
    root.add_argument("--expected-name-contains")
    root.add_argument("--timeout-seconds", type=float, default=600.0)
    root.add_argument("--reclaim-after-seconds", type=float, default=3600.0)
    root.add_argument("--poll-seconds", type=float, default=1.0)
    root.add_argument("--once", action="store_true")
    return root


def _gpu_attestation(
    env_name: str | None,
    expected_name_contains: str | None,
) -> dict | None:
    if env_name is None:
        return None
    uuid_value = os.environ.get(env_name)
    if not uuid_value:
        raise PlaywrightComputerError(f"GPU UUID environment variable is unset: {env_name}")
    rows = query_nvidia()
    gpu = next((row for row in rows if row.get("uuid") == uuid_value), None)
    if gpu is None:
        raise PlaywrightComputerError(f"GPU UUID {uuid_value!r} is not present")
    if expected_name_contains and expected_name_contains.casefold() not in str(
        gpu.get("name", "")
    ).casefold():
        raise PlaywrightComputerError(
            f"GPU {uuid_value!r} expected a name containing {expected_name_contains!r}; "
            f"observed {gpu.get('name')!r}"
        )
    return {
        "resolved": True,
        "uuid_env": env_name,
        "expected_name_contains": expected_name_contains,
        "gpu": gpu,
    }


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.timeout_seconds <= 0:
            raise PlaywrightComputerError("timeout-seconds must be positive")
        if args.reclaim_after_seconds <= 0:
            raise PlaywrightComputerError("reclaim-after-seconds must be positive")
        if args.poll_seconds <= 0:
            raise PlaywrightComputerError("poll-seconds must be positive")
        worker = ExchangeWorker(
            exchange_root=args.exchange_root,
            role=args.role,
            command=args.command,
            seat_id=args.seat_id,
            gpu_attestation=_gpu_attestation(
                args.gpu_uuid_env, args.expected_name_contains
            ),
            timeout_seconds=args.timeout_seconds,
            reclaim_after_seconds=args.reclaim_after_seconds,
        )
        if args.once:
            result = worker.process_once()
            write_json(None, result)
            return 0 if result["ok"] else 1
        write_json(
            None,
            {
                "ok": True,
                "status": "watching",
                "exchange_root": str(args.exchange_root.resolve()),
                "role": args.role,
                "seat_id": args.seat_id,
            },
        )
        worker.run_loop(poll_seconds=args.poll_seconds)
        return 0
    except (PlaywrightComputerError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"tiertaskworker: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
