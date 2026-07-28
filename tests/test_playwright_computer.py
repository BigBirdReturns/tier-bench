#!/usr/bin/env python3
"""Control-plane and optional Chromium tests for the Playwright browser computer."""
from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tier_runner.playwright_computer_common import (  # noqa: E402
    EventLedger,
    PlaywrightComputerError,
    hash_json,
)
from tier_runner.playwright_computer_protocol import (  # noqa: E402
    batch_break_reason,
    classify_action,
    url_allowed,
    validate_action,
    validate_config,
)


def config(*, start_url: str = "about:blank", deny_private: bool = True) -> dict:
    return {
        "schema": "tier-bench/playwright-computer@1",
        "id": "fixture-browser-computer",
        "title": "Fixture browser computer",
        "mode": "isolated",
        "headless": True,
        "start_url": start_url,
        "paths": {
            "workspace": "workspace",
            "profile": "profile",
            "downloads": "downloads",
            "artifacts": "artifacts",
            "secrets": "secrets",
        },
        "viewport": {"width": 1000, "height": 760},
        "allowed_schemes": ["https", "http", "about", "data"],
        "allowed_domains": [],
        "blocked_domains": ["blocked.example"],
        "deny_private_networks": deny_private,
        "storage_state_file": "state.json",
        "trace": False,
        "record_video": False,
        "force_open_shadow_dom": False,
        "policy": {
            "max_actions_per_batch": 10,
            "default_timeout_ms": 5000,
            "navigation_timeout_ms": 15000,
            "wait_between_actions_ms": 10,
            "viewport_expansion": 200,
            "max_visible_text_chars": 10000,
            "highlight_elements": True,
            "external_write_requires_approval": True,
            "sensitive_input_requires_approval": True,
            "allow_javascript": False,
            "allow_upload": True,
            "allow_download": True,
        },
        "takeover": {"enabled": True, "lease_seconds": 60},
    }


def action(action_id: str, op: str, state_id: str | None, **args: object) -> dict:
    return {
        "schema": "tier-bench/playwright-action@1",
        "action_id": action_id,
        "expected_state_id": state_id,
        "op": op,
        "args": args,
        "intent": args.pop("intent", op) if "intent" in args else op,
    }


def test_config_and_action_contracts_fail_closed() -> None:
    normalized = validate_config(config())
    assert normalized["mode"] == "isolated"
    assert normalized["deny_private_networks"] is True
    broken = config()
    broken["policy"]["external_write_requires_approval"] = "true"
    try:
        validate_config(broken)
    except PlaywrightComputerError as exc:
        assert "must be boolean" in str(exc)
    else:
        raise AssertionError("truthy policy strings must not pass")
    try:
        validate_action({"action_id": "bad", "op": "click", "args": {}})
    except PlaywrightComputerError as exc:
        assert "requires args.index" in str(exc)
    else:
        raise AssertionError("indexed actions require an element index")


def test_network_policy_blocks_private_and_blocked_targets() -> None:
    normalized = validate_config(config())
    assert url_allowed("about:blank", normalized)[0] is True
    assert url_allowed("http://127.0.0.1/admin", normalized)[0] is False
    assert url_allowed("https://blocked.example/path", normalized)[0] is False
    assert url_allowed("file:///etc/passwd", normalized)[0] is False


def test_side_effect_classifier_requires_approval() -> None:
    normalized = validate_config(config())
    state = {
        "elements": [
            {
                "index": 4,
                "tag": "button",
                "role": "button",
                "name": "Submit order",
                "text": "Submit order",
                "input_type": "submit",
                "attributes": {},
            },
            {
                "index": 5,
                "tag": "input",
                "role": "textbox",
                "name": "Password",
                "text": "",
                "input_type": "password",
                "attributes": {"type": "password"},
            },
        ]
    }
    submit = validate_action(action("submit", "click", "0" * 64, index=4))
    category, reasons = classify_action(submit, state, normalized)
    assert category == "external_write"
    assert reasons
    password = validate_action(
        action("password", "fill", "0" * 64, index=5, text="not-a-real-secret")
    )
    category, _ = classify_action(password, state, normalized)
    assert category == "sensitive_input"


def test_batch_breaks_when_page_or_interaction_topology_changes() -> None:
    before = {
        "page_id": "page-a",
        "url": "https://example.com/a",
        "tabs": [{"page_id": "page-a"}],
        "elements": [{"signature": "one"}],
    }
    after = {
        "page_id": "page-a",
        "url": "https://example.com/a",
        "tabs": [{"page_id": "page-a"}],
        "elements": [{"signature": "one"}, {"signature": "two"}],
    }
    assert "new interactive" in str(batch_break_reason(before, after))
    changed = dict(after)
    changed["url"] = "https://example.com/b"
    assert batch_break_reason(before, changed) == "URL changed"


def test_event_ledger_detects_tampering() -> None:
    parent = Path(tempfile.mkdtemp(prefix="tier-browser-ledger-"))
    try:
        ledger = EventLedger(parent / "events.jsonl", "fixture-browser-computer")
        ledger.append("computer.started", detail={"a": 1})
        ledger.append("browser.state.observed", state_id="1" * 64)
        assert ledger.verify()["ok"] is True
        rows = (parent / "events.jsonl").read_text(encoding="utf-8").splitlines()
        value = json.loads(rows[0])
        value["detail"]["a"] = 2
        rows[0] = json.dumps(value, sort_keys=True)
        (parent / "events.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
        assert ledger.verify()["ok"] is False
    finally:
        shutil.rmtree(parent, ignore_errors=True)


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:  # noqa: N802
        html = b"""<!doctype html><html><body>
        <label>Name <input id='name' name='name'></label>
        <button id='show' onclick="const b=document.createElement('button');b.id='submit';b.textContent='Submit order';b.onclick=()=>document.body.dataset.submitted='yes';document.body.appendChild(b)">Show advanced</button>
        <a id='download' download='report.txt' href='data:text/plain,hello'>Download report</a>
        <iframe srcdoc="<button id='inside'>Inside frame</button>"></iframe>
        <div id='shadow'></div>
        <script>document.getElementById('shadow').attachShadow({mode:'open'}).innerHTML='<button id="shadow-action">Shadow action</button>';</script>
        </body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)


def _fixture_server() -> tuple[ThreadingHTTPServer, threading.Thread, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_address[1]}/"


def _find(state: dict, *, element_id: str | None = None, name: str | None = None) -> dict:
    for element in state["elements"]:
        if element_id and element.get("attributes", {}).get("id") == element_id:
            return element
        if name and element.get("name") == name:
            return element
    raise AssertionError(f"element not found: id={element_id!r} name={name!r}")


async def _browser_roundtrip() -> None:
    try:
        from tier_runner.playwright_computer_runtime import PlaywrightComputer
    except ImportError:
        print("  skip  browser roundtrip: Playwright unavailable")
        return
    server, thread, url = _fixture_server()
    parent = Path(tempfile.mkdtemp(prefix="tier-browser-runtime-"))
    raw = config(start_url=url, deny_private=False)
    computer = PlaywrightComputer(raw, root=parent, approval_token="approve-fixture")
    try:
        await computer.start()
        state = computer.current_state
        assert state and state["url"] == url
        assert _find(state, element_id="name")
        assert _find(state, element_id="inside")
        assert _find(state, element_id="shadow-action")
        assert Path(parent / state["artifacts"]["clean_screenshot"]["path"]).is_file()
        assert Path(parent / state["artifacts"]["marked_screenshot"]["path"]).is_file()

        name_element = _find(state, element_id="name")
        fill = action(
            "fill-name",
            "fill",
            state["state_id"],
            index=name_element["index"],
            text="Jonathan",
        )
        fill_receipt = await computer.execute(fill)
        assert fill_receipt["error"] is None
        assert fill_receipt["action"]["args"]["text_redacted"] is True

        state = computer.current_state
        show = _find(state, element_id="show")
        name_element = _find(state, element_id="name")
        batch = await computer.execute_batch(
            [
                action("show-options", "click", state["state_id"], index=show["index"]),
                action(
                    "should-not-run",
                    "fill",
                    state["state_id"],
                    index=name_element["index"],
                    text="blocked by page change",
                ),
            ]
        )
        assert len(batch["receipts"]) == 1
        assert "new interactive" in str(batch["stopped_reason"])

        state = computer.current_state
        submit = _find(state, element_id="submit")
        blocked = action("submit-blocked", "click", state["state_id"], index=submit["index"])
        try:
            await computer.execute(blocked)
        except PlaywrightComputerError as exc:
            assert "approval token" in str(exc)
        else:
            raise AssertionError("external write should require approval")
        approved = dict(blocked)
        approved["action_id"] = "submit-approved"
        approved["approval_token"] = "approve-fixture"
        result = await computer.execute(approved)
        assert result["error"] is None

        lease = await computer.takeover(seconds=10)
        try:
            await computer.execute(action("blocked-takeover", "observe", None))
        except PlaywrightComputerError as exc:
            assert "takeover" in str(exc)
        else:
            raise AssertionError("agent action must stop during human takeover")
        released = await computer.release_takeover(lease["lease_id"])
        assert released["released"] is True
        assert (await computer.verify())["ok"] is True
    finally:
        try:
            await computer.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            shutil.rmtree(parent, ignore_errors=True)


def test_optional_playwright_browser_roundtrip() -> None:
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("  skip  test_optional_playwright_browser_roundtrip: Playwright unavailable")
        return
    asyncio.run(_browser_roundtrip())


def test_optional_http_control_plane() -> None:
    try:
        import playwright  # noqa: F401
        from tier_runner.playwright_computer_runtime import PlaywrightComputer
        from tier_runner.playwright_computer_server import serve_browser_computer
    except ImportError:
        print("  skip  test_optional_http_control_plane: Playwright unavailable")
        return
    fixture, fixture_thread, url = _fixture_server()
    parent = Path(tempfile.mkdtemp(prefix="tier-browser-server-"))
    raw = config(start_url=url, deny_private=False)
    computer = PlaywrightComputer(raw, root=parent, approval_token="approval")
    thread = threading.Thread(
        target=serve_browser_computer,
        kwargs={
            "computer": computer,
            "host": "127.0.0.1",
            "port": 0,
            "control_token": "control-token",
        },
        daemon=True,
    )
    thread.start()
    try:
        record_path = parent / "server.json"
        deadline = time.time() + 30
        while time.time() < deadline and not record_path.exists():
            time.sleep(0.1)
        if not record_path.exists():
            raise AssertionError("browser server did not publish its control record")
        record = json.loads(record_path.read_text(encoding="utf-8"))
        base = record["url"].rstrip("/")

        def request(path: str, *, method: str = "GET", body: bytes | None = None) -> dict:
            req = Request(
                base + path,
                method=method,
                data=body,
                headers={
                    "X-Tier-Browser-Token": "control-token",
                    "Content-Type": "application/json",
                },
            )
            with urlopen(req, timeout=30) as response:
                return json.loads(response.read())

        health = request("/healthz")
        assert health["ok"] is True
        state = request("/observe", method="POST", body=b"{}")
        assert state["state_id"]
        events = request("/events?after=0")
        assert events["events"]
        stopped = request("/shutdown", method="POST", body=b"{}")
        assert stopped["ok"] is True
        thread.join(timeout=20)
        assert not thread.is_alive()
    finally:
        fixture.shutdown()
        fixture.server_close()
        fixture_thread.join(timeout=5)
        shutil.rmtree(parent, ignore_errors=True)


def main() -> int:
    tests = [
        test_config_and_action_contracts_fail_closed,
        test_network_policy_blocks_private_and_blocked_targets,
        test_side_effect_classifier_requires_approval,
        test_batch_breaks_when_page_or_interaction_topology_changes,
        test_event_ledger_detects_tampering,
        test_optional_playwright_browser_roundtrip,
        test_optional_http_control_plane,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok  {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} Playwright-computer tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
