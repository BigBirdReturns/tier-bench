#!/usr/bin/env python3
from __future__ import annotations

import json
import os
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
    pid_alive,
)
from tier_runner.desk_sources import parse_claude_usage, read_estate  # noqa: E402
import tier_runner.desk_sources as desk_sources  # noqa: E402
import tier_runner.desk_http as desk_http  # noqa: E402
import tier_runner.desk_runtime as desk_runtime  # noqa: E402
import tier_runner.desk_worker as desk_worker  # noqa: E402
from tier_runner.desk_intake import plan_intent  # noqa: E402
from tier_runner.desk_ui import HTML  # noqa: E402


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


class BlockingExecutor:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.canceled: list[str] = []

    def run(self, task: dict, run: dict) -> ExecutionResult:
        self.started.set()
        assert self.release.wait(3), task
        return ExecutionResult(
            state="ACCEPTED",
            receipt={"schema": "tier-bench/tier-run-receipt@1", "state": "ACCEPTED"},
            verification={"ok": True, "errors": []},
            receipt_path=str(Path(run["output_dir"]) / "receipt.json"),
            cost_usd=0.05,
            input_tokens=100,
            output_tokens=25,
            exit_code=0,
        )

    def cancel(self, run_id: str) -> bool:
        self.canceled.append(run_id)
        self.release.set()
        return True


class FakeSources:
    def __init__(self):
        self.forced = 0

    def snapshot(self, force: bool = False) -> dict:
        self.forced += int(force)
        return {
            "observed_at": "2026-07-19T00:00:00Z",
            "gauges": {"claude": {"status": "pass"}, "codex": {"status": "pass"}},
            "estate": {"status": "pass", "projects": []},
        }


def repo(parent: Path) -> Path:
    path = parent / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "monster-wrangler@example.invalid"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Monster Wrangler Test"],
        cwd=path,
        check=True,
    )
    (path / "pilot_backends.json").write_text(
        json.dumps(
            {
                "schema": "tier-bench/pilot-backends@1",
                "arms": {"arm_b": {}, "benchmark_local": {}},
            }
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "pilot_backends.json"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "freeze fixture manifest"], cwd=path, check=True)
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
    benchmark = store.create_task(task("benchmark", arm="benchmark_local"))
    assert benchmark["arm"] == "benchmark_local"
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


def test_pid_liveness_is_truthful(parent: Path) -> None:  # noqa: ARG001
    assert pid_alive(os.getpid()) is True
    assert pid_alive(2_000_000_000) is False


def test_state_transitions_fail_closed(parent: Path) -> None:
    root = repo(parent)
    store = DeskStore(parent / "state" / "desk.sqlite3", root)
    store.create_task(task("draft", queue_now=False))
    store.transition("draft", "arm")
    try:
        store.transition("draft", "arm")
    except DeskError as exc:
        assert "only a draft" in str(exc)
    else:
        raise AssertionError("an armed task must not be armed twice")
    store.transition("draft", "hold")
    try:
        store.transition("draft", "retry")
    except DeskError as exc:
        assert "only a failed" in str(exc)
    else:
        raise AssertionError("a draft task must not be retried")


def test_claim_paths(parent: Path) -> None:
    root = repo(parent)
    store = DeskStore(parent / "state" / "desk.sqlite3", root)
    store.create_task(task("paths"))
    claimed = store.claim(
        "paths", root / ".git" / "tier-runs" / "monster-wrangler", parent / "logs"
    )
    assert claimed is not None
    _, run = claimed
    assert not Path(run["output_dir"]).exists()
    assert Path(run["log_path"]).parent.is_dir()
    assert "tier-runs" in Path(run["output_dir"]).parts


def test_run_envelope(parent: Path) -> None:
    root = repo(parent)
    envelope = parent / "run.json"
    envelope.write_text(
        json.dumps(
            {
                "schema": "tier-bench/tier-run-envelope@1",
                "repo": str(root),
                "task_id": "enveloped",
                "task": "change app.py",
                "files": ["app.py"],
                "acceptance": "python -m pytest -q",
                "manifest": "pilot_backends.json",
                "arm": "arm_b",
                "output_dir": str(root / ".git" / "tier-runs" / "enveloped"),
            }
        ),
        encoding="utf-8",
    )
    args = tier_parser().parse_args(["run", "--envelope", str(envelope)])
    values = _run_inputs(args)
    assert values["task_id"] == "enveloped"
    assert values["manifest"] == root / "pilot_backends.json"
    try:
        mixed = tier_parser().parse_args(
            ["run", "--envelope", str(envelope), "--task", "contradiction"]
        )
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
            "--heartbeat-instance",
            "expected-instance",
            "--heartbeat-timeout",
            "5",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "heartbeat is absent, stale, or owned by another instance" in result.stderr
    heartbeat = parent / "owned-by-old-desk"
    heartbeat.write_text("old-instance 2026-07-19T00:00:00Z\n", encoding="utf-8")
    wrong_owner = subprocess.run(
        [
            sys.executable,
            "-m",
            "tier_runner.desk_worker",
            "--envelope",
            str(envelope),
            "--heartbeat",
            str(heartbeat),
            "--heartbeat-instance",
            "new-instance",
            "--heartbeat-timeout",
            "5",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert wrong_owner.returncode == 2
    assert "owned by another instance" in wrong_owner.stderr


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


def test_cancel_cannot_be_overwritten_by_late_success(parent: Path) -> None:
    root = repo(parent)
    store = DeskStore(parent / "state" / "desk.sqlite3", root)
    executor = BlockingExecutor()
    scheduler = DeskScheduler(store, root, parent / "state", executor)
    store.create_task(task("cancel-race"))
    scheduler.start()
    try:
        assert executor.started.wait(2)
        scheduler.cancel_task("cancel-race")
        canceled = wait_for(store, "cancel-race", "CANCELED")
        run = canceled["runs"][0]
        assert run["state"] == "CANCELED"
        time.sleep(0.1)
        assert store.get_task("cancel-race")["state"] == "CANCELED"
        assert executor.canceled == [run["id"]]
    finally:
        executor.release.set()
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


def test_success_denominator_excludes_infrastructure_errors(parent: Path) -> None:
    root = repo(parent)
    store = DeskStore(parent / "state" / "desk.sqlite3", root)
    runs = root / ".git" / "tier-runs" / "monster-wrangler"
    logs = parent / "logs"
    for task_id, state in (("yes", "ACCEPTED"), ("no", "REJECTED"), ("infra", "ERROR")):
        store.create_task(task(task_id))
        claimed = store.claim(task_id, runs, logs)
        assert claimed is not None
        _, run = claimed
        assert store.complete(
            run["id"],
            ExecutionResult(
                state,
                cost_usd=0.01,
                error="transport" if state == "ERROR" else None,
            ),
        )
    assert store.stats()["success_rate"] == 0.5


def test_claude_usage_parser(parent: Path) -> None:  # noqa: ARG001
    sample = """Current session: 29% used · resets Jul 19, 6:30pm (America/Los_Angeles)
Current week (all models): 99% used · resets Jul 19, 6pm
Current week (Fable): 71% used - resets Jul 25, 6pm
Broken: 101% used · resets never
"""
    assert parse_claude_usage(sample) == [
        {"label": "Current session", "used_percent": 29, "resets": "Jul 19, 6:30pm (America/Los_Angeles)"},
        {"label": "Current week (all models)", "used_percent": 99, "resets": "Jul 19, 6pm"},
        {"label": "Current week (Fable)", "used_percent": 71, "resets": "Jul 25, 6pm"},
    ]


def test_estate_reads_git_and_open_queue(parent: Path) -> None:
    root = repo(parent)
    queue_path = root / "docs" / "agents" / "QUEUE.md"
    queue_path.parent.mkdir(parents=True)
    queue_path.write_text(
        "| ID | Work item | Owner | Status |\n| --- | --- | --- | --- |\n"
        "| `OPEN-1` | Ship the dashboard | desk | **claimed** |\n"
        "| `DONE-1` | Old work | desk | **done** |\n",
        encoding="utf-8",
    )
    (root / "loose.txt").write_text("dirty\n", encoding="utf-8")
    estate = read_estate(root, [parent])
    assert estate["status"] == "pass"
    assert len(estate["projects"]) == 1
    project = estate["projects"][0]
    assert project["open_count"] == 1
    assert project["open_items"][0]["id"] == "OPEN-1"
    assert project["dirty_count"] >= 2
    assert project["head_sha"]


def test_queue_uses_named_state_column(parent: Path) -> None:
    root = repo(parent)
    queue_path = root / "docs" / "agents" / "QUEUE.md"
    queue_path.parent.mkdir(parents=True)
    queue_path.write_text(
        "| id | task | owner | lane | state | evidence when done | note |\n"
        "|---|---|---|---|---|---|---|\n"
        "| `OPEN-1` | First | sol | driver | **claimed — now** | — | note is not state |\n"
        "| `BLOCK-1` | Second | terra | audit | blocked — input | — | arbitrary note |\n"
        "| `DONE-1` | Third | sol | driver | **done** | receipt | claimed in old prose |\n"
        "| `SAME-1` | Fourth | sol | driver | **claimed+done — same session** | receipt | — |\n",
        encoding="utf-8",
    )
    project = read_estate(root, [parent])["projects"][0]
    assert [item["id"] for item in project["open_items"]] == ["OPEN-1", "BLOCK-1"]
    assert project["open_items"][0]["state"] == "claimed — now"


def test_dashboard_ui_contract(parent: Path) -> None:  # noqa: ARG001
    assert "<title>Tier Desk</title>" in HTML
    assert 'id="pageDashboard"' in HTML
    assert 'id="themeBtn"' in HTML
    assert "tier-desk-theme" in HTML
    assert ':root[data-theme="light"]' in HTML
    assert "/api/dashboard" in HTML
    assert "setInterval(()=>loadDashboard()" not in HTML


def test_intent_first_work_entry(parent: Path) -> None:
    root = repo(parent)
    (root / "tests").mkdir()
    (root / "tests" / "test_tier_desk.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / ".claude").mkdir()
    (root / ".claude" / "rules.md").write_text("controller only\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("controller only\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "tests/test_tier_desk.py", "src/app.py", ".claude/rules.md", "AGENTS.md"],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "commit", "-q", "-m", "add intake fixture"], cwd=root, check=True)
    plan = plan_intent(
        root,
        {"intent": "Make starting useful work simple. Keep the custody boundary visible."},
    )
    assert plan["title"] == "Make starting useful work simple"
    assert plan["acceptance"] == "python -B tests/test_tier_desk.py"
    assert plan["files"] == ["src/", "tests/"]
    assert plan["arm"] == "arm_b"
    assert "committed top-level code areas" in plan["why"]["scope"]
    exact = plan_intent(
        root,
        {
            "intent": (
                "In src/app.py, add one concise comment and preserve the rest "
                "of the file."
            )
        },
    )
    assert exact["files"] == ["src/app.py"]
    assert "tier_runner.intent_acceptance insertion" in exact["acceptance"]
    assert "recognized 1 committed files" in exact["why"]["scope"]
    assert 'id="intent"' in HTML
    assert "Prepare this work" in HTML
    assert "Start guarded work" in HTML
    assert "Change technical details" in HTML
    assert "<label>Cartridge" not in HTML
    assert 'id="title" maxlength="160" required' not in HTML
    assert 'id="files" required' not in HTML
    assert 'id="acceptance" required' not in HTML
    assert "/api/intake/plan" in HTML

    benchmark = plan_intent(
        root,
        {"intent": "run 10 benchmarks that teach us the costs of this system as is"},
    )
    assert benchmark["arm"] == "benchmark_local"
    assert benchmark["files"] == ["data/"]
    assert "--expected-count 10" in benchmark["acceptance"]
    assert "tests/test_tier_desk.py" not in benchmark["acceptance"]
    assert "Receipt integrity" in HTML


def test_observer_processes_are_hidden_and_cached(parent: Path) -> None:
    assert desk_sources.hidden_process_kwargs("nt") == {
        "creationflags": subprocess.CREATE_NO_WINDOW
    }
    assert desk_sources.hidden_process_kwargs("posix") == {}
    expected_group = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    assert desk_sources.hidden_process_kwargs("nt", new_process_group=True) == {
        "creationflags": expected_group
    }
    assert desk_runtime.TierRunExecutor._process_kwargs() == {
        "creationflags": expected_group
    }
    assert desk_worker._child_kwargs() == {"creationflags": expected_group}
    calls = {"claude": 0, "codex": 0, "estate": 0}
    originals = (
        desk_sources.read_claude_usage,
        desk_sources.read_codex_usage,
        desk_sources.read_estate,
    )

    def claude(path: Path) -> dict:  # noqa: ARG001
        calls["claude"] += 1
        return {"status": "pass", "windows": []}

    def codex() -> dict:
        calls["codex"] += 1
        return {"status": "pass", "windows": []}

    def estate(path: Path, roots=None, stop_event=None) -> dict:  # noqa: ARG001
        calls["estate"] += 1
        return {"status": "pass", "projects": [], "max_parallel_processes": 1}

    desk_sources.read_claude_usage = claude
    desk_sources.read_codex_usage = codex
    desk_sources.read_estate = estate
    try:
        sources = desk_sources.DeskSources(parent, gauge_ttl=999, estate_ttl=999)
        first = sources.snapshot()
        second = sources.snapshot()
        assert first["estate"]["max_parallel_processes"] == 1
        assert second == first or second["gauges"] == first["gauges"]
        assert calls == {"claude": 1, "codex": 1, "estate": 1}
        sources.snapshot(force=True)
        assert calls == {"claude": 2, "codex": 2, "estate": 2}
        sources.stop()
        assert sources.stop_event.is_set()
    finally:
        (
            desk_sources.read_claude_usage,
            desk_sources.read_codex_usage,
            desk_sources.read_estate,
        ) = originals


def test_forced_dashboard_refresh_is_single_flight(parent: Path) -> None:
    calls = {"claude": 0, "codex": 0, "estate": 0}
    entered = threading.Event()
    release = threading.Event()
    originals = (
        desk_sources.read_claude_usage,
        desk_sources.read_codex_usage,
        desk_sources.read_estate,
    )

    def claude(path: Path) -> dict:  # noqa: ARG001
        calls["claude"] += 1
        entered.set()
        assert release.wait(2)
        return {"status": "pass", "windows": []}

    def codex() -> dict:
        calls["codex"] += 1
        return {"status": "pass", "windows": []}

    def estate(path: Path, roots=None, stop_event=None) -> dict:  # noqa: ARG001
        calls["estate"] += 1
        return {"status": "pass", "projects": []}

    desk_sources.read_claude_usage = claude
    desk_sources.read_codex_usage = codex
    desk_sources.read_estate = estate
    try:
        sources = desk_sources.DeskSources(parent)
        results: list[dict] = []
        first = threading.Thread(target=lambda: results.append(sources.snapshot(force=True)))
        second = threading.Thread(target=lambda: results.append(sources.snapshot(force=True)))
        first.start()
        assert entered.wait(1)
        second.start()
        release.set()
        first.join(3)
        second.join(3)
        assert len(results) == 2
        assert calls == {"claude": 1, "codex": 1, "estate": 1}
    finally:
        release.set()
        (
            desk_sources.read_claude_usage,
            desk_sources.read_codex_usage,
            desk_sources.read_estate,
        ) = originals


def test_manifest_poll_is_hidden_and_cached(parent: Path) -> None:
    root = repo(parent)
    app = DeskApplication(root, parent / "state", FakeExecutor(), sources=FakeSources())
    original = desk_http.subprocess.run
    calls: list[dict] = []

    def observed(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)

    desk_http.subprocess.run = observed
    try:
        readings = [app.cartridges() for _ in range(100)]
        assert all(reading == readings[0] for reading in readings)
        assert len(calls) == 2
        assert all(call["timeout"] == 5 for call in calls)
        assert all(call.get("creationflags") == subprocess.CREATE_NO_WINDOW for call in calls)
    finally:
        desk_http.subprocess.run = original


def test_estate_scan_honors_stop_before_spawning(parent: Path) -> None:
    stopped = threading.Event()
    stopped.set()
    result = read_estate(parent, [parent], stopped)
    assert result["status"] == "canceled"
    assert result["projects"] == []
    assert result["max_parallel_processes"] == 1


def request(url: str, method: str = "GET", body: dict | None = None, token: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if token:
        headers["X-Tier-Desk-Token"] = token
    with urlopen(Request(url, data=data, method=method, headers=headers), timeout=3) as response:
        return response.status, json.loads(response.read())


def test_http_token(parent: Path) -> None:
    root = repo(parent)
    (root / "tests").mkdir()
    (root / "tests" / "test_tier_desk.py").write_text("print('ok')\n", encoding="utf-8")
    subprocess.run(["git", "add", "tests/test_tier_desk.py"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add desk test"], cwd=root, check=True)
    sources = FakeSources()
    app = DeskApplication(root, parent / "state", FakeExecutor(delay=0.2), sources=sources)
    app.store.pause("test holds queue")
    server = DeskServer(("127.0.0.1", 0), app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    app.start()
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, state = request(base + "/api/state")
        assert status == 200 and state["ok"] is True
        status, dashboard = request(base + "/api/dashboard")
        assert status == 200 and dashboard["dashboard"]["estate"]["status"] == "pass"
        try:
            request(base + "/api/dashboard/refresh", "POST", {})
        except HTTPError as exc:
            assert exc.code == 403
        else:
            raise AssertionError("tokenless dashboard refresh should fail")
        status, refreshed = request(base + "/api/dashboard/refresh", "POST", {}, app.token)
        assert status == 200 and refreshed["dashboard"]["gauges"]["codex"]["status"] == "pass"
        assert sources.forced == 1
        status, planned = request(
            base + "/api/intake/plan",
            "POST",
            {"intent": "Make this project easier to use."},
            app.token,
        )
        assert status == 200
        assert planned["plan"]["acceptance"] == "python -B tests/test_tier_desk.py"
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
        try:
            with urlopen(
                Request(base + "/healthz", headers={"Host": "rebind.example"}),
                timeout=3,
            ):
                pass
        except HTTPError as exc:
            assert exc.code == 400
        else:
            raise AssertionError("a DNS-rebinding Host header should fail")
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
        test_pid_liveness_is_truthful,
        test_state_transitions_fail_closed,
        test_claim_paths,
        test_run_envelope,
        test_worker_refuses_stale_heartbeat,
        test_dag_order,
        test_failure_pauses,
        test_cancel_cannot_be_overwritten_by_late_success,
        test_daily_limit,
        test_success_denominator_excludes_infrastructure_errors,
        test_claude_usage_parser,
        test_estate_reads_git_and_open_queue,
        test_queue_uses_named_state_column,
        test_dashboard_ui_contract,
        test_intent_first_work_entry,
        test_observer_processes_are_hidden_and_cached,
        test_forced_dashboard_refresh_is_single_flight,
        test_manifest_poll_is_hidden_and_cached,
        test_estate_scan_honors_stop_before_spawning,
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
