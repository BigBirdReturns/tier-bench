from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

from .desk_common import hidden_process_kwargs


class WorkerError(RuntimeError):
    pass


def _child_kwargs() -> dict[str, object]:
    if os.name == "nt":
        return hidden_process_kwargs(new_process_group=True)
    return {"start_new_session": True}


def _soft_signal(process: subprocess.Popen[object]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid, signal.SIGINT)
    except (OSError, ProcessLookupError):
        pass


def _hard_kill(process: subprocess.Popen[object]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
            **hidden_process_kwargs(),
        )
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass


def terminate_tree(process: subprocess.Popen[object], grace: float = 8.0) -> None:
    _soft_signal(process)
    try:
        process.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        _hard_kill(process)
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()


def heartbeat_valid(path: Path, instance_id: str, timeout: float) -> bool:
    try:
        age = max(0.0, time.time() - path.stat().st_mtime)
        owner = path.read_text(encoding="utf-8").split(maxsplit=1)[0]
    except OSError:
        return False
    return age <= timeout and owner == instance_id


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Supervise one Monster Wrangler tier run")
    result.add_argument("--envelope", type=Path, required=True)
    result.add_argument("--heartbeat", type=Path, required=True)
    result.add_argument("--heartbeat-instance", required=True)
    result.add_argument("--heartbeat-timeout", type=float, default=30.0)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.heartbeat_timeout < 5:
        raise WorkerError("heartbeat timeout must be at least five seconds")
    if not heartbeat_valid(args.heartbeat, args.heartbeat_instance, args.heartbeat_timeout):
        raise WorkerError("desk heartbeat is absent, stale, or owned by another instance")

    stopping = threading.Event()

    def request_stop(signum: int, frame: object) -> None:  # noqa: ARG001
        stopping.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    if os.name == "nt" and hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, request_stop)

    command = [
        sys.executable,
        "-m",
        "tier_runner.cli",
        "run",
        "--envelope",
        str(args.envelope),
    ]
    process = subprocess.Popen(command, **_child_kwargs())
    reason = ""
    while process.poll() is None:
        if stopping.wait(0.5):
            reason = "worker received a stop request"
            break
        if not heartbeat_valid(args.heartbeat, args.heartbeat_instance, args.heartbeat_timeout):
            reason = "desk heartbeat expired or changed ownership"
            break
    if reason:
        print(f"monster-wrangler worker: {reason}; terminating tier run", file=sys.stderr)
        terminate_tree(process)
        return 75
    return int(process.returncode or 0)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (WorkerError, OSError, ValueError) as exc:
        print(f"monster-wrangler worker: {exc}", file=sys.stderr)
        raise SystemExit(2)
