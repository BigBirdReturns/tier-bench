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


class LaneExecutor:
    def __init__(self, delay: float = 0.08):
        self.delay = delay
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.order: list[str] = []

    def run(self, task: dict, run: dict) -> ExecutionResult:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.order.append(task["id"])
        try:
            time.sleep(self.delay)
            output = Path(run["output_dir"])
            output.mkdir(parents=True, exist_ok=True)
            receipt = {"schema": "tier-bench/tier-run-receipt@1", "state": "ACCEPTED"}
            receipt_path = output / "receipt.json"
            receipt_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
            return ExecutionResult(
                state="ACCEPTED",
                receipt=receipt,
                verification={"ok": True, "errors": []},
                receipt_path=str(receipt_path),
                cost_usd=0,
                input_tokens=100,
                output_tokens=25,
                exit_code=0,
            )
        finally:
            with self.lock:
                self.active -= 1

    def cancel(self, run_id: str) -> bool:  # noqa: ARG002
        return True


def repo(parent: Path) -> Path:
    path = parent / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "resource-lane@example.invalid"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Resource Lane Test"], cwd=path, check=True
    )
    manifest = {
        "schema": "tier-bench/pilot-backends@1",
        "arms": {"arm_a": {"model_id": "local-fixture", "surface": "local"}},
    }
    (path / "pilot_backends.json").write_text(json.dumps(manifest), encoding="utf-8")
    (path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "freeze fixture"], cwd=path, check=True)
    return path


def plan(campaign_id: str, resource_key: str) -> dict:
    return {
        "schema": "tier-bench/frontier-residue-campaign@1",
        "id": campaign_id,
        "title": f"Campaign {campaign_id}",
        "mode": "local_first",
        "k": 1,
        "queue_now": True,
        "task": {
            "task": "Run the bounded local fixture.",
            "files": ["app.py"],
            "acceptance": "python -m py_compile app.py",
            "priority": 70,
        },
        "routes": [
            {
                "id": "local",
                "label": "Shared local GPU",
                "manifest": "pilot_backends.json",
                "arm": "arm_a",
                "execution_class": "local",
                "source_access": "source_and_weights",
                "capability_basis": "measured",
                "estimated_max_cost_usd": 0,
                "resource_key": resource_key,
                "max_concurrency": 1,
            }
        ],
    }


def wait(store: DeskStore, campaign_id: str, timeout: float = 6) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        campaign = store.get_campaign(campaign_id)
        if campaign and campaign["state"] == "CLEARED":
            return campaign
        time.sleep(0.02)
    raise AssertionError(f"campaign did not clear: {store.get_campaign(campaign_id)}")


def test_shared_gpu_lane_serializes_campaigns(parent: Path) -> None:
    root = repo(parent)
    store = DeskStore(parent / "state" / "desk.sqlite3", root)
    store.update_settings({"max_workers": 2, "stop_on_failure": False})
    executor = LaneExecutor()
    scheduler = DeskScheduler(store, root, parent / "state", executor)
    store.create_campaign(plan("fixture-a", "gpu:3090"))
    store.create_campaign(plan("fixture-b", "gpu:3090"))
    scheduler.start()
    try:
        first = wait(store, "fixture-a")
        second = wait(store, "fixture-b")
        assert executor.max_active == 1
        assert len(executor.order) == 2
        assert first["routes"][0]["resource_key"] == "gpu:3090"
        assert second["routes"][0]["max_concurrency"] == 1
    finally:
        scheduler.stop()


def test_independent_lanes_are_admitted_together(parent: Path) -> None:
    root = repo(parent)
    store = DeskStore(parent / "state" / "desk.sqlite3", root)
    store.create_campaign(plan("fixture-3090", "gpu:3090"))
    store.create_campaign(plan("fixture-4060", "gpu:4060"))
    ready = store.ready(2)
    assert len(ready) == 2
    assert {task["id"] for task in ready} == {
        store.campaign_active_task("fixture-3090"),
        store.campaign_active_task("fixture-4060"),
    }


def test_queue_now_rejects_truthy_strings(parent: Path) -> None:
    root = repo(parent)
    store = DeskStore(parent / "state" / "desk.sqlite3", root)
    invalid = plan("fixture-invalid", "gpu:3090")
    invalid["queue_now"] = "false"
    try:
        store.create_campaign(invalid)
    except Exception as exc:
        assert "queue_now must be boolean" in str(exc)
    else:
        raise AssertionError("a truthy string must not silently activate a campaign")
    assert store.get_campaign("fixture-invalid") is None


def main() -> int:
    parent = Path(tempfile.mkdtemp(prefix="residue-resource-"))
    tests = [
        test_shared_gpu_lane_serializes_campaigns,
        test_independent_lanes_are_admitted_together,
        test_queue_now_rejects_truthy_strings,
    ]
    try:
        for index, test in enumerate(tests):
            case = parent / f"case-{index}"
            case.mkdir()
            test(case)
        print(f"OK - {len(tests)}/{len(tests)} resource-lane tests passed; zero model calls")
        return 0
    finally:
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
