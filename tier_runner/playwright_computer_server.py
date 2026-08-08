"""Authenticated HTTP and event-stream control plane for a Playwright computer."""
from __future__ import annotations

import asyncio
from concurrent.futures import Future
import hmac
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

from .playwright_computer_common import (
    PlaywrightComputerError,
    atomic_json,
    hash_bytes,
    hash_json,
    now_utc,
    safe_relative_path,
)
from .playwright_computer_runtime import PlaywrightComputer

MAX_BODY_BYTES = 8 * 1024 * 1024


class ComputerLoop:
    """Own the Playwright event loop on one dedicated thread."""

    def __init__(self, computer: PlaywrightComputer):
        self.computer = computer
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self._run,
            name=f"playwright-computer-{computer.config['id']}",
            daemon=True,
        )
        self.ready = threading.Event()
        self.thread.start()
        if not self.ready.wait(timeout=10):
            raise PlaywrightComputerError("browser event loop did not start")

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.ready.set()
        self.loop.run_forever()
        pending = asyncio.all_tasks(self.loop)
        for task in pending:
            task.cancel()
        if pending:
            self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self.loop.close()

    def call(self, coroutine: Any, *, timeout: float = 120.0) -> Any:
        future: Future[Any] = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        try:
            return future.result(timeout=timeout)
        except TimeoutError as exc:
            future.cancel()
            raise PlaywrightComputerError("browser operation timed out") from exc

    def start(self) -> dict[str, Any]:
        return self.call(self.computer.start(), timeout=180.0)

    def close(self) -> dict[str, Any]:
        result = self.call(self.computer.close(), timeout=120.0)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=15)
        return result


class BrowserComputerServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        bridge: ComputerLoop,
        *,
        control_token: str,
    ):
        super().__init__(address, BrowserComputerHandler)
        self.bridge = bridge
        self.control_token = control_token
        self.shutdown_requested = threading.Event()


class BrowserComputerHandler(BaseHTTPRequestHandler):
    server: BrowserComputerServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        self.server.bridge.computer.ledger.append(
            "server.http",
            detail={"client": self.client_address[0], "message": format % args},
        )

    def _json(self, status: int, value: Any) -> None:
        data = json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _html(self, value: str) -> None:
        data = value.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self) -> bool:
        supplied = self.headers.get("X-Tier-Browser-Token", "")
        return hmac.compare_digest(supplied, self.server.control_token)

    def _require_auth(self) -> bool:
        if self._authorized():
            return True
        self._json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "invalid control token"})
        return False

    def _body(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or "0")
        except ValueError as exc:
            raise PlaywrightComputerError("invalid Content-Length") from exc
        if length < 0 or length > MAX_BODY_BYTES:
            raise PlaywrightComputerError("request body exceeds the server limit")
        data = self.rfile.read(length) if length else b"{}"
        try:
            value = json.loads(data)
        except json.JSONDecodeError as exc:
            raise PlaywrightComputerError(f"request body is invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise PlaywrightComputerError("request body must be an object")
        return value

    def _error(self, exc: Exception) -> None:
        status = (
            HTTPStatus.BAD_REQUEST
            if isinstance(exc, (PlaywrightComputerError, ValueError))
            else HTTPStatus.INTERNAL_SERVER_ERROR
        )
        self.server.bridge.computer.ledger.append(
            "server.request.failed",
            detail={"path": self.path, "error": f"{type(exc).__name__}: {exc}"[:4000]},
        )
        self._json(status, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                self._html(_dashboard_html())
                return
            if parsed.path == "/healthz":
                health = self.server.bridge.call(self.server.bridge.computer.health(), timeout=10)
                self._json(
                    HTTPStatus.OK if health["ok"] else HTTPStatus.SERVICE_UNAVAILABLE,
                    health,
                )
                return
            if not self._require_auth():
                return
            if parsed.path == "/state":
                state = self.server.bridge.computer.current_state
                if state is None:
                    state = self.server.bridge.call(self.server.bridge.computer.observe())
                self._json(HTTPStatus.OK, state)
                return
            if parsed.path == "/events":
                query = parse_qs(parsed.query)
                after = int(query.get("after", ["0"])[0])
                self._json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "after": after,
                        "events": self.server.bridge.computer.ledger.after(after),
                    },
                )
                return
            if parsed.path == "/events/stream":
                self._events_stream(parsed.query)
                return
            if parsed.path == "/artifact":
                self._artifact(parsed.query)
                return
            self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
        except Exception as exc:
            self._error(exc)

    def _events_stream(self, query_string: str) -> None:
        query = parse_qs(query_string)
        after = int(query.get("after", ["0"])[0])
        wait = min(max(float(query.get("wait", ["20"])[0]), 0.0), 60.0)
        deadline = time.monotonic() + wait
        events: list[dict[str, Any]] = []
        while time.monotonic() <= deadline:
            events = self.server.bridge.computer.ledger.after(after)
            if events:
                break
            time.sleep(0.25)
        chunks = [
            f"id: {event['seq']}\nevent: {event['kind']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            for event in events
        ]
        if not chunks:
            chunks.append(": keepalive\n\n")
        data = "".join(chunks).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _artifact(self, query_string: str) -> None:
        query = parse_qs(query_string)
        value = query.get("path", [""])[0]
        target = safe_relative_path(self.server.bridge.computer.root, value, "artifact path")
        allowed = (
            self.server.bridge.computer.workspace.resolve(),
            self.server.bridge.computer.downloads.resolve(),
            self.server.bridge.computer.artifacts.resolve(),
        )
        if not any(target == root or root in target.parents for root in allowed):
            raise PlaywrightComputerError("artifact path is outside the exportable computer roots")
        if not target.is_file():
            raise PlaywrightComputerError("artifact does not exist or is not a file")
        data = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'inline; filename="{target.name}"')
        self.send_header("X-Content-SHA256", hash_bytes(data))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if not self._require_auth():
                return
            body = self._body()
            if parsed.path == "/observe":
                self._json(
                    HTTPStatus.OK,
                    self.server.bridge.call(self.server.bridge.computer.observe()),
                )
                return
            if parsed.path == "/act":
                action = body.get("action", body)
                self._json(
                    HTTPStatus.OK,
                    self.server.bridge.call(self.server.bridge.computer.execute(action)),
                )
                return
            if parsed.path == "/batch":
                actions = body.get("actions")
                self._json(
                    HTTPStatus.OK,
                    self.server.bridge.call(self.server.bridge.computer.execute_batch(actions)),
                )
                return
            if parsed.path == "/takeover":
                self._json(
                    HTTPStatus.OK,
                    self.server.bridge.call(
                        self.server.bridge.computer.takeover(seconds=body.get("seconds"))
                    ),
                )
                return
            if parsed.path == "/takeover/release":
                self._json(
                    HTTPStatus.OK,
                    self.server.bridge.call(
                        self.server.bridge.computer.release_takeover(
                            str(body.get("lease_id", ""))
                        )
                    ),
                )
                return
            if parsed.path == "/verify":
                self._json(
                    HTTPStatus.OK,
                    self.server.bridge.call(self.server.bridge.computer.verify()),
                )
                return
            if parsed.path == "/shutdown":
                result = self.server.bridge.close()
                self._json(HTTPStatus.OK, {"ok": True, **result})
                self.server.shutdown_requested.set()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
        except Exception as exc:
            self._error(exc)


def serve_browser_computer(
    computer: PlaywrightComputer,
    *,
    host: str,
    port: int,
    control_token: str,
) -> None:
    bridge = ComputerLoop(computer)
    try:
        health = bridge.start()
        server = BrowserComputerServer((host, port), bridge, control_token=control_token)
        address, actual_port = server.server_address[:2]
        display_address = "127.0.0.1" if str(address) in {"0.0.0.0", "::"} else str(address)
        record = {
            "schema": "tier-bench/playwright-computer-server@1",
            "computer_id": computer.config["id"],
            "pid": os.getpid(),
            "host": str(address),
            "port": int(actual_port),
            "url": f"http://{display_address}:{actual_port}/",
            "started_at": now_utc(),
            "control_token_sha256": hash_json({"token": control_token}),
            "health": health,
        }
        atomic_json(computer.root / "server.json", record, mode=0o600)
        print(json.dumps(record, indent=2, sort_keys=True), flush=True)
        try:
            server.serve_forever(poll_interval=0.25)
        finally:
            server.server_close()
            if not computer.closed:
                bridge.close()
    except Exception:
        if bridge.thread.is_alive():
            try:
                bridge.close()
            except Exception:
                bridge.loop.call_soon_threadsafe(bridge.loop.stop)
        raise


def _dashboard_html() -> str:
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tier Browser Computer</title>
<style>
body{font:14px/1.45 system-ui,sans-serif;margin:0;background:#111;color:#eee}header{padding:14px 18px;border-bottom:1px solid #333;display:flex;gap:10px;align-items:center}main{display:grid;grid-template-columns:minmax(0,2fr) minmax(320px,1fr);gap:12px;padding:12px}section{background:#181818;border:1px solid #333;border-radius:8px;padding:12px}img{max-width:100%;border:1px solid #444}pre{white-space:pre-wrap;word-break:break-word;max-height:45vh;overflow:auto}button,input{font:inherit;padding:7px 9px}input{flex:1;background:#222;color:#fff;border:1px solid #555}button{background:#333;color:#fff;border:1px solid #666;border-radius:4px}#status{margin-left:auto}
</style></head><body><header><strong>Tier Browser Computer</strong><input id="token" type="password" placeholder="Control token"><button onclick="saveToken()">Set token</button><button onclick="observe()">Observe</button><button onclick="takeover()">Take over</button><span id="status"></span></header><main><section><h2>Marked browser state</h2><img id="shot"><pre id="meta"></pre></section><section><h2>Events</h2><pre id="events"></pre></section></main>
<script>
let token=sessionStorage.getItem('tier-browser-token')||'';document.getElementById('token').value=token;let seq=0;let shotUrl='';
function saveToken(){token=document.getElementById('token').value;sessionStorage.setItem('tier-browser-token',token);refresh()}
async function api(path,options={}){options.headers={...(options.headers||{}),'X-Tier-Browser-Token':token,'Content-Type':'application/json'};let r=await fetch(path,options);let j=await r.json();if(!r.ok)throw new Error(j.error||r.status);return j}
async function loadShot(path){let r=await fetch('/artifact?path='+encodeURIComponent(path),{headers:{'X-Tier-Browser-Token':token}});if(!r.ok)throw new Error('screenshot '+r.status);let b=await r.blob();if(shotUrl)URL.revokeObjectURL(shotUrl);shotUrl=URL.createObjectURL(b);document.getElementById('shot').src=shotUrl}
async function refresh(){try{let s=await api('/state');document.getElementById('meta').textContent=JSON.stringify({state_id:s.state_id,url:s.url,title:s.title,tabs:s.tabs,elements:s.elements_text,scroll:s.scroll},null,2);await loadShot(s.artifacts.marked_screenshot.path);document.getElementById('status').textContent=s.url;let e=await api('/events?after='+seq);for(const x of e.events){seq=x.seq;document.getElementById('events').textContent+=JSON.stringify(x)+'\n'} }catch(e){document.getElementById('status').textContent=e}}
async function observe(){await api('/observe',{method:'POST',body:'{}'});refresh()}
async function takeover(){let v=await api('/takeover',{method:'POST',body:'{}'});alert('Takeover lease '+v.lease_id+' active. Use the visible browser window, then release through the API or CLI.');refresh()}
setInterval(refresh,2500);refresh();
</script></body></html>"""
