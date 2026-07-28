#!/usr/bin/env python3
"""Content-addressed planner and critic seat tests."""
from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CATALOG = ROOT / "experiments" / "task_computer" / "project_scenarios.json"
AGENT = ROOT / "examples" / "task_computer" / "fixture_team_agent.py"

from tier_runner.playwright_computer_common import atomic_json  # noqa: E402
from tier_runner.task_computer_lab import load_catalog  # noqa: E402
from tier_runner.task_computer_planner import FileExchangePlanner  # noqa: E402
from tier_runner.task_computer_protocol import (  # noqa: E402
    compile_planner_packet,
    scenario_by_id,
)
from tier_runner.task_computer_team import (  # noqa: E402
    FileExchangeCritic,
    TeamedPlanner,
    compile_critic_request,
)
from tier_runner.task_computer_worker import ExchangeWorker  # noqa: E402


def state() -> dict:
    return {
        "state_id": "1" * 64,
        "page_id": "page-fixture",
        "url": "http://127.0.0.1/",
        "title": "Tier Desk queue",
        "tabs": [{"page_id": "page-fixture", "active": True}],
        "elements": [
            {
                "index": 4,
                "tag": "button",
                "role": "button",
                "name": "Review Underdrain task",
                "text": "Review Underdrain task",
                "attributes": {"id": "task-underdrain"},
                "signature": "sig-task",
            }
        ],
        "elements_text": "[4]<button>Review Underdrain task</button>",
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


def test_planner_and_critic_workers_roundtrip() -> None:
    parent = Path(tempfile.mkdtemp(prefix="task-computer-team-"))
    try:
        catalog = load_catalog(CATALOG)
        scenario = scenario_by_id(catalog, "tier-desk-approve-underdrain")
        packet = compile_planner_packet(
            run_id="team-fixture-run",
            scenario=scenario,
            variant="base",
            state=state(),
            step_number=1,
            history=[],
        )
        planner_stem = f"0001-{packet['packet_sha256'][:16]}"
        planner_request = (
            parent
            / packet["run_id"]
            / "planner"
            / "requests"
            / f"{planner_stem}.json"
        )
        atomic_json(planner_request, packet)
        planner_worker = ExchangeWorker(
            exchange_root=parent,
            role="planner",
            command=[sys.executable, str(AGENT)],
            seat_id="gpu.3090-a",
            timeout_seconds=30,
        )
        planner_result = planner_worker.process_once()
        assert planner_result["ok"] is True
        assert len(planner_result["completed"]) == 1
        proposal = FileExchangePlanner(parent, timeout_seconds=1).propose(packet)
        assert proposal["actions"][0]["target"] == {"id": "task-underdrain"}

        critic_request_value = compile_critic_request(packet, proposal)
        critic_stem = f"0001-{critic_request_value['request_sha256'][:16]}"
        critic_request = (
            parent
            / packet["run_id"]
            / "critic"
            / "requests"
            / f"{critic_stem}.json"
        )
        atomic_json(critic_request, critic_request_value)
        critic_worker = ExchangeWorker(
            exchange_root=parent,
            role="critic",
            command=[sys.executable, str(AGENT)],
            seat_id="gpu.3090-b",
            timeout_seconds=30,
        )
        critic_result = critic_worker.process_once()
        assert critic_result["ok"] is True
        assert len(critic_result["completed"]) == 1
        verdict = FileExchangeCritic(parent, timeout_seconds=1).review(packet, proposal)
        assert verdict["pass"] is True
        assert verdict["seat"]["seat_id"] == "gpu.3090-b"
        assert list(parent.rglob("*-gpu.3090-a.json"))
        assert list(parent.rglob("*-gpu.3090-b.json"))
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_teamed_planner_holds_critic_rejection() -> None:
    catalog = load_catalog(CATALOG)
    scenario = scenario_by_id(catalog, "tier-desk-approve-underdrain")
    packet = compile_planner_packet(
        run_id="team-rejection",
        scenario=scenario,
        variant="base",
        state=state(),
        step_number=1,
        history=[],
    )

    class Planner:
        def propose(self, value: dict) -> dict:
            return {
                "packet_sha256": value["packet_sha256"],
                "state_id": value["state"]["state_id"],
                "actions": [
                    {
                        "id": "open",
                        "surface": "playwright",
                        "op": "click",
                        "effect": "read",
                        "intent": "Open the task",
                        "target": {"id": "task-underdrain"},
                        "args": {},
                    }
                ],
                "done": False,
                "memory": "",
                "next_goal": "Open the task",
            }

    class Critic:
        def review(self, value: dict, proposal: dict) -> dict:
            return {
                "pass": False,
                "errors": ["independent critic found a contradiction"],
                "warnings": [],
                "rationale": "hold",
            }

    try:
        TeamedPlanner(Planner(), Critic()).propose(packet)
    except Exception as exc:
        assert "independent critic rejected" in str(exc)
    else:
        raise AssertionError("critic rejection must hold the planner proposal")


def main() -> int:
    tests = [
        test_planner_and_critic_workers_roundtrip,
        test_teamed_planner_holds_critic_rejection,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok  {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} Task Computer team tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
