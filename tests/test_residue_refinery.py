#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tier_runner.desk import DeskScheduler, DeskStore, ExecutionResult  # noqa: E402


class RouteExecutor:
    def __init__(self, outcomes: dict[str, list[str]], delay: float = 0.01):
        self.outcomes = {key: list(value) for key, value in outcomes.items()}
        self.delay = delay
        self.order: list[str] = []
        self.arms: list[str] = []
        self.lock = threading.Lock()

    def run(self, task: dict, run: dict) -> ExecutionResult:
        with self.lock:
            self.order.append(task["id"])
            self.arms.append(task["arm"])
            queue = self.outcomes.get(task["arm"], ["ACCEPTED"])
            state = queue.pop(0) if queue else "ACCEPTED"
        time.sleep(self.delay)
        output = Path(run["output_dir"])
        output.mkdir(parents=True, exist_ok=True)
        receipt = {"schema": "tier-bench/tier-run-receipt@1", "state": state}
        receipt_path = output / "receipt.json"
        receipt_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
        if state == "ACCEPTED":
            (output / "change.patch").write_text("diff --git a/app.py b/app.py\n", encoding="utf-8")
        return ExecutionResult(
            state=state,
            receipt=receipt,
            verification={"ok": state != "ERROR", "errors": []},
            receipt_path=str(receipt_path),
            cost_usd=0.0 if task["arm"] == "arm_a" else 0.05,
            input_tokens=100,
            output_tokens=25,
            exit_code=0 if state == "ACCEPTED" else 1,
            error=None if state == "ACCEPTED" else f"fixture {state.lower()}",
        )

    def cancel(self, run_id: str) -> bool:  # noqa: ARG002
        return True


def repo(parent: Path) -> Path:
    path = parent / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "residue-refinery@example.invalid"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Residue Refinery Test"], cwd=path, check=True
    )
    manifest = {
        "schema": "tier-bench/pilot-backends@1",
        "arms": {
            "arm_a": {"model_id": "local-fixture", "surface": "local"},
            "arm_b": {"model_id": "open-fixture", "surface": "api"},
            "arm_c": {"model_id": "closed-fixture", "surface": "subscription"},
        },
    }
    (path / "pilot_backends.json").write_text(json.dumps(manifest), encoding="utf-8")
    (path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "freeze fixture"], cwd=path, check=True)
    return path


def plan(*, mode: str = "local_first", k: int = 1, max_trials: int | None = None,
         max_cost: float | None = None) -> dict:
    policy: dict[str, object] = {"materialize_candidates": True}
    if max_cost is not None:
        policy["max_total_cost_usd"] = max_cost
    return {
        "schema": "tier-bench/frontier-residue-campaign@1",
        "id": "fixture-campaign",
        "title": "Fixture campaign",
        "mode": mode,
        "k": k,
        "max_trials_per_route": max_trials or max(3 * k, k + 2),
        "queue_now": True,
        "task": {
            "task": "Fix the bounded fixture defect.",
            "files": ["app.py"],
            "acceptance": "python -m py_compile app.py",
            "priority": 70,
        },
        "policy": policy,
        "routes": [
            {
                "id": "local",
                "label": "Local cartridge",
                "manifest": "pilot_backends.json",
                "arm": "arm_a",
                "execution_class": "local",
                "source_access": "source_and_weights",
                "capability_basis": "measured",
                "estimated_max_cost_usd": 0,
            },
            {
                "id": "open",
                "label": "Open-weight frontier",
                "manifest": "pilot_backends.json",
                "arm": "arm_b",
                "execution_class": "remote_open_weight",
                "source_access": "weights",
                "capability_basis": "hypothesis",
                "estimated_max_cost_usd": 0.20,
            },
            {
                "id": "closed",
                "label": "Closed frontier",
                "manifest": "pilot_backends.json",
                "arm": "arm_c",
                "execution_class": "remote_closed",
                "source_access": "subscription_only",
                "capability_basis": "unmeasured",
                "estimated_max_cost_usd": 0.50,
            },
        ],
    }


def wait_campaign(store: DeskStore, expected: str, timeout: float = 6) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        campaign = store.get_campaign("fixture-campaign")
        if campaign and campaign["state"] == expected:
            return campaign
        time.sleep(0.02)
    raise AssertionError(
        f"campaign did not reach {expected}: {store.get_campaign('fixture-campaign')}"
    )


def test_local_clear_avoids_frontier(parent: Path) -> None:
    root = repo(parent)
    store = DeskStore(parent / "state" / "desk.sqlite3", root)
    executor = RouteExecutor({"arm_a": ["ACCEPTED"]})
    scheduler = DeskScheduler(store, root, parent / "state", executor)
    store.create_campaign(plan())
    scheduler.start()
    try:
        campaign = wait_campaign(store, "CLEARED")
        assert executor.arms == ["arm_a"]
        assert campaign["result"]["remote_routes_not_called"] == 2
        assert campaign["result"]["remote_trials"] == 0
        assert store.list_residue_candidates() == []
    finally:
        scheduler.stop()


def test_k_wall_earns_frontier_and_candidate(parent: Path) -> None:
    root = repo(parent)
    store = DeskStore(parent / "state" / "desk.sqlite3", root)
    executor = RouteExecutor(
        {"arm_a": ["REJECTED", "REJECTED"], "arm_b": ["ACCEPTED", "ACCEPTED"]}
    )
    scheduler = DeskScheduler(store, root, parent / "state", executor)
    store.create_campaign(plan(k=2))
    scheduler.start()
    try:
        campaign = wait_campaign(store, "CLEARED")
        assert executor.arms == ["arm_a", "arm_a", "arm_b", "arm_b"]
        assert store.settings()["paused"] is False
        assert campaign["result"]["winner"]["route_id"] == "open"
        candidates = store.list_residue_candidates()
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate["kind"] == "capability_residue"
        assert candidate["evidence"]["k"] == 2
        assert candidate["evidence"]["capture_plan"]["mode"] == "mechanistic"
        assert Path(candidate["projection_path"]).is_file()
        assert Path(campaign["projection_path"]).is_file()
    finally:
        scheduler.stop()


def test_errors_do_not_buy_frontier_escalation(parent: Path) -> None:
    root = repo(parent)
    store = DeskStore(parent / "state" / "desk.sqlite3", root)
    executor = RouteExecutor({"arm_a": ["ERROR", "ERROR"]})
    scheduler = DeskScheduler(store, root, parent / "state", executor)
    store.create_campaign(plan(k=2, max_trials=2))
    scheduler.start()
    try:
        campaign = wait_campaign(store, "INCONCLUSIVE")
        assert executor.arms == ["arm_a", "arm_a"]
        assert store.settings()["paused"] is False
        assert campaign["routes"][0]["state"] == "inconclusive"
        assert campaign["result"]["remote_trials"] == 0
    finally:
        scheduler.stop()


def test_survey_runs_every_preregistered_route(parent: Path) -> None:
    root = repo(parent)
    store = DeskStore(parent / "state" / "desk.sqlite3", root)
    executor = RouteExecutor(
        {"arm_a": ["ACCEPTED"], "arm_b": ["REJECTED"], "arm_c": ["ACCEPTED"]}
    )
    scheduler = DeskScheduler(store, root, parent / "state", executor)
    store.create_campaign(plan(mode="survey"))
    scheduler.start()
    try:
        campaign = wait_campaign(store, "COMPLETED")
        assert executor.arms == ["arm_a", "arm_b", "arm_c"]
        assert campaign["result"]["winner"]["route_id"] == "local"
        assert store.list_residue_candidates() == []
    finally:
        scheduler.stop()


def test_campaign_budget_blocks_unknown_or_expensive_next_route(parent: Path) -> None:
    root = repo(parent)
    store = DeskStore(parent / "state" / "desk.sqlite3", root)
    executor = RouteExecutor({"arm_a": ["REJECTED"]})
    scheduler = DeskScheduler(store, root, parent / "state", executor)
    store.create_campaign(plan(max_cost=0.10))
    scheduler.start()
    try:
        campaign = wait_campaign(store, "BUDGET_BLOCKED")
        assert executor.arms == ["arm_a"]
        assert "cost cap" in campaign["result"]["reason"]
    finally:
        scheduler.stop()


def test_campaign_trial_refuses_manual_retry(parent: Path) -> None:
    root = repo(parent)
    store = DeskStore(parent / "state" / "desk.sqlite3", root)
    store.create_campaign(plan())
    queued = store.ready(1)
    assert len(queued) == 1
    claimed = store.claim(
        queued[0]["id"],
        root / ".git" / "tier-runs" / "monster-wrangler",
        parent / "state" / "logs",
    )
    assert claimed is not None
    _, run = claimed
    store.complete(
        run["id"],
        ExecutionResult(
            "REJECTED",
            receipt={"schema": "tier-bench/tier-run-receipt@1", "state": "REJECTED"},
            verification={"ok": True, "errors": []},
        ),
    )
    try:
        store.transition(queued[0]["id"], "retry")
    except Exception as exc:
        assert "campaign-managed" in str(exc)
    else:
        raise AssertionError("manual retry must not rewrite a campaign evidence sequence")


def main() -> int:
    parent = Path(tempfile.mkdtemp(prefix="residue-refinery-"))
    tests = [
        test_local_clear_avoids_frontier,
        test_k_wall_earns_frontier_and_candidate,
        test_errors_do_not_buy_frontier_escalation,
        test_survey_runs_every_preregistered_route,
        test_campaign_budget_blocks_unknown_or_expensive_next_route,
        test_campaign_trial_refuses_manual_retry,
    ]
    try:
        for index, test in enumerate(tests):
            case = parent / f"case-{index}"
            case.mkdir()
            test(case)
        print(f"OK - {len(tests)}/{len(tests)} residue-refinery tests passed; zero model calls")
        return 0
    finally:
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
