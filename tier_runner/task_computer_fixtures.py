"""Deterministic, project-shaped browser worlds for Task Computer qualification."""
from __future__ import annotations

from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from typing import Any
from urllib.parse import urlparse

from .playwright_computer_common import PlaywrightComputerError, hash_json, now_utc


_STYLE = """
:root{font:16px/1.45 system-ui,sans-serif;color:#18212b;background:#edf1f5}*{box-sizing:border-box}
body{margin:0}.shell{max-width:1100px;margin:0 auto;padding:28px}.bar{display:flex;align-items:center;gap:12px;padding:14px 18px;background:#17212b;color:#fff}.bar strong{font-size:18px}.bar span{opacity:.72}.card{background:#fff;border:1px solid #cbd4dd;border-radius:12px;padding:18px;margin:14px 0;box-shadow:0 4px 16px rgba(20,35,50,.06)}
button,a.button{display:inline-block;border:1px solid #315c86;background:#eaf3fc;color:#163a5c;border-radius:8px;padding:10px 14px;text-decoration:none;font-weight:650;cursor:pointer;margin:4px 6px 4px 0}button.primary,a.primary{background:#215f96;color:#fff}button.danger{background:#8c2935;color:#fff}.muted{color:#66717d}.pill{display:inline-block;border-radius:99px;padding:3px 9px;background:#e7edf3;font-size:13px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px}.receipt{border-left:5px solid #287d4d;background:#eff9f2}.warning{border-left:5px solid #a56a10;background:#fff8e8}pre{white-space:pre-wrap;background:#101820;color:#d7ecff;padding:14px;border-radius:8px;overflow:auto}.phone{width:390px;height:690px;margin:18px auto;background:#121820;border:10px solid #242c36;border-radius:36px;position:relative;color:#fff;box-shadow:0 16px 50px rgba(0,0,0,.28)}.phone .screen{position:absolute;inset:42px 15px 18px;background:linear-gradient(150deg,#15345c,#1f6d7d);border-radius:20px;padding:24px}.visual-target{position:absolute;left:55%;top:55%;width:35%;height:11%;border-radius:16px;background:#f4d35e;color:#18212b;display:flex;align-items:center;justify-content:center;font-weight:800;box-shadow:0 6px 18px rgba(0,0,0,.25)}
"""


def _page(title: str, body: str, *, script: str = "") -> str:
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{escape(title)}</title><style>{_STYLE}</style></head><body><div class='bar'><strong>Tier Task Computer Lab</strong><span>{escape(title)}</span></div><main class='shell'>{body}</main><script>
async function fixtureAction(name,payload={{}}){{const response=await fetch('/action',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{name,payload}})}});if(!response.ok)throw new Error(await response.text());location.reload();}}
{script}
</script></body></html>"""


class ProjectFixtureApp:
    def __init__(self, scenario_id: str, variant: str):
        self.scenario_id = scenario_id
        self.variant = variant
        self.lock = threading.Lock()
        self.actions: list[dict[str, Any]] = []
        self.state = self._initial_state()

    def _initial_state(self) -> dict[str, Any]:
        if self.scenario_id == "tier-desk-approve-underdrain":
            return {"view": "queue", "reviewed": False, "task_state": "DRAFT"}
        if self.scenario_id == "axm-chat-pull-latest":
            return {"view": "list", "pulled": False, "imported_turns": 0, "sealed": False}
        if self.scenario_id == "screen-ghost-visual-fallback":
            return {"synced": False, "route": None}
        if self.scenario_id == "axm-world-underdrain-playtest":
            return {
                "stage": "briefing",
                "choice": None,
                "changed": None,
                "record": None,
                "next": None,
                "victory": False,
            }
        raise PlaywrightComputerError(f"unknown fixture scenario {self.scenario_id!r}")

    def apply(self, name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        with self.lock:
            self.actions.append({"name": name, "payload": payload, "ts": now_utc()})
            if self.scenario_id == "tier-desk-approve-underdrain":
                if name == "open_underdrain":
                    self.state["view"] = "detail"
                elif name == "show_acceptance" and self.state["view"] == "detail":
                    self.state["reviewed"] = True
                elif name == "arm_task" and self.state["reviewed"]:
                    self.state["task_state"] = "QUEUED"
                    self.state["view"] = "receipt"
                else:
                    raise PlaywrightComputerError(f"invalid Tier Desk transition {name!r}")
            elif self.scenario_id == "axm-chat-pull-latest":
                if name == "open_shared_chat":
                    self.state["view"] = "detail"
                elif name == "pull_latest" and self.state["view"] == "detail":
                    self.state["pulled"] = True
                    self.state["view"] = "diff"
                elif name == "import_turns" and self.state["pulled"]:
                    self.state["imported_turns"] = 3
                    self.state["view"] = "imported"
                elif name == "seal_shard" and self.state["imported_turns"] == 3:
                    self.state["sealed"] = True
                    self.state["view"] = "sealed"
                else:
                    raise PlaywrightComputerError(f"invalid axm-chat transition {name!r}")
            elif self.scenario_id == "screen-ghost-visual-fallback":
                if name != "visual_sync":
                    raise PlaywrightComputerError(f"invalid ScreenGhost transition {name!r}")
                self.state["synced"] = True
                self.state["route"] = "screen_ghost"
            elif self.scenario_id == "axm-world-underdrain-playtest":
                if name == "start_pilot" and self.state["stage"] == "briefing":
                    self.state["stage"] = "drain"
                elif name == "snake_drain" and self.state["stage"] == "drain":
                    self.state["choice"] = "snake the blocked main drain"
                    self.state["changed"] = "the obstruction tears open and exposes fungal mycelium"
                    self.state["stage"] = "fungus"
                elif name == "inspect_fungus" and self.state["stage"] == "fungus":
                    self.state["record"] = "sample UD-01 sealed with location and consequence"
                    self.state["stage"] = "report"
                elif name == "report_back" and self.state["stage"] == "report":
                    self.state["next"] = "follow the mycelium into the municipal underworks"
                    self.state["victory"] = True
                    self.state["stage"] = "receipt"
                else:
                    raise PlaywrightComputerError(f"invalid AXM World transition {name!r}")
            return dict(self.state)

    def render(self) -> str:
        with self.lock:
            state = dict(self.state)
        if self.scenario_id == "tier-desk-approve-underdrain":
            return self._render_tier_desk(state)
        if self.scenario_id == "axm-chat-pull-latest":
            return self._render_axm_chat(state)
        if self.scenario_id == "screen-ghost-visual-fallback":
            return self._render_screen_ghost(state)
        if self.scenario_id == "axm-world-underdrain-playtest":
            return self._render_axm_world(state)
        raise PlaywrightComputerError(f"unknown fixture scenario {self.scenario_id!r}")

    def _render_tier_desk(self, state: dict[str, Any]) -> str:
        if state["view"] == "queue":
            cards = [
                "<section class='card'><span class='pill'>ACCEPTED</span><h2>Refresh model waterline</h2><p class='muted'>Receipt closed.</p></section>",
                "<section class='card'><span class='pill'>DRAFT</span><h2>Underdrain authored pilot</h2><p>A plumber is drafted into the hidden war beneath his town.</p><button id='task-underdrain' onclick=\"fixtureAction('open_underdrain')\">Review Underdrain task</button></section>",
                "<section class='card'><span class='pill'>QUEUED</span><h2>AXM Chat shard refresh</h2><p class='muted'>Waiting for a worker.</p></section>",
            ]
            if self.variant == "reordered":
                cards = [cards[2], cards[0], cards[1]]
            return _page("Tier Desk queue", "<h1>Governed work queue</h1><div class='grid'>" + "".join(cards) + "</div>")
        if state["view"] == "detail":
            delay = "hidden" if self.variant == "dynamic" and not state["reviewed"] else ""
            script = "setTimeout(()=>document.getElementById('acceptance-tab')?.removeAttribute('hidden'),350);" if delay else ""
            arm = (
                "<button id='arm-task' class='primary' onclick=\"fixtureAction('arm_task')\">Arm task</button>"
                if state["reviewed"]
                else "<p class='muted'>Review acceptance before arming.</p>"
            )
            body = f"""<h1>Underdrain authored pilot</h1><section class='card'><h2>Task</h2><p>Rebuild the pilot around real plumbing actions, authored consequences, and playable continuation.</p><button id='acceptance-tab' {delay} onclick=\"fixtureAction('show_acceptance')\">Read acceptance contract</button>{arm}</section><section class='card'><h2>Acceptance</h2><p>The player can identify who they are, the drain problem, the chosen action, the changed world state, the recorded evidence, and what happens next.</p></section>"""
            return _page("Tier Desk task review", body, script=script)
        return _page(
            "Tier Desk transition receipt",
            "<section class='card receipt'><h1>Task armed</h1><p>Underdrain authored pilot moved from DRAFT to QUEUED under an explicit operator-authority receipt.</p><span class='pill'>QUEUED</span></section>",
        )

    def _render_axm_chat(self, state: dict[str, Any]) -> str:
        if state["view"] == "list":
            return _page(
                "AXM Chat retrieval",
                "<h1>Conversation intake</h1><section class='card'><span class='pill'>REMOTE UPDATE</span><h2>Manus Playwright computer</h2><p>Three turns exist after the latest local shard boundary.</p><button id='open-shared-chat' onclick=\"fixtureAction('open_shared_chat')\">Open shared conversation</button></section>",
            )
        if state["view"] == "detail":
            return _page(
                "Shared conversation",
                "<h1>Manus Playwright computer</h1><section class='card'><p>Local boundary: turn 42. Remote boundary: turn 45.</p><button id='pull-latest' onclick=\"fixtureAction('pull_latest')\">Pull latest turns</button></section>",
            )
        if state["view"] == "diff":
            return _page(
                "Conversation diff",
                "<h1>Three new turns</h1><section class='card'><pre>43 user: reconstruct it from first principles\n44 assistant: project-native task computer\n45 user: continue</pre><button id='import-turns' class='primary' onclick=\"fixtureAction('import_turns')\">Import new turns</button></section>",
            )
        if state["view"] == "imported":
            return _page(
                "AXM Chat import",
                "<section class='card receipt'><h1>Three turns imported</h1><p>Source-byte offsets and deterministic conversation identity are ready.</p><button id='seal-shard' class='primary' onclick=\"fixtureAction('seal_shard')\">Seal local shard</button></section>",
            )
        return _page(
            "AXM Chat seal",
            "<section class='card receipt'><h1>Shard sealed</h1><p>The local shard now ends at turn 45.</p><a id='download-sync-receipt' class='button primary' download href='/download/sync-receipt.json'>Download sync receipt</a></section>",
        )

    def _render_screen_ghost(self, state: dict[str, Any]) -> str:
        status = "Synchronized" if state["synced"] else "Waiting for local action"
        script = """
const surface=document.getElementById('visual-surface');
surface.addEventListener('click',event=>{const target=document.getElementById('visual-target').getBoundingClientRect();if(event.clientX>=target.left&&event.clientX<=target.right&&event.clientY>=target.top&&event.clientY<=target.bottom){fixtureAction('visual_sync',{x:event.clientX,y:event.clientY});}});
"""
        body = f"""<h1>ScreenGhost fallback surface</h1><p>The rendered control intentionally exposes no semantic button, role, tabindex, or click attribute. The screenshot is the action surface.</p><div id='visual-surface' class='phone'><div class='screen'><h2>Field handset</h2><p>{escape(status)}</p><div id='visual-target' class='visual-target'>SYNC NOW</div></div></div>"""
        if state["synced"]:
            body += "<section class='card receipt'><h2>Visual action accepted</h2><p>The state changed through the ScreenGhost route and emitted a photonic action receipt.</p></section>"
        return _page("ScreenGhost visual fallback", body, script=script)

    def _render_axm_world(self, state: dict[str, Any]) -> str:
        stage = state["stage"]
        if stage == "briefing":
            return _page(
                "Underdrain briefing",
                "<h1>You are the town plumber</h1><section class='card'><p>Main Street is backing up. The public problem is a blocked drain. The hidden problem is something growing inside it.</p><button id='start-pilot' class='primary' onclick=\"fixtureAction('start_pilot')\">Enter Main Street drain</button></section>",
            )
        if stage == "drain":
            buttons = [
                "<button id='snake-drain' class='primary' onclick=\"fixtureAction('snake_drain')\">Snake the main drain</button>",
                "<button id='leave-scene'>Leave the scene</button>",
            ]
            if self.variant == "reordered":
                buttons.reverse()
            return _page(
                "Underdrain action",
                "<h1>Main Street cleanout</h1><section class='card'><p>The line is blocked eighteen feet in. Choose a real plumbing action.</p>" + "".join(buttons) + "</section>",
            )
        if stage == "fungus":
            delay = "hidden" if self.variant == "dynamic" else ""
            script = "setTimeout(()=>document.getElementById('inspect-fungus')?.removeAttribute('hidden'),350);" if delay else ""
            return _page(
                "Underdrain consequence",
                f"<h1>The blockage tears open</h1><section class='card warning'><p>White mycelium tightens around the cable and pulls back into a service lateral.</p><button id='inspect-fungus' {delay} onclick=\"fixtureAction('inspect_fungus')\">Bag and record the sample</button></section>",
                script=script,
            )
        if stage == "report":
            return _page(
                "Underdrain continuation",
                "<h1>Sample UD-01</h1><section class='card'><p>The obstruction is no longer an ordinary drain call. The sample points toward the municipal underworks.</p><button id='report-back' class='primary' onclick=\"fixtureAction('report_back')\">Report the finding and continue</button></section>",
            )
        return _page(
            "Underdrain playtest receipt",
            "<section class='card receipt'><h1>Pilot complete</h1><p>You acted as the plumber, opened the drain, exposed the fungal cause, sealed a sample, and unlocked the municipal-underworks continuation.</p></section>",
        )

    def visual_target(self, visual_id: str, viewport: dict[str, int]) -> dict[str, Any]:
        if self.scenario_id != "screen-ghost-visual-fallback" or visual_id != "sync-now":
            raise PlaywrightComputerError(f"fixture has no visual target {visual_id!r}")
        width = int(viewport.get("width", 1280))
        height = int(viewport.get("height", 900))
        # The phone is centered inside the 1100px shell. These normalized coordinates
        # are fixture-only oracle evidence and never represent a real ScreenGhost proof.
        return {
            "visual_id": visual_id,
            "x": round(width * 0.575),
            "y": round(height * 0.63),
            "coordinate_space": "viewport_pixels",
            "evidence_tier": "synthetic_fixture_oracle",
            "confidence": 1.0,
        }

    def acceptance(self) -> list[dict[str, Any]]:
        with self.lock:
            state = dict(self.state)
            actions = list(self.actions)
        if self.scenario_id == "tier-desk-approve-underdrain":
            checks = [
                ("acceptance-reviewed", state["reviewed"] is True, state["reviewed"], True),
                ("task-queued", state["task_state"] == "QUEUED", state["task_state"], "QUEUED"),
            ]
        elif self.scenario_id == "axm-chat-pull-latest":
            checks = [
                ("three-turn-delta", state["imported_turns"] == 3, state["imported_turns"], 3),
                ("shard-sealed", state["sealed"] is True, state["sealed"], True),
            ]
        elif self.scenario_id == "screen-ghost-visual-fallback":
            checks = [
                ("visual-sync", state["synced"] is True, state["synced"], True),
                ("visual-route", state["route"] == "screen_ghost", state["route"], "screen_ghost"),
            ]
        else:
            checks = [
                ("real-plumbing-choice", state["choice"] == "snake the blocked main drain", state["choice"], "snake the blocked main drain"),
                ("world-changed", bool(state["changed"]), state["changed"], "non-empty consequence"),
                ("evidence-recorded", bool(state["record"]), state["record"], "non-empty record"),
                ("continuation-unlocked", bool(state["next"]), state["next"], "non-empty next beat"),
                ("pilot-won", state["victory"] is True, state["victory"], True),
            ]
        return [
            {"id": identifier, "pass": passed, "observed": observed, "expected": expected}
            for identifier, passed, observed, expected in checks
        ] + [{"id": "fixture-actions-recorded", "pass": bool(actions), "observed": len(actions), "expected": ">0"}]

    def handoff(self) -> dict[str, Any]:
        with self.lock:
            state = dict(self.state)
            actions = list(self.actions)
        if self.scenario_id == "tier-desk-approve-underdrain":
            return {
                "schema": "tier-bench/tier-desk-computer-handoff@1",
                "task_id": "underdrain-authored-pilot",
                "transition": "DRAFT->QUEUED",
                "reviewed": state["reviewed"],
            }
        if self.scenario_id == "axm-chat-pull-latest":
            return {
                "schema": "tier-bench/axm-chat-browser-sync-handoff@1",
                "conversation_id": "manus-playwright-computer",
                "previous_turn": 42,
                "current_turn": 45,
                "imported_turns": state["imported_turns"],
                "sealed": state["sealed"],
            }
        if self.scenario_id == "screen-ghost-visual-fallback":
            return {
                "schema": "tier-bench/screen-ghost-surface-handoff@1",
                "source_type": "photonic",
                "route": state["route"],
                "synced": state["synced"],
            }
        return {
            "schema": "tier-bench/axm-world-blind-playtest@1",
            "identity": "town plumber drafted into the hidden drain war",
            "problem": "Main Street drain blockage caused by fungal mycelium",
            "choice": state["choice"],
            "changed": state["changed"],
            "record": state["record"],
            "next": state["next"],
            "victory": state["victory"],
            "action_count": len(actions),
        }

    def download(self, name: str) -> tuple[str, bytes]:
        if self.scenario_id != "axm-chat-pull-latest" or name != "sync-receipt.json":
            raise PlaywrightComputerError(f"fixture download does not exist: {name}")
        if not self.state["sealed"]:
            raise PlaywrightComputerError("sync receipt is not available before the shard is sealed")
        value = {
            "schema": "axm-chat/browser-sync-receipt@1",
            "conversation_id": "manus-playwright-computer",
            "previous_turn": 42,
            "current_turn": 45,
            "imported_turns": 3,
            "source_bytes_sha256": hash_json({"turns": [43, 44, 45]}),
            "sealed": True,
        }
        value["receipt_sha256"] = hash_json(value)
        return "application/json", (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


class _FixtureServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], app: ProjectFixtureApp):
        super().__init__(address, _FixtureHandler)
        self.app = app


class _FixtureHandler(BaseHTTPRequestHandler):
    server: _FixtureServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def _send(self, status: int, content_type: str, data: bytes, **headers: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                self._send(HTTPStatus.OK, "text/html; charset=utf-8", self.server.app.render().encode("utf-8"))
                return
            if parsed.path.startswith("/download/"):
                name = Path(parsed.path).name
                content_type, data = self.server.app.download(name)
                self._send(
                    HTTPStatus.OK,
                    content_type,
                    data,
                    **{"Content-Disposition": f'attachment; filename="{name}"'},
                )
                return
            self._send(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n")
        except Exception as exc:
            self._send(HTTPStatus.BAD_REQUEST, "text/plain; charset=utf-8", f"{type(exc).__name__}: {exc}\n".encode("utf-8"))

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/action":
            self._send(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            value = json.loads(self.rfile.read(length) if length else b"{}")
            state = self.server.app.apply(str(value.get("name", "")), value.get("payload"))
            data = (json.dumps({"ok": True, "state": state}, sort_keys=True) + "\n").encode("utf-8")
            self._send(HTTPStatus.OK, "application/json; charset=utf-8", data)
        except Exception as exc:
            self._send(HTTPStatus.BAD_REQUEST, "text/plain; charset=utf-8", f"{type(exc).__name__}: {exc}\n".encode("utf-8"))


class ProjectFixtureServer:
    def __init__(self, scenario_id: str, variant: str):
        self.app = ProjectFixtureApp(scenario_id, variant)
        self.server = _FixtureServer(("127.0.0.1", 0), self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/"

    def start(self) -> "ProjectFixtureServer":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
