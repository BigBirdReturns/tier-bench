from __future__ import annotations

import argparse
import ctypes
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
    if os.name == "nt":
        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
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


def _record_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True) + "\n").encode("utf-8")


def claim_record(path: Path, value: dict[str, Any]) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        existing = read_record(path)
        if existing is None:
            time.sleep(0.2)
            existing = read_record(path)
        if existing is None:
            raise DeskError(
                "desk control record exists but is unreadable; refusing takeover"
            ) from exc
        pid = int(existing.get("pid", 0)) if existing else 0
        if pid_alive(pid):
            raise DeskError(f"desk state is already leased by live pid {pid}") from exc
        path.unlink(missing_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as retry_exc:
            raise DeskError("desk state was claimed concurrently") from retry_exc
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(_record_bytes(value))


def replace_record(path: Path, value: dict[str, Any]) -> None:
    current = read_record(path)
    if not current or current.get("instance_id") != value.get("instance_id"):
        raise DeskError("desk control record ownership changed during startup")
    temporary = path.with_name(path.name + f".{value['instance_id']}.tmp")
    temporary.write_bytes(_record_bytes(value))
    if os.name != "nt":
        temporary.chmod(0o600)
    os.replace(temporary, path)


def log_tail(path: Path, limit: int = 4000) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return data[-limit:].decode("utf-8", errors="replace").strip()


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
    if existing and pid_alive(existing_pid):
        if health(existing):
            raise DeskError(f"desk already runs as pid {existing_pid}")
        raise DeskError(
            f"desk state is held by live but unverified pid {existing_pid}; refusing takeover"
        )
    if existing:
        pid_path.unlink(missing_ok=True)

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
        package_root = str(Path(__file__).resolve().parents[1])
        inherited_pythonpath = child_env.get("PYTHONPATH")
        child_env["PYTHONPATH"] = (
            package_root
            if not inherited_pythonpath
            else package_root + os.pathsep + inherited_pythonpath
        )
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
        deadline = time.time() + 10
        record = None
        while time.time() < deadline:
            if process.poll() is not None:
                detail = log_tail(log_path)
                candidate = read_record(pid_path)
                if candidate and candidate.get("instance_id") == instance_id:
                    pid_path.unlink(missing_ok=True)
                raise DeskError(
                    f"desk process exited during startup with rc={process.returncode}"
                    + (f": {detail}" if detail else "")
                )
            candidate = read_record(pid_path)
            if (
                candidate
                and candidate.get("pid") == process.pid
                and candidate.get("instance_id") == instance_id
                and health(candidate)
            ):
                record = candidate
                break
            time.sleep(0.1)
        if record is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            candidate = read_record(pid_path)
            if candidate and candidate.get("instance_id") == instance_id:
                pid_path.unlink(missing_ok=True)
            detail = log_tail(log_path)
            raise DeskError(
                "desk did not produce a verified health receipt during startup"
                + (f": {detail}" if detail else "")
            )
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

    provisional = {
        "pid": os.getpid(),
        "repo": str(repo),
        "started_at": now(),
        "url": None,
        "instance_id": instance_id,
        "token": token,
    }
    claim_record(pid_path, provisional)
    app: DeskApplication | None = None
    server: DeskServer | None = None
    app_started = False
    try:
        app = DeskApplication(repo, state_dir, instance_id=instance_id, token=token)
        if args.max_workers:
            app.store.update_settings({"max_workers": args.max_workers})
        server = DeskServer((args.host, args.port), app)
        host, port = server.server_address[:2]
        url_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
        rendered_host = f"[{url_host}]" if ":" in str(url_host) else url_host
        url = f"http://{rendered_host}:{port}/"
        record = {**provisional, "url": url}
        replace_record(pid_path, record)
        shutting_down = threading.Event()

        def stop_server(signum: int, frame: Any) -> None:  # noqa: ARG001
            if not shutting_down.is_set():
                shutting_down.set()
                threading.Thread(target=server.shutdown, daemon=True).start()

        signal.signal(signal.SIGTERM, stop_server)
        signal.signal(signal.SIGINT, stop_server)
        app.start()
        app_started = True
        print(f"Monster Wrangler is running at {url}")
        print(f"State: {state_dir}")
        if not args.no_open:
            threading.Timer(0.4, lambda: webbrowser.open(url)).start()
        server.serve_forever(0.4)
    finally:
        if server is not None:
            server.server_close()
        if app is not None and app_started:
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
