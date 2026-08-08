#!/usr/bin/env python3
"""Project-cartridge, policy, mutation, and optional Chromium tests."""
from __future__ import annotations

import asyncio
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CATALOG = ROOT / "experiments" / "task_computer" / "project_scenarios.json"

from tier_runner.playwright_computer_common import PlaywrightComputerError  # noqa: E402
from tier_runner.task_computer_lab import (  # noqa: E402
    TaskComputerRunner,
    load_catalog,
    verify_run,
)
from tier_runner.task_computer_protocol import (  # noqa: E402
    compile_planner_packet,
    critic_verdict,
    scenario_by_id,
    screen_ghost_request,
    validate_proposal,
)


def _state(elements: list[dict] | None = None) -> dict:
    return {
        "state_id": "1" * 64,
        "page_id": "page-fixture",
        "url": "http://127.0.0.1/",
        "title": "Fixture",
        "tabs": [{"page_id": "page-fixture", "active": True}],
        "elements": elements or [],
        "elements_text": "",
        "scroll": {
            "pixels_above": 0,
            "pixels_below": 0,
            "viewport_height": 900,
            "document_height": 900,
        },
        "artifacts": {
            "clean_screenshot": {"path": "clean.png", "bytes": 1, "sha256": "2" * 64},
            "marked_screenshot": {"path": "marked.png", "bytes": 1, "sha256": "3" * 64},
            "visible_text": {"path": "visible.txt", "bytes": 1, "sha256": "4" * 64},
        },
    }


def test_catalog_encodes_project_needs() -> None:
    catalog = load_catalog(CATALOG)
    assert catalog["id"] == "axm-project-task-computer-v1"
    projects = {scenario["project"] for scenario in catalog["scenarios"]}
    assert projects == {"tier-desk", "axm-chat", "screen-ghost", "axm-world"}
    for scenario in catalog["scenarios"]:
        assert scenario["cold_operator"]["identity"]
        assert scenario["cold_operator"]["problem"]
        assert scenario["cold_operator"]["choice"]
        assert scenario["cold_operator"]["changed"]
        assert scenario["cold_operator"]["record"]
        assert scenario["cold_operator"]["next"]
        assert scenario["reference_plan"]


def test_critic_holds_governed_writes_without_approval() -> None:
    catalog = load_catalog(CATALOG)
    scenario = scenario_by_id(catalog, "tier-desk-approve-underdrain")
    state = _state(
        [
            {
                "index": 7,
                "tag": "button",
                "role": "button",
                "name": "Arm task",
                "text": "Arm task",
                "attributes": {"id": "arm-task"},
                "signature": "sig",
            }
        ]
    )
    packet = compile_planner_packet(
        run_id="fixture-run",
        scenario=scenario,
        variant="base",
        state=state,
        step_number=1,
        history=[],
    )
    proposal = validate_proposal(
        {
            "packet_sha256": packet["packet_sha256"],
            "state_id": state["state_id"],
            "actions": [
                {
                    "id": "arm",
                    "surface": "playwright",
                    "op": "click",
                    "effect": "local_write",
                    "intent": "Arm the task",
                    "target": {"id": "arm-task"},
                    "args": {},
                }
            ],
            "done": False,
            "memory": "",
            "next_goal": "",
        },
        packet,
    )
    denied = critic_verdict(
        scenario=scenario,
        packet=packet,
        proposal=proposal,
        approval_available=False,
    )
    assert denied["pass"] is False
    assert any("approval token" in error for error in denied["errors"])
    admitted = critic_verdict(
        scenario=scenario,
        packet=packet,
        proposal=proposal,
        approval_available=True,
    )
    assert admitted["pass"] is True


def test_screen_ghost_packet_is_state_and_screenshot_bound() -> None:
    catalog = load_catalog(CATALOG)
    scenario = scenario_by_id(catalog, "screen-ghost-visual-fallback")
    state = _state([])
    packet = compile_planner_packet(
        run_id="visual-fixture",
        scenario=scenario,
        variant="base",
        state=state,
        step_number=1,
        history=[],
    )
    proposal = validate_proposal(
        {
            "packet_sha256": packet["packet_sha256"],
            "state_id": state["state_id"],
            "actions": [
                {
                    "id": "visual",
                    "surface": "screen_ghost",
                    "op": "tap",
                    "effect": "local_write",
                    "intent": "Tap Sync now",
                    "target": {"visual_id": "sync-now"},
                    "args": {},
                }
            ],
            "done": False,
            "memory": "",
            "next_goal": "",
        },
        packet,
    )
    request = screen_ghost_request(
        scenario=scenario,
        packet=packet,
        action=proposal["actions"][0],
    )
    assert request["state_id"] == state["state_id"]
    assert request["screenshot"]["sha256"] == "2" * 64
    assert request["candidate_contract"]["failure"] == "unsupported_surface"


async def _run_one(
    parent: Path,
    scenario_id: str,
    variant: str,
    *,
    approval_enabled: bool = True,
) -> tuple[dict, Path]:
    catalog = load_catalog(CATALOG)
    runner = TaskComputerRunner(
        catalog=catalog,
        scenario_id=scenario_id,
        variant=variant,
        out_root=parent,
        headless=True,
        trace=False,
        approval_enabled=approval_enabled,
    )
    receipt = await runner.run()
    return receipt, runner.run_dir


def test_optional_project_browser_suite() -> None:
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("  skip  test_optional_project_browser_suite: Playwright unavailable")
        return
    parent = Path(tempfile.mkdtemp(prefix="task-computer-projects-"))
    try:
        catalog = load_catalog(CATALOG)
        cases = [
            (scenario["id"], variant)
            for scenario in catalog["scenarios"]
            for variant in scenario["variants"]
        ]
        assert len(cases) == 9
        results = []
        for scenario_id, variant in cases:
            receipt, run_dir = asyncio.run(_run_one(parent, scenario_id, variant))
            results.append((scenario_id, variant, receipt, run_dir))
            assert receipt["status"] == "ACCEPTED", receipt
            verification = verify_run(run_dir)
            assert verification["ok"], verification
        by_id = {
            (scenario, variant): receipt
            for scenario, variant, receipt, _ in results
        }
        visual = by_id[("screen-ghost-visual-fallback", "base")]
        assert visual["routes"] == {"screen_ghost": 1}
        for variant in ("base", "reordered"):
            chat = by_id[("axm-chat-pull-latest", variant)]
            assert any(
                item["id"] == "download-sync-receipt.json" and item["pass"]
                for item in chat["acceptance"]
            )
        for variant in ("base", "reordered", "dynamic"):
            world = by_id[("axm-world-underdrain-playtest", variant)]
            assert world["cold_operator_expected_answers"]["next"].endswith(
                "municipal underworks."
            )
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_optional_missing_approval_holds_tier_desk() -> None:
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("  skip  test_optional_missing_approval_holds_tier_desk: Playwright unavailable")
        return
    parent = Path(tempfile.mkdtemp(prefix="task-computer-approval-"))
    try:
        receipt, run_dir = asyncio.run(
            _run_one(
                parent,
                "tier-desk-approve-underdrain",
                "base",
                approval_enabled=False,
            )
        )
        assert receipt["status"] == "REJECTED"
        assert "approval token" in str(receipt["error"])
        assert verify_run(run_dir)["ok"] is True
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def main() -> int:
    tests = [
        test_catalog_encodes_project_needs,
        test_critic_holds_governed_writes_without_approval,
        test_screen_ghost_packet_is_state_and_screenshot_bound,
        test_optional_project_browser_suite,
        test_optional_missing_approval_holds_tier_desk,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok  {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} Task Computer tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
