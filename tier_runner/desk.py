from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import threading
import time
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen
import webbrowser

from .desk_common import DeskError, now, resolve_repo, resolve_state_dir
from .desk_http import DeskApplication, DeskServer
from .desk_runtime import DeskScheduler, ExecutionResult, TierRunExecutor
from .desk_store import DeskStore

__all__ = [
    "DeskApplication",
    "DeskError",
    "DeskScheduler",
    "DeskServer",
    "DeskStore",
    "ExecutionResult",
    "TierRunExecutor",
    "main",
]


def loopback(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_record(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def write_record(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)


def health(record: dict[str, Any]) -> dict[str, Any] | None:
    url = record.get("url")
    instance_id = record.get("instance_id")
    if not isinstance(url, str) or not isinstance(instance_id, str):
        return None
    try:
        with urlopen(url.rstrip("/") + "/healthz", timeout=1.5) as response:
            value = json.loads(response.read())
    except (OSError, URLError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(value, dict) or value.get("instance_id") != instance_id:
        return None
    return value


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--unsafe-network", action="store_true")
    parser.add_argument("--max-workers", type=int, choices=range(1, 5))
    parser.add_argument("--foreground-child", action="store_true", help=argparse.SUPPRESS)


def daemon_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "tier_runner.desk",
        "--repo",
        str(args.repo),
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--no-open",
        "--foreground-child",
    ]
    if args.state_dir:
        command += ["--state-dir", str(args.state_dir)]
    if args.unsafe_network:
        command.append("--unsafe-network")
    if args.max_workers:
        command += ["--max-workers", str(args.max_workers)]
    return command


def stop_remote(record: dict[str, Any]) -> None:
    url = record.get("url")
    token = record.get("token")
    if not isinstance(url, str) or not isinstance(token, str):
        raise DeskError("desk control record is incomplete")
    request = Request(
        url.rstrip("/") + "/api/control/shutdown",
        data=b"{}",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Tier-Desk-Token": token,
        },
    )
    try:
        with urlopen(request, timeout=3) as response:
            value = json.loads(response.read())
    except (OSError, URLError, json.JSONDecodeError) as exc:
        raise DeskError(f"verified desk refused shutdown: {exc}") from exc
    if not isinstance(value, dict) or value.get("shutting_down") is not True:
        raise DeskError("desk returned an invalid shutdown acknowledgement")


def run_cli(args: argparse.Namespace) -> int:
    repo = resolve_repo(args.repo)
    state_dir = resolve_state_dir(repo, args.state_dir)
    pid_path = state_dir / "desk.pid.json"
    log_path = state_dir / "server.log"
    if not 0 <= args.port <= 65535:
        raise DeskError("port must be between 0 and 65535")
    if args.daemon and args.port == 0:
        raise DeskError("daemon mode requires a fixed nonzero port")

    if args.status:
        record = read_record(pid_path)
        pid = int(record.get("pid", 0)) if record else 0
        verified = health(record) if record and pid_alive(pid) else None
        print(
            json.dumps(
                {
                    "running": bool(verified),
                    "pid": pid or None,
                    "url": record.get("url") if record else None,
                    "state_dir": str(state_dir),
                }
            )
        )
        return 0 if verified else 1
    if args.stop:
        record = read_record(pid_path)
        pid = int(record.get("pid", 0)) if record else 0
        if not record or not pid_alive(pid):
            raise DeskError("no running desk found")
        if health(record) is None:
            raise DeskError(
                "PID exists but the desk instance could not be verified; refusing to signal it"
            )
        stop_remote(record)
        deadline = time.time() + 12
        while time.time() < deadline and pid_alive(pid):
            time.sleep(0.1)
        if pid_alive(pid):
            raise DeskError(f"verified desk process {pid} did not stop")
        if read_record(pid_path) == record:
            pid_path.unlink(missing_ok=True)
        print(json.dumps({"stopped": True, "pid": pid}))
        return 0
    if not loopback(args.host) and not args.unsafe_network:
        raise DeskError("non-loopback binding requires --unsafe-network")

    existing = read_record(pid_path)
    existing_pid = int(existing.get("pid", 0)) if existing else 0
    if existing and pid_alive(existing_pid) and health(existing):
        raise DeskError(f"desk already runs as pid {existing_pid}")

    instance_id = os.environ.get("TIER_DESK_INSTANCE_ID") or secrets.token_hex(16)
    token = os.environ.get("TIER_DESK_CONTROL_TOKEN") or secrets.token_urlsafe(32)
    if args.daemon and not args.foreground_child:
        kwargs: dict[str, Any] = {"start_new_session": os.name != "nt"}
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        child_env = dict(os.environ)
        child_env["TIER_DESK_INSTANCE_ID"] = instance_id
        child_env["TIER_DESK_CONTROL_TOKEN"] = token
        with log_path.open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                daemon_command(args),
                cwd=repo,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                env=child_env,
                **kwargs,
            )
        record = {
            "pid": process.pid,
            "repo": str(repo),
            "started_at": now(),
            "url": f"http://{args.host}:{args.port}/",
            "instance_id": instance_id,
            "token": token,
        }
        write_record(pid_path, record)
        print(
            json.dumps(
                {
                    "started": True,
                    "pid": process.pid,
                    "url": record["url"],
                    "log": str(log_path),
                }
            )
        )
        return 0

    app = DeskApplication(repo, state_dir, instance_id=instance_id, token=token)
    if args.max_workers:
        app.store.update_settings({"max_workers": args.max_workers})
    server = DeskServer((args.host, args.port), app)
    host, port = server.server_address[:2]
    url_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{url_host}:{port}/"
    record = {
        "pid": os.getpid(),
        "repo": str(repo),
        "started_at": now(),
        "url": url,
        "instance_id": instance_id,
        "token": token,
    }
    write_record(pid_path, record)
    shutting_down = threading.Event()

    def stop_server(signum: int, frame: Any) -> None:  # noqa: ARG001
        if not shutting_down.is_set():
            shutting_down.set()
            threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop_server)
    signal.signal(signal.SIGINT, stop_server)
    app.start()
    print(f"Monster Wrangler is running at {url}")
    print(f"State: {state_dir}")
    if not args.no_open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(0.4)
    finally:
        server.server_close()
        app.stop()
        current = read_record(pid_path)
        if current and current.get("instance_id") == instance_id:
            pid_path.unlink(missing_ok=True)
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="tierdesk", description="Monster Wrangler: controlled unattended agent work"
    )
    add_arguments(result)
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        return run_cli(parser().parse_args(argv))
    except (DeskError, OSError, ValueError) as exc:
        print(f"monster-wrangler: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
