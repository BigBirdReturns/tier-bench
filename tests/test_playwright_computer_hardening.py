#!/usr/bin/env python3
"""Focused network-boundary tests for the public Playwright computer runtime."""
from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:  # noqa: N802
        html = b"""<!doctype html><html><body>
        <a id='blocked' href='https://blocked.example/private'>Blocked target</a>
        <img src='https://blocked.example/pixel.png'>
        <script>console.log('fixture-console')</script>
        </body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)


def _config(url: str) -> dict:
    return {
        "schema": "tier-bench/playwright-computer@1",
        "id": "hardened-browser-computer",
        "mode": "isolated",
        "headless": True,
        "start_url": url,
        "paths": {
            "workspace": "workspace",
            "profile": "profile",
            "downloads": "downloads",
            "artifacts": "artifacts",
            "secrets": "secrets",
        },
        "viewport": {"width": 900, "height": 700},
        "allowed_schemes": ["https", "http", "about", "data"],
        "allowed_domains": [],
        "blocked_domains": ["blocked.example"],
        "deny_private_networks": False,
        "trace": False,
        "record_video": False,
        "force_open_shadow_dom": False,
        "policy": {
            "max_actions_per_batch": 10,
            "default_timeout_ms": 5000,
            "navigation_timeout_ms": 15000,
            "wait_between_actions_ms": 10,
            "viewport_expansion": 200,
            "max_visible_text_chars": 5000,
            "highlight_elements": True,
            "external_write_requires_approval": True,
            "sensitive_input_requires_approval": True,
            "allow_javascript": False,
            "allow_upload": True,
            "allow_download": True,
        },
        "takeover": {"enabled": True, "lease_seconds": 60},
    }


async def _roundtrip() -> None:
    from tier_runner.playwright_computer import PlaywrightComputer

    fixture = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    fixture_thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    fixture_thread.start()
    url = f"http://127.0.0.1:{fixture.server_address[1]}/"
    root = Path(tempfile.mkdtemp(prefix="tier-browser-hardening-"))
    computer = PlaywrightComputer(_config(url), root=root)
    try:
        await computer.start()
        events = computer.ledger.after(0)
        blocked = [row for row in events if row["kind"] == "browser.request.blocked"]
        assert blocked, events
        console = [
            row
            for row in events
            if row["kind"] == "browser.console"
            and row["detail"].get("text") == "fixture-console"
        ]
        assert len(console) == 1, console
        state = computer.current_state
        target = next(
            element
            for element in state["elements"]
            if element.get("attributes", {}).get("id") == "blocked"
        )
        receipt = await computer.execute(
            {
                "schema": "tier-bench/playwright-action@1",
                "action_id": "blocked-navigation",
                "expected_state_id": state["state_id"],
                "op": "click",
                "args": {"index": target["index"]},
                "intent": "Open the blocked test target",
            }
        )
        assert "blocked.example" not in computer.current_state["url"]
        events = computer.ledger.after(0)
        assert any(row["kind"] == "browser.request.blocked" for row in events)
        assert receipt["receipt_sha256"]
    finally:
        await computer.close()
        fixture.shutdown()
        fixture.server_close()
        fixture_thread.join(timeout=5)
        shutil.rmtree(root, ignore_errors=True)


def test_optional_hardened_network_boundary() -> None:
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("  skip  test_optional_hardened_network_boundary: Playwright unavailable")
        return
    asyncio.run(_roundtrip())


def main() -> int:
    try:
        test_optional_hardened_network_boundary()
        print("  ok  test_optional_hardened_network_boundary")
        print("\n1/1 Playwright hardening tests passed")
        return 0
    except Exception as exc:
        print(
            "FAIL  test_optional_hardened_network_boundary: "
            f"{type(exc).__name__}: {exc}"
        )
        print("\n0/1 Playwright hardening tests passed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
