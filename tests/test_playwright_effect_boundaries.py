#!/usr/bin/env python3
"""Regression tests for lexical browser effect classification."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tier_runner.playwright_computer import _classify_action_precise  # noqa: E402
from tier_runner.playwright_computer_protocol import validate_config  # noqa: E402


def config() -> dict:
    return validate_config(
        {
            "schema": "tier-bench/playwright-computer@1",
            "id": "effect-boundary-fixture",
            "mode": "isolated",
            "headless": True,
            "start_url": "about:blank",
            "paths": {
                "workspace": "workspace",
                "profile": "profile",
                "downloads": "downloads",
                "artifacts": "artifacts",
                "secrets": "secrets",
            },
            "viewport": {"width": 1000, "height": 700},
            "allowed_schemes": ["https", "http", "about", "data"],
            "allowed_domains": [],
            "blocked_domains": [],
            "deny_private_networks": True,
            "trace": False,
            "record_video": False,
            "force_open_shadow_dom": False,
            "policy": {
                "external_write_requires_approval": True,
                "sensitive_input_requires_approval": True,
                "allow_javascript": False,
                "allow_upload": True,
                "allow_download": True,
            },
            "takeover": {"enabled": True, "lease_seconds": 60},
        }
    )


def test_acceptance_and_reordered_are_not_effect_verbs() -> None:
    state = {
        "elements": [
            {
                "index": 1,
                "tag": "button",
                "role": "button",
                "name": "Read acceptance contract",
                "text": "Read acceptance contract",
                "input_type": "",
                "attributes": {"id": "acceptance-tab"},
            },
            {
                "index": 2,
                "tag": "button",
                "role": "button",
                "name": "Show reordered results",
                "text": "Show reordered results",
                "input_type": "",
                "attributes": {"id": "reordered"},
            },
        ]
    }
    for index in (1, 2):
        category, reasons = _classify_action_precise(
            {
                "op": "click",
                "args": {"index": index},
                "intent": state["elements"][index - 1]["name"],
            },
            state,
            config(),
        )
        assert category == "interactive", (category, reasons)


def test_accept_and_order_remain_effect_verbs() -> None:
    state = {
        "elements": [
            {
                "index": 1,
                "tag": "button",
                "role": "button",
                "name": "Accept terms",
                "text": "Accept terms",
                "input_type": "",
                "attributes": {},
            },
            {
                "index": 2,
                "tag": "button",
                "role": "button",
                "name": "Order now",
                "text": "Order now",
                "input_type": "",
                "attributes": {},
            },
        ]
    }
    for index in (1, 2):
        category, reasons = _classify_action_precise(
            {
                "op": "click",
                "args": {"index": index},
                "intent": state["elements"][index - 1]["name"],
            },
            state,
            config(),
        )
        assert category == "external_write"
        assert reasons


def main() -> int:
    tests = [
        test_acceptance_and_reordered_are_not_effect_verbs,
        test_accept_and_order_remain_effect_verbs,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok  {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} effect-boundary tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
