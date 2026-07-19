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
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tier_runner.cli import _parser as tier_parser, _run_inputs  # noqa: E402
from tier_runner.desk import (  # noqa: E402
    DeskApplication,
    DeskError,
    DeskScheduler,
    DeskServer,
    DeskStore,
    ExecutionResult,
)


class FakeExecutor:
    def __init__(self, outcomes: dict[str, str] | None = None, delay: float = 0.02):
        self.outcomes = outcomes or {}
        self.delay = delay
        self.order: list[str] = []
        self.canceled: list[str] = []

    def run(self, task: dict, run: dict) -> ExecutionResult:
        self.order.append(task["id"])
        time.sleep(self.delay)
        state = self.outcomes.get(task["id"], "ACCEPTED")
        return ExecutionResult(
            state=state,
            receipt={"schema": "tier-bench/tier-run-receipt@1", "state": state},
            verification={"ok": state != "ERROR", "errors": []},
            receipt_path=str(Path(run["output_dir"]) / "receipt.json"),
            cost_usd=0.05,
            input_tokens=100,
            output_tokens=25,
            exit_code=0 if state == "ACCEPTED" else 1,
            error=None if state == "ACCEPTED" else f"fixture {state.lower()}",
        )

    def cancel(self, run_id: str) -> bool:
        self.canceled.append(run_id)
        return True


def repo(parent: Path) -> Path:
    path = parent / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "pilot_backends.json").write_text(
        json.dumps({"schema": "tier-bench/pilot-backends@1", "arms": {"arm_b": {}}}),
        encoding="utf-8",
    )
    return path


def task(task_id: str, **patch) -> dict:
    value = {
        "id": task_id,
        "title": f"Task {task_id}",
        "task": "Change only the declared file and preserve all other behavior.",
        "files": ["app.py"],
        "acceptance": "python -m pytest -q",
        "manifest": "pilot_backends.json",
        "arm": "arm_b",
        "priority": 50,
        "queue_now": True,
        "approval_required": False,
    }
    value.update(patch)
    return value


def wait_for(store: DeskStore, task_id: str, expected: str, timeout: float = 4) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = store.get_task(task_id)
        if value and value["state"] == expected:
            return value
        time.sleep(0.02)
    raise AssertionError(f"{task_id} did not reach {expected}: {store.get_task(task_id)}")


def test_validation(parent: Path) -> None:
    root = repo(parent)
    store = DeskStore(parent / "state" / "desk.sqlite3", root)
    created = store.create_task(task("safe", files="app.py\ntests/"))
    assert created["files"] == ["app.py", "tests/"]
    try:
        store.create_task(task("escape", files=["../secret.txt"]))
    except DeskError as exc:
        assert "unsafe repository scope" in str(exc)
    else:
        raise AssertionError("scope escape should fail")
    try:
        store.create_task(task("missing", manifest="missing.json"))
    except DeskError as exc:
        assert "does not exist" in str(exc)
    else:
        raise AssertionError("missing manifest should fail")
    try:
        store.create_task(task("missing-arm", arm="arm_c"))
    except DeskError as exc:
        assert "does not define arm_c" in str(exc)
    else:
        raise AssertionError("an unavailable cartridge arm should fail")


def test_claim_paths(parent: Path) -> None:
    root = repo(parent)
    store = DeskStore(parent / "state" / "desk.sqlite3", root)
    store.create_task(task("paths"))
    claimed = store.claim("paths", root / ".git" / "tier-runs" / "monster-wrangler", parent / "logs")
    assert claimed is not None
    _, run = claimed
    assert not Path(run["output_dir"]).exists()
    assert Path(run["log_path"]).parent.is_dir()
    assert "tier-runs" in Path(run["output_dir"]).parts


def test_run_envelope(parent: Path) -> None:
    root = repo(parent)
    envelope = parent / "run.json"
    envelope.write_text(json.dumps({
        "schema": "tier-bench/tier-run-envelope@1",
        "repo": str(root),
        "task_id": "enveloped",
        "task": "change app.py",
        "files": ["app.py"],
        "acceptance": "python -m pytest -q",
        "manifest": "pilot_backends.json",
        "arm": "arm_b",
        "output_dir": str(root / ".git" / "tier-runs" / "enveloped"),
    }), encoding="utf-8")
    args = tier_parser().parse_args(["run", "--envelope", str(envelope)])
    values = _run_inputs(args)
    assert values["task_id"] == "enveloped"
    assert values["manifest"] == root / "pilot_backends.json"
    try:
        mixed = tier_parser().parse_args([
            "run", "--envelope", str(envelope), "--task", "contradiction"
        ])
        _run_inputs(mixed)
    except Exception as exc:
        assert "cannot be combined" in str(exc)
    else:
        raise AssertionError("envelope and direct inputs must fail closed")


def test_worker_refuses_stale_heartbeat(parent: Path) -> None:
    envelope = parent / "unused.json"
    envelope.write_text("{}\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tier_runner.desk_worker",
            "--envelope",
            str(envelope),
            "--heartbeat",
            str(parent / "missing-heartbeat"),
            "--heartbeat-timeout",
            "5",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "heartbeat is absent or stale" in result.stderr


def test_dag_order(parent: Path) -> None:
    root = repo(parent)
    store = DeskStore(parent / "state" / "desk.sqlite3", root)
    executor = FakeExecutor()
    scheduler = DeskScheduler(store, root, parent / "state", executor)
    store.create_task(task("parent"))
    child = store.create_task(task("child", depends_on=["parent"]))
    assert child["blocked_by"][0]["id"] == "parent"
    scheduler.start()
    try:
        wait_for(store, "child", "ACCEPTED")
        assert executor.order == ["parent", "child"]
    finally:
        scheduler.stop()


def test_failure_pauses(parent: Path) -> None:
    root = repo(parent)
    store = DeskStore(parent / "state" / "desk.sqlite3", root)
    executor = FakeExecutor({"bad": "REJECTED"})
    scheduler = DeskScheduler(store, root, parent / "state", executor)
    store.create_task(task("bad", priority=100))
    store.create_task(task("after", priority=1))
    scheduler.start()
    try:
        wait_for(store, "bad", "REJECTED")
        deadline = time.time() + 2
        while time.time() < deadline and not store.settings()["paused"]:
            time.sleep(0.02)
        assert store.settings()["paused"] is True
        assert store.get_task("after")["state"] == "QUEUED"
        assert executor.order == ["bad"]
    finally:
        scheduler.stop()


def test_daily_limit(parent: Path) -> None:
    root = repo(parent)
    store = DeskStore(parent / "state" / "desk.sqlite3", root)
    store.update_settings({"daily_task_limit": 1, "stop_on_failure": False, "max_workers": 4})
    executor = FakeExecutor()
    scheduler = DeskScheduler(store, root, parent / "state", executor)
    store.create_task(task("first", priority=100))
    store.create_task(task("second", priority=1))
    scheduler.start()
    try:
        wait_for(store, "first", "ACCEPTED")
        deadline = time.time() + 2
        while time.time() < deadline and not store.settings()["paused"]:
            time.sleep(0.02)
        assert "daily task limit" in store.settings()["pause_reason"]
        assert store.get_task("second")["state"] == "QUEUED"
    finally:
        scheduler.stop()


def request(url: str, method: str = "GET", body: dict | None = None, token: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if token:
        headers["X-Tier-Desk-Token"] = token
    with urlopen(Request(url, data=data, method=method, headers=headers), timeout=3) as response:
        return response.status, json.loads(response.read())


def test_http_token(parent: Path) -> None:
    root = repo(parent)
    app = DeskApplication(root, parent / "state", FakeExecutor(delay=0.2))
    app.store.pause("test holds queue")
    server = DeskServer(("127.0.0.1", 0), app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    app.start()
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, state = request(base + "/api/state")
        assert status == 200 and state["ok"] is True
        try:
            request(base + "/api/tasks", "POST", task("api"))
        except HTTPError as exc:
            assert exc.code == 403
        else:
            raise AssertionError("tokenless mutation should fail")
        status, created = request(base + "/api/tasks", "POST", task("api"), app.token)
        assert status == 201 and created["task"]["id"] == "api"
        status, check = request(base + "/healthz")
        assert status == 200 and check["instance_id"] == app.instance_id
        status, stopped = request(base + "/api/control/shutdown", "POST", {}, app.token)
        assert status == 200 and stopped["shutting_down"] is True
    finally:
        server.shutdown()
        server.server_close()
        app.stop()
        thread.join(timeout=2)


def main() -> int:
    parent = Path(tempfile.mkdtemp(prefix="tier-desk-"))
    tests = [
        test_validation,
        test_claim_paths,
        test_run_envelope,
        test_worker_refuses_stale_heartbeat,
        test_dag_order,
        test_failure_pauses,
        test_daily_limit,
        test_http_token,
    ]
    try:
        for index, test in enumerate(tests):
            case = parent / f"case-{index}"
            case.mkdir()
            test(case)
        print(f"OK - {len(tests)}/{len(tests)} Monster Wrangler tests passed; zero model calls")
        return 0
    finally:
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
