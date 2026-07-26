from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
from typing import Any
from urllib.parse import parse_qs, urlparse, urlsplit

from .desk_common import MAX_BODY, MAX_LOG, SCHEMA, DeskError, committed_blob, now
from .desk_runtime import DeskScheduler
from .desk_store import DeskStore
from .desk_ui import HTML


class DeskApplication:
    def __init__(
        self,
        repo: Path,
        state_dir: Path,
        executor: Any | None = None,
        *,
        instance_id: str | None = None,
        token: str | None = None,
    ):
        self.repo = repo
        self.state_dir = state_dir
        self.instance_id = instance_id or secrets.token_hex(16)
        self.token = token or secrets.token_urlsafe(32)
        self.store = DeskStore(state_dir / "desk.sqlite3", repo)
        self.scheduler = DeskScheduler(
            self.store,
            repo,
            state_dir,
            executor,
            instance_id=self.instance_id,
        )
        self.started_at = now()
        self.manifest_blob_id = ""
        self.manifest_cache: dict[str, Any] | None = None

    def start(self) -> None:
        self.scheduler.start()

    def stop(self) -> None:
        self.scheduler.stop()

    def cartridges(self) -> dict[str, Any] | None:
        relative = "pilot_backends.json"
        path = self.repo / relative
        identity = subprocess.run(
            ["git", "rev-parse", f"HEAD:{relative}"],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )
        if identity.returncode:
            return None
        blob_id = identity.stdout.strip()
        if blob_id == self.manifest_blob_id:
            return self.manifest_cache
        try:
            raw = json.loads(committed_blob(self.repo, relative, "backend manifest"))
        except (DeskError, json.JSONDecodeError):
            return None
        arms = raw.get("arms") if isinstance(raw, dict) else {}
        summary = {"path": str(path), "schema": raw.get("schema"), "arms": {}}
        if isinstance(arms, dict):
            for name, value in arms.items():
                if isinstance(value, dict):
                    summary["arms"][name] = {
                        key: value.get(key)
                        for key in (
                            "model_id",
                            "effort",
                            "surface",
                            "cost_basis",
                            "account",
                            "tier",
                        )
                    }
        self.manifest_blob_id = blob_id
        self.manifest_cache = summary
        return summary

    def snapshot(self) -> dict[str, Any]:
        data = self.store.snapshot(self.cartridges(), self.scheduler.active_ids())
        data["started_at"] = self.started_at
        return data


class DeskServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], app: DeskApplication):
        super().__init__(address, DeskHandler)
        self.app = app
        bound_host = str(self.server_address[0])
        self.allowed_hosts = {"127.0.0.1", "localhost", "::1", bound_host, address[0]}


class DeskHandler(BaseHTTPRequestHandler):
    server: DeskServer
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("monster-wrangler: " + fmt % args + "\n")

    def headers_secure(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'",
        )

    def send_bytes(
        self,
        data: bytes,
        content_type: str,
        status: HTTPStatus = HTTPStatus.OK,
        disposition: str | None = None,
    ) -> None:
        self.send_response(status.value)
        self.headers_secure()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if disposition:
            self.send_header("Content-Disposition", disposition)
        self.end_headers()
        self.wfile.write(data)

    def json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_bytes(
            (json.dumps(value, sort_keys=True, ensure_ascii=False) + "\n").encode(),
            "application/json; charset=utf-8",
            status,
        )

    def error(self, status: HTTPStatus, message: str) -> None:
        self.json({"ok": False, "error": message}, status)

    def require_token(self) -> None:
        supplied = self.headers.get("X-Tier-Desk-Token", "")
        if not secrets.compare_digest(supplied, self.server.app.token):
            raise DeskError("missing or invalid desk token")

    def require_host(self) -> None:
        raw = self.headers.get("Host", "")
        try:
            hostname = urlsplit("//" + raw).hostname
        except ValueError as exc:
            raise DeskError("invalid Host header") from exc
        if hostname not in self.server.allowed_hosts:
            raise DeskError("Host header is not allowed for this local desk")

    def body(self) -> dict[str, Any]:
        if "application/json" not in self.headers.get("Content-Type", ""):
            raise DeskError("POST requests must use application/json")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise DeskError("invalid Content-Length") from exc
        if not 0 <= length <= MAX_BODY:
            raise DeskError("request body is too large")
        try:
            value = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as exc:
            raise DeskError(f"invalid JSON body: {exc}") from exc
        if not isinstance(value, dict):
            raise DeskError("request body must be a JSON object")
        return value

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        try:
            self.require_host()
            if parsed.path == "/":
                page = HTML.replace("__TIER_DESK_TOKEN__", self.server.app.token)
                self.send_bytes(page.encode(), "text/html; charset=utf-8")
                return
            if parsed.path == "/healthz":
                self.json(
                    {
                        "ok": True,
                        "schema": SCHEMA,
                        "instance_id": self.server.app.instance_id,
                        "time": now(),
                    }
                )
                return
            if parsed.path == "/api/state":
                self.json({"ok": True, "state": self.server.app.snapshot()})
                return
            if len(parts) == 3 and parts[:2] == ["api", "tasks"]:
                task = self.server.app.store.get_task(parts[2])
                if task is None:
                    self.error(HTTPStatus.NOT_FOUND, "task not found")
                else:
                    self.json({"ok": True, "task": task})
                return
            if len(parts) == 4 and parts[:2] == ["api", "runs"]:
                run = self.server.app.store.get_run(parts[2])
                if run is None:
                    self.error(HTTPStatus.NOT_FOUND, "run not found")
                    return
                if parts[3] == "log":
                    queries = parse_qs(parsed.query)
                    tail = max(0, min(int(queries.get("tail", [MAX_LOG])[0]), MAX_LOG))
                    path = Path(run["log_path"])
                    if not path.is_file():
                        self.send_bytes(b"", "text/plain; charset=utf-8")
                        return
                    with path.open("rb") as handle:
                        handle.seek(0, os.SEEK_END)
                        size = handle.tell()
                        handle.seek(max(0, size - tail))
                        data = handle.read()
                    self.send_bytes(data, "text/plain; charset=utf-8")
                    return
                if parts[3] == "receipt":
                    if run.get("receipt") is None:
                        self.error(HTTPStatus.NOT_FOUND, "receipt not available")
                    else:
                        self.json({"ok": True, "receipt": run["receipt"]})
                    return
                if parts[3] == "patch":
                    patch = Path(run["output_dir"]) / "change.patch"
                    if not patch.is_file():
                        self.error(HTTPStatus.NOT_FOUND, "patch not available")
                    else:
                        self.send_bytes(
                            patch.read_bytes(),
                            "text/x-diff; charset=utf-8",
                            disposition=f'attachment; filename="{parts[2]}.patch"',
                        )
                    return
            self.error(HTTPStatus.NOT_FOUND, "not found")
        except (DeskError, OSError, ValueError) as exc:
            self.error(HTTPStatus.BAD_REQUEST, str(exc))

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        parts = [part for part in path.split("/") if part]
        try:
            self.require_host()
            self.require_token()
            body = self.body()
            if path == "/api/tasks":
                task = self.server.app.store.create_task(body)
                self.server.app.scheduler.wake()
                self.json({"ok": True, "task": task}, HTTPStatus.CREATED)
                return
            if len(parts) == 4 and parts[:2] == ["api", "tasks"]:
                task_id, action = parts[2], parts[3]
                if action == "cancel":
                    self.server.app.scheduler.cancel_task(task_id)
                    task = self.server.app.store.get_task(task_id)
                elif action in {"arm", "hold", "retry"}:
                    task = self.server.app.store.transition(task_id, action)
                    self.server.app.scheduler.wake()
                else:
                    self.error(HTTPStatus.NOT_FOUND, "unknown task action")
                    return
                self.json({"ok": True, "task": task})
                return
            if path == "/api/settings":
                settings = self.server.app.store.update_settings(body)
                self.server.app.scheduler.wake()
                self.json({"ok": True, "settings": settings})
                return
            if path == "/api/control/pause":
                self.server.app.store.pause(str(body.get("reason", "operator paused scheduling")))
                self.json({"ok": True, "settings": self.server.app.store.settings()})
                return
            if path == "/api/control/resume":
                self.server.app.store.resume()
                self.server.app.scheduler.wake()
                self.json({"ok": True, "settings": self.server.app.store.settings()})
                return
            if path == "/api/control/emergency-stop":
                self.server.app.scheduler.emergency_stop()
                self.json({"ok": True, "settings": self.server.app.store.settings()})
                return
            if path == "/api/control/shutdown":
                self.json({"ok": True, "shutting_down": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            self.error(HTTPStatus.NOT_FOUND, "not found")
        except DeskError as exc:
            status = HTTPStatus.FORBIDDEN if "token" in str(exc) else HTTPStatus.BAD_REQUEST
            self.error(status, str(exc))
        except (OSError, ValueError) as exc:
            self.error(HTTPStatus.BAD_REQUEST, str(exc))
