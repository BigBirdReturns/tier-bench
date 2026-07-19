#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


REPO = Path(__file__).resolve().parents[1]
TEST_TMP = REPO / ".test-tmp"
sys.path.insert(0, str(REPO))

from tier_runner.desk import (  # noqa: E402
    DeskApplication,
    DeskError,
    DeskHTTPServer,
    DeskScheduler,
    DeskStore,
    ExecutionResult,
    TierRunExecutor,
    _ProcessLock,
    _process_start_token,
    _read_pid_record,
    resolve_runs_dir,
    resolve_state_dir,
)


def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, check=True, capture_output=True, text=True)


def _iso(delta_seconds: int = 0) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)
    ).isoformat().replace("+00:00", "Z")


def make_repo(parent: Path) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    repo = parent / "subject"
    repo.mkdir()
    _run(["git", "init", "-q"], repo)
    _run(["git", "config", "user.email", "monster-wrangler@example.invalid"], repo)
    _run(["git", "config", "user.name", "Monster Wrangler Test"], repo)
    (repo / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    (repo / "hands.prompt.txt").write_text(
        "Task: {{TASK}}\nFiles: {{FILES}}\nAcceptance: {{ACCEPTANCE}}\nBase: {{BASE_COMMIT}}\n",
        encoding="utf-8",
    )
    manifest = {
        "schema": "tier-bench/pilot-backends@1",
        "protocol_commit": "a" * 40,
        "isolation": {
            "fresh_session_per_call": True,
            "instruction_files": False,
            "auto_memory": False,
            "conversation_carryover": False,
        },
        "tool_versions": {"fixture": "1"},
        "prompt_templates": {
            "hands": {"path": "hands.prompt.txt", "sha256": "fixture-not-used-by-desk"}
        },
        "arms": {
            "arm_a": {
                "model_id": "fixture-driver",
                "effort": "low",
                "surface": "fixture",
                "cost_basis": "shadow-estimated",
                "account": "fixture",
                "tier": "driver",
                "prompt_template": "hands",
                "adapter": {"command": ["fixture"]},
            },
            "arm_b": {
                "model_id": "fixture-hand",
                "effort": "low",
                "surface": "fixture",
                "cost_basis": "shadow-estimated",
                "account": "fixture",
                "tier": "cheap",
                "prompt_template": "hands",
                "adapter": {"command": ["fixture"]},
            },
        },
    }
    (repo / "fixture_backends.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (repo / "models.json").write_text(
        json.dumps(
            {
                "models": {
                    "fixture-hand": {
                        "provider": "local",
                        "input_per_1M": 0,
                        "output_per_1M": 0,
                        "tier_ceiling": "T1",
                    }
                },
                "roles": {"driver": "fixture-hand"},
                "composites": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _run(["git", "add", "-A"], repo)
    _run(["git", "commit", "-q", "-m", "fixture base"], repo)
    return repo


def route(label: str = "Primary", tank_id: str | None = None, arm: str = "arm_b") -> dict:
    return {
        "label": label,
        "manifest": "fixture_backends.json",
        "arm": arm,
        "tank_id": tank_id,
        "capability_basis": "measured",
        "quota_basis": "operator" if tank_id else "unknown",
    }


def task_payload(task_id: str, **overrides: object) -> dict:
    value: dict[str, object] = {
        "id": task_id,
        "title": f"Task {task_id}",
        "task": "Change app.py under the frozen scope.",
        "files": ["app.py"],
        "acceptance": f'"{sys.executable}" -c "import app; assert app.value() == 2"',
        "routes": [route()],
        "priority": 50,
        "queue_now": True,
        "approval_required": False,
        "max_attempts": 1,
        "escalation_mode": "operator",
    }
    value.update(overrides)
    return value


class FakeExecutor:
    def __init__(self, results: list[ExecutionResult]):
        self.results = list(results)
        self.routes: list[str] = []
        self.canceled: list[str] = []

    def run(self, task: dict, run: dict) -> ExecutionResult:
        self.routes.append(run["route"]["label"])
        Path(run["log_path"]).write_text(
            f"fixture execution for {task['id']} via {run['route']['label']}\n",
            encoding="utf-8",
        )
        if not self.results:
            raise AssertionError("fake executor ran more times than expected")
        return self.results.pop(0)

    def cancel(self, run_id: str) -> bool:
        self.canceled.append(run_id)
        return True


def wait_until(predicate, timeout: float = 4.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition did not become true before timeout")


def test_control_and_evidence_roots_are_separate(parent: Path) -> None:
    repo = make_repo(parent)
    state_dir = resolve_state_dir(repo, None)
    runs_dir = resolve_runs_dir(repo)
    assert state_dir == (repo / ".git" / "tier-desk").resolve()
    assert runs_dir == (repo / ".git" / "tier-runs" / "monster-wrangler").resolve()
    try:
        runs_dir.relative_to(state_dir)
    except ValueError:
        pass
    else:
        raise AssertionError("run evidence was nested under the control-state directory")


def test_approval_dependency_and_receipt_state(parent: Path) -> None:
    repo = make_repo(parent)
    store = DeskStore(parent / "state.sqlite3", repo)
    runs_dir = resolve_runs_dir(repo)
    first = store.create_task(task_payload("parent"))
    child = store.create_task(
        task_payload(
            "child",
            depends_on=["parent"],
            approval_required=True,
            queue_now=True,
        )
    )
    assert first["ready"] is True
    assert child["state"] == "DRAFT"
    approved = store.transition_task("child", "approve")
    assert approved["state"] == "QUEUED"
    assert approved["ready"] is False
    assert [item["id"] for item in approved["blocked_by"]] == ["parent"]

    claimed = store.claim("parent", first["next_route"], runs_dir)
    assert claimed is not None
    _, run = claimed
    assert Path(run["output_dir"]).is_dir()
    assert list(Path(run["output_dir"]).iterdir()) == []
    assert Path(run["log_path"]).parent == Path(run["output_dir"]).parent
    assert Path(run["log_path"]) != Path(run["output_dir"]) / "desk.log"
    assert store.complete_run(
        run["id"],
        ExecutionResult(
            state="ACCEPTED",
            receipt={"state": "ACCEPTED"},
            verification={"ok": True, "errors": []},
        ),
    )
    child = store.get_task("child")
    assert child is not None and child["ready"] is True
    assert store.verify_event_chain() == []


def test_subscription_tank_fails_closed_at_cap_and_when_stale(parent: Path) -> None:
    repo = make_repo(parent)
    store = DeskStore(parent / "state.sqlite3", repo)
    store.upsert_tank(
        {
            "id": "claude-window",
            "label": "Claude window",
            "kind": "subscription",
            "enabled": True,
            "headroom_percent": 50,
            "observed_at": _iso(),
            "snapshot_max_age_seconds": 300,
            "hard_cap_percent": 80,
        }
    )
    task = store.create_task(
        task_payload("tank-task", routes=[route(tank_id="claude-window")])
    )
    assert task["ready"] is True
    store.upsert_tank({"id": "claude-window", "headroom_percent": 20})
    capped = store.get_task("tank-task")
    assert capped is not None and capped["ready"] is False
    assert "at or beyond" in capped["route_blocked_reason"]

    store.upsert_tank(
        {
            "id": "claude-window",
            "headroom_percent": 70,
            "observed_at": _iso(-900),
            "snapshot_max_age_seconds": 60,
        }
    )
    stale = store.get_task("tank-task")
    assert stale is not None and stale["ready"] is False
    assert "stale" in stale["route_blocked_reason"]


def test_scheduler_escalates_to_next_route_and_accepts(parent: Path) -> None:
    repo = make_repo(parent)
    store = DeskStore(parent / "state.sqlite3", repo)
    fake = FakeExecutor(
        [
            ExecutionResult(
                state="ERROR",
                error="fixture transport error",
                evidence_complete=True,
            ),
            ExecutionResult(
                state="ACCEPTED",
                receipt={"state": "ACCEPTED"},
                verification={"ok": True, "errors": []},
                cost_usd=0.02,
                input_tokens=100,
                output_tokens=20,
            ),
        ]
    )
    task = store.create_task(
        task_payload(
            "escalate",
            routes=[route("Cheap route"), route("Judgment route", arm="arm_a")],
            max_attempts=2,
            escalation_mode="next-route-on-failure",
        )
    )
    scheduler = DeskScheduler(store, repo, resolve_runs_dir(repo), executor=fake)
    scheduler.tick()
    wait_until(lambda: not scheduler.active_run_ids())
    wait_until(lambda: store.get_task("escalate", include_runs=False)["state"] == "QUEUED")
    scheduler.tick()
    wait_until(lambda: not scheduler.active_run_ids())
    settled = store.get_task("escalate")
    assert settled is not None and settled["state"] == "ACCEPTED"
    assert settled["attempt_count"] == 2
    assert fake.routes == ["Cheap route", "Judgment route"]
    assert store.settings()["paused"] is False
    assert [run["state"] for run in reversed(settled["runs"])] == ["ERROR", "ACCEPTED"]


def test_terminal_failure_pauses_when_escalation_is_not_authorized(parent: Path) -> None:
    repo = make_repo(parent)
    store = DeskStore(parent / "state.sqlite3", repo)
    fake = FakeExecutor([ExecutionResult(state="REJECTED", error="acceptance failed")])
    store.create_task(task_payload("rejected"))
    scheduler = DeskScheduler(store, repo, resolve_runs_dir(repo), executor=fake)
    scheduler.tick()
    wait_until(lambda: not scheduler.active_run_ids())
    wait_until(lambda: store.settings()["paused"] is True)
    task = store.get_task("rejected")
    assert task is not None and task["state"] == "REJECTED"
    assert "operator review" in store.settings()["pause_reason"]


def test_restart_recovery_marks_unsettled_run_interrupted(parent: Path) -> None:
    repo = make_repo(parent)
    database = parent / "state.sqlite3"
    store = DeskStore(database, repo)
    task = store.create_task(task_payload("restart"))
    claimed = store.claim("restart", task["next_route"], resolve_runs_dir(repo))
    assert claimed is not None
    recovered = DeskStore(database, repo)
    task_after = recovered.get_task("restart")
    assert task_after is not None and task_after["state"] == "INTERRUPTED"
    assert task_after["runs"][0]["state"] == "INTERRUPTED"
    assert recovered.verify_event_chain() == []


def test_task_envelope_refuses_uncommitted_or_wrong_manifest(parent: Path) -> None:
    repo = make_repo(parent)
    store = DeskStore(parent / "state.sqlite3", repo)
    (repo / "uncommitted.json").write_text(
        json.dumps({"schema": "tier-bench/pilot-backends@1", "arms": {"arm_b": {}}}),
        encoding="utf-8",
    )
    try:
        store.create_task(
            task_payload(
                "uncommitted",
                routes=[{**route(), "manifest": "uncommitted.json"}],
            )
        )
    except DeskError as exc:
        assert "must be committed" in str(exc)
    else:
        raise AssertionError("uncommitted backend manifest was accepted")

    try:
        store.create_task(
            task_payload(
                "wrong-arm",
                routes=[{**route(), "arm": "arm_c"}],
            )
        )
    except DeskError as exc:
        assert "has no arm_c" in str(exc)
    else:
        raise AssertionError("missing manifest arm was accepted")

    try:
        store.create_task(task_payload("unsafe", files=["../outside.py"]))
    except DeskError as exc:
        assert "unsafe file scope" in str(exc)
    else:
        raise AssertionError("unsafe repository scope was accepted")


def test_route_progression_uses_the_route_actually_consumed(parent: Path) -> None:
    repo = make_repo(parent)
    store = DeskStore(parent / "state.sqlite3", repo)
    store.upsert_tank(
        {
            "id": "blocked",
            "label": "Blocked subscription",
            "kind": "subscription",
            "enabled": True,
            "headroom_percent": 10,
            "observed_at": _iso(),
            "hard_cap_percent": 80,
        }
    )
    task = store.create_task(
        task_payload(
            "route-progress",
            routes=[
                route("Blocked first", tank_id="blocked"),
                route("Eligible second"),
                route("Third route", arm="arm_a"),
            ],
            max_attempts=3,
        )
    )
    assert task["next_route"]["label"] == "Eligible second"
    claimed = store.claim(task["id"], task["next_route"], resolve_runs_dir(repo))
    assert claimed is not None
    _, run = claimed
    store.complete_run(
        run["id"],
        ExecutionResult(
            state="ERROR",
            error="verified fixture failure",
            evidence_complete=True,
        ),
    )
    store.transition_task(task["id"], "retry")
    retried = store.get_task(task["id"])
    assert retried is not None
    assert retried["next_route"]["label"] == "Third route"
    consumed = {item["route"]["label"]: item["consumed"] for item in retried["route_statuses"]}
    assert consumed == {
        "Blocked first": True,
        "Eligible second": True,
        "Third route": False,
    }


def test_state_database_refuses_repository_rebinding(parent: Path) -> None:
    first = make_repo(parent / "first")
    second = make_repo(parent / "second")
    database = parent / "shared.sqlite3"
    DeskStore(database, first)
    try:
        DeskStore(database, second)
    except DeskError as exc:
        assert "different repository" in str(exc)
    else:
        raise AssertionError("one control database was rebound to another repository")


def test_event_chain_detects_database_tampering(parent: Path) -> None:
    repo = make_repo(parent)
    store = DeskStore(parent / "state.sqlite3", repo)
    store.upsert_tank(
        {"id": "local", "label": "Local", "kind": "local", "enabled": True}
    )
    assert store.verify_event_chain() == []
    store._connect().execute(  # deliberate adversarial witness over local fixture data
        "UPDATE events SET detail_json='{}' WHERE seq=(SELECT MIN(seq) FROM events)"
    )
    assert any("hash mismatch" in error for error in store.verify_event_chain())

    other = DeskStore(parent / "tail.sqlite3", repo)
    other.upsert_tank(
        {"id": "local", "label": "Local", "kind": "local", "enabled": True}
    )
    other.upsert_tank({"id": "local", "notes": "second event"})
    other._connect().execute("DELETE FROM events WHERE seq=(SELECT MAX(seq) FROM events)")
    assert any("sealed metadata" in error for error in other.verify_event_chain())


def test_http_surface_requires_token_and_exposes_catalog(parent: Path) -> None:
    repo = make_repo(parent)
    app = DeskApplication(repo, parent / "state", executor=FakeExecutor([]))
    server = DeskHTTPServer(("127.0.0.1", 0), app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        with urlopen(base + "/healthz") as response:
            health = json.loads(response.read())
        assert health["ok"] is True

        payload = json.dumps(
            {"id": "local", "label": "Local", "kind": "local", "enabled": True}
        ).encode()
        denied = Request(
            base + "/api/tanks",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json", "X-Tier-Desk-Token": "wrong"},
        )
        try:
            urlopen(denied)
        except HTTPError as exc:
            assert exc.code == 403
        else:
            raise AssertionError("POST without the desk token was accepted")

        allowed = Request(
            base + "/api/tanks",
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Tier-Desk-Token": app.csrf_token,
            },
        )
        with urlopen(allowed) as response:
            result = json.loads(response.read())
        assert result["tank"]["id"] == "local"

        with urlopen(base + "/api/state") as response:
            state = json.loads(response.read())["state"]
        assert state["backend_manifests"][0]["path"] == "fixture_backends.json"
        assert state["models"]["models"]["fixture-hand"]["provider"] == "local"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)



def test_executor_uses_file_envelopes_and_cleans_failed_launch(parent: Path) -> None:
    repo = make_repo(parent)
    store = DeskStore(parent / "state.sqlite3", repo)
    long_task = "x" * 100_000
    task = store.create_task(task_payload("file-envelope", task=long_task))
    claimed = store.claim(task["id"], task["next_route"], resolve_runs_dir(repo))
    assert claimed is not None
    claimed_task, run = claimed
    executor = TierRunExecutor(repo, store)

    invocation_dir, task_path, acceptance_path, files_path = executor._invocation_files(
        claimed_task, run
    )
    command = executor._command(
        claimed_task, run, task_path, acceptance_path, files_path
    )
    assert "--task-file" in command
    assert "--acceptance-file" in command
    assert "--files-file" in command
    assert "--task" not in command
    assert long_task not in command
    assert task_path.read_text(encoding="utf-8") == long_task
    assert json.loads(files_path.read_text(encoding="utf-8")) == ["app.py"]
    shutil.rmtree(invocation_dir)

    import tier_runner.desk as desk_module

    original_popen = desk_module.subprocess.Popen

    def fail_popen(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise OSError("fixture launch failure")

    desk_module.subprocess.Popen = fail_popen
    try:
        try:
            executor.run(claimed_task, run)
        except OSError as exc:
            assert "fixture launch failure" in str(exc)
        else:
            raise AssertionError("executor swallowed a process launch failure")
    finally:
        desk_module.subprocess.Popen = original_popen
    assert not list(Path(run["output_dir"]).parent.glob(".*.invocation"))
    assert executor._processes == {}


def test_settled_task_cannot_be_retried_or_canceled(parent: Path) -> None:
    repo = make_repo(parent)
    store = DeskStore(parent / "state.sqlite3", repo)
    task = store.create_task(task_payload("settled"))
    claimed = store.claim(task["id"], task["next_route"], resolve_runs_dir(repo))
    assert claimed is not None
    _, run = claimed
    store.complete_run(
        run["id"],
        ExecutionResult(
            state="ACCEPTED",
            receipt={"state": "ACCEPTED"},
            verification={"ok": True, "errors": []},
            evidence_complete=True,
        ),
    )
    for action in ("retry", "cancel"):
        try:
            store.transition_task(task["id"], action)
        except DeskError:
            pass
        else:
            raise AssertionError(f"settled task accepted invalid action {action}")
    settled = store.get_task(task["id"])
    assert settled is not None and settled["state"] == "ACCEPTED"


def test_process_lock_and_pid_identity_are_fail_closed(parent: Path) -> None:
    lock_path = parent / "monster-wrangler.lock"
    first = _ProcessLock(lock_path)
    try:
        try:
            _ProcessLock(lock_path)
        except DeskError as exc:
            assert "owns this repository" in str(exc)
        else:
            raise AssertionError("second scheduler process acquired the control lock")
    finally:
        first.close()
    with _ProcessLock(lock_path):
        pass

    token = _process_start_token(os.getpid())
    record_path = parent / "pid.json"
    record_path.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "process_start_token": token,
                "url": "http://127.0.0.1:1/",
            }
        ),
        encoding="utf-8",
    )
    assert _read_pid_record(record_path) is not None
    if token is not None:
        record_path.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "process_start_token": token + "-wrong",
                }
            ),
            encoding="utf-8",
        )
        assert _read_pid_record(record_path) is None


def test_detached_daemon_publishes_readiness_and_stops(parent: Path) -> None:
    repo = make_repo(parent)
    state_dir = parent / "daemon-state"
    env = dict(os.environ)
    env["PYTHONPATH"] = (
        str(REPO)
        if not env.get("PYTHONPATH")
        else str(REPO) + os.pathsep + env["PYTHONPATH"]
    )
    base = [
        sys.executable,
        "-m",
        "tier_runner.desk",
        "--repo",
        str(repo),
        "--state-dir",
        str(state_dir),
        "--port",
        "0",
        "--no-open",
    ]
    started = subprocess.run(
        [*base, "--daemon"],
        cwd=REPO,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    payload = json.loads(started.stdout)
    assert payload["started"] is True
    assert payload["pid"] > 0
    assert not payload["url"].endswith(":0/")
    try:
        status = subprocess.run(
            [*base, "--status"],
            cwd=REPO,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        status_payload = json.loads(status.stdout)
        assert status_payload["running"] is True
        assert status_payload["pid"] == payload["pid"]
        assert status_payload["url"] == payload["url"]
    finally:
        stopped = subprocess.run(
            [*base, "--stop"],
            cwd=REPO,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert stopped.returncode == 0, (stopped.stdout, stopped.stderr)
    final = subprocess.run(
        [*base, "--status"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert final.returncode == 1
    assert json.loads(final.stdout)["running"] is False

def main() -> int:
    TEST_TMP.mkdir(exist_ok=True)
    parent = Path(tempfile.mkdtemp(prefix="monster-wrangler-", dir=TEST_TMP))
    tests = [
        test_control_and_evidence_roots_are_separate,
        test_approval_dependency_and_receipt_state,
        test_subscription_tank_fails_closed_at_cap_and_when_stale,
        test_scheduler_escalates_to_next_route_and_accepts,
        test_terminal_failure_pauses_when_escalation_is_not_authorized,
        test_restart_recovery_marks_unsettled_run_interrupted,
        test_task_envelope_refuses_uncommitted_or_wrong_manifest,
        test_route_progression_uses_the_route_actually_consumed,
        test_state_database_refuses_repository_rebinding,
        test_event_chain_detects_database_tampering,
        test_http_surface_requires_token_and_exposes_catalog,
        test_executor_uses_file_envelopes_and_cleans_failed_launch,
        test_settled_task_cannot_be_retried_or_canceled,
        test_process_lock_and_pid_identity_are_fail_closed,
        test_detached_daemon_publishes_readiness_and_stops,
    ]
    try:
        for index, test in enumerate(tests):
            case = parent / f"case-{index}"
            case.mkdir()
            test(case)
        print(
            f"OK: {len(tests)}/{len(tests)} Monster Wrangler tests passed; "
            "zero model calls"
        )
        return 0
    finally:
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
