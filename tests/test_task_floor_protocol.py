#!/usr/bin/env python3
"""Contract tests for Task Floor manifests, state, actions, and approvals."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tier_runner.playwright_computer_common import (  # noqa: E402
    PlaywrightComputerError,
    load_json,
)
from tier_runner.task_floor_protocol import (  # noqa: E402
    ACTION_SCHEMA,
    APPROVAL_SCHEMA,
    PROFILE_ORDER,
    profile_requirement_map,
    seal_action,
    seal_approval,
    seal_state,
    validate_action,
    validate_approval,
    validate_manifest,
    validate_state,
)

MANIFEST = ROOT / "experiments" / "task_floor" / "reference_manifest.json"


def test_reference_manifest_is_stable_and_honest() -> None:
    raw = load_json(MANIFEST)
    manifest = validate_manifest(raw)
    assert manifest["manifest_sha256"] == raw["manifest_sha256"]
    assert manifest["conformance"]["profiles_claimed"] == [
        "TF0",
        "TF1",
        "TF2",
        "TF3",
        "TF4",
        "TF5",
    ]
    assert manifest["conformance"]["production_qualified"] is False
    assert {interface["protocol"] for interface in manifest["interfaces"]} >= {
        "native-json",
        "mcp",
        "a2a",
        "ag-ui",
        "opentelemetry",
        "in-toto",
        "opa",
    }
    profiles = profile_requirement_map()
    assert tuple(profiles) == PROFILE_ORDER
    assert profiles["TF1"]["requirements"][0] == "state.content_addressed"
    assert "production.qualified" in profiles["TF7"]["requirements"]


def test_manifest_tamper_fails_hash_verification() -> None:
    raw = load_json(MANIFEST)
    raw["name"] = "tampered"
    try:
        validate_manifest(raw)
    except PlaywrightComputerError as exc:
        assert "manifest_sha256" in str(exc)
    else:
        raise AssertionError("tampered manifest must fail")


def test_state_action_and_approval_form_one_content_addressed_chain() -> None:
    state = seal_state(
        {
            "task_id": "floor-contract-fixture",
            "revision": 1,
            "observed_at": "2026-07-28T00:00:00Z",
            "previous_state_id": None,
            "surfaces": {"api": {"ready": True}},
            "artifacts": [],
            "data": {"counter": 0},
        }
    )
    assert validate_state(state) == state
    action = seal_action(
        {
            "schema": ACTION_SCHEMA,
            "action_id": "increment-counter",
            "task_id": state["task_id"],
            "expected_state_id": state["state_id"],
            "surface": "api",
            "operation": "increment",
            "effect": "local_write",
            "arguments": {"amount": 1},
            "intent": "Increment the fixture counter exactly once.",
            "idempotency_key": "fixture-increment-v1",
            "principal": {"type": "agent", "id": "planner-a"},
            "on_behalf_of": {"type": "human", "id": "operator"},
            "resource": {"type": "counter", "id": "fixture"},
            "preconditions": [{"path": "/counter", "equals": 0}],
            "expected_postconditions": [{"path": "/counter", "equals": 1}],
            "data_classification": ["internal"],
            "compensation": {"operation": "decrement", "amount": 1},
            "trace_context": {
                "traceparent": "00-11111111111111111111111111111111-2222222222222222-01"
            },
        }
    )
    assert validate_action(action) == action
    approval = seal_approval(
        {
            "schema": APPROVAL_SCHEMA,
            "approval_id": "approval-fixture-1",
            "task_id": state["task_id"],
            "state_id": state["state_id"],
            "action_sha256": action["action_sha256"],
            "effect": action["effect"],
            "decision": "approve",
            "authority": {"type": "human", "id": "operator"},
            "issued_at": "2026-07-28T00:00:01Z",
            "expires_at": "2026-07-28T00:10:01Z",
            "scope": {"resource": action["resource"]},
            "constraints": [{"max_executions": 1}],
            "reason": "The state and postcondition were inspected.",
        }
    )
    assert validate_approval(approval) == approval
    assert approval["state_id"] == action["expected_state_id"]
    assert approval["action_sha256"] == action["action_sha256"]

    stale = deepcopy(action)
    stale["expected_state_id"] = "0" * 64
    try:
        validate_action(stale)
    except PlaywrightComputerError as exc:
        assert "action_sha256" in str(exc)
    else:
        raise AssertionError("changing state binding without resealing must fail")


def main() -> int:
    tests = [
        test_reference_manifest_is_stable_and_honest,
        test_manifest_tamper_fails_hash_verification,
        test_state_action_and_approval_form_one_content_addressed_chain,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok  {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} Task Floor protocol tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
