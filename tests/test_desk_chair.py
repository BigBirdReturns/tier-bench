from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
import subprocess
import threading
from urllib.request import Request, urlopen

import pytest

from tier_runner.desk_chair import ChairInbox, GitHubAccessError, GitHubTransport, chair_prompt
from tier_runner.desk_common import DeskError
from tier_runner.desk_http import DeskApplication, DeskServer
from tier_runner.desk_store import DeskStore


REPO = "BigBirdReturns/tier-bench"
BASE = "2f6ccc3a740db98b0687f758c5cedae8006cb1cb"


def local_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Chair Test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "chair@example.invalid"], cwd=root, check=True)
    (root / "pilot_backends.json").write_text(
        json.dumps({"schema": 1, "arms": {"arm_b": {}}}), encoding="utf-8"
    )
    subprocess.run(["git", "add", "pilot_backends.json"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=root, check=True)
    return root


def request_payload(request_id: str = "chair-1", **patch) -> dict:
    value = {
        "request_id": request_id,
        "repo": REPO,
        "base_sha": BASE,
        "allowed_paths": ["tier_runner/", "tests/test_desk_chair.py"],
        "acceptance": "python -m pytest -q tests/test_desk_chair.py",
        "auto_validate": False,
    }
    value.update(patch)
    return value


def marker(request_id: str = "chair-1", base: str = BASE) -> str:
    return f"<!-- tier-desk-chair:v1 request_id={request_id}\nbase_sha={base} -->"


def pull(number: int = 7, head_sha: str = "a" * 40, body: str | None = None, **patch) -> dict:
    value = {
        "number": number,
        "html_url": f"https://github.com/{REPO}/pull/{number}",
        "state": "open",
        "body": body or marker(),
        "head": {"sha": head_sha, "repo": {"full_name": REPO}},
        "base": {"sha": BASE, "repo": {"full_name": REPO}},
    }
    value.update(patch)
    return value


class FakeTransport:
    def __init__(self, pulls, files=None):
        self.pulls = pulls
        self.files = files or {}
        self.calls = []

    def list_open_pulls(self, repo: str) -> list[dict]:
        self.calls.append(("pulls", repo))
        value = self.pulls[repo]
        if isinstance(value, Exception):
            raise value
        return value

    def list_pull_files(self, repo: str, number: int) -> list[str]:
        self.calls.append(("files", repo, number))
        value = self.files[(repo, number)]
        if isinstance(value, Exception):
            raise value
        return value


class PagedTransport(GitHubTransport):
    def __init__(self, pages):
        super().__init__(gh_executable="missing-gh")
        self.pages = pages

    def _json(self, repo: str, endpoint: str):
        match = re.search(r"[?&]page=(\d+)", endpoint)
        assert match
        key = "files" if "/files?" in endpoint else "pulls"
        return self.pages[key].get(int(match.group(1)), [])


def test_chair_prompt_binds_contract_and_disables_execution(tmp_path: Path) -> None:
    store = DeskStore(tmp_path / "desk.sqlite3", local_repo(tmp_path))
    prompt = chair_prompt(store.register_chair_request(request_payload()))
    assert REPO in prompt and BASE in prompt and "tier_runner/" in prompt
    assert "Auto-validation: disabled" in prompt
    assert "will not invoke a model" in prompt


def test_auto_validation_registration_is_disabled(tmp_path: Path) -> None:
    store = DeskStore(tmp_path / "desk.sqlite3", local_repo(tmp_path))
    with pytest.raises(DeskError, match="auto-validation is disabled"):
        store.register_chair_request(request_payload(auto_validate=True))


def test_valid_return_is_approval_gated_draft_with_zero_wakes_and_custody(tmp_path: Path) -> None:
    store = DeskStore(tmp_path / "desk.sqlite3", local_repo(tmp_path))
    store.register_chair_request(request_payload())
    wakes = []
    transport = FakeTransport(
        {REPO: [pull()]},
        {(REPO, 7): ["tier_runner/desk_chair.py", "tests/test_desk_chair.py"]},
    )
    assert ChairInbox(store, transport, lambda: wakes.append(True)).poll_once()["accepted"] == 1
    assert wakes == []
    task = store.list_tasks()[0]
    assert task["state"] == "DRAFT" and task["approval_required"] is True
    assert task["attempt_count"] == 0
    assert store.get_chair_request("chair-1")["status"] == "CONSUMED"
    returned = store.list_chair_returns()[0]
    assert returned["status"] == "ACCEPTED"
    assert returned["detail"]["custody"] == {
        "repo": REPO,
        "pr_number": 7,
        "base_sha": BASE,
        "head_sha": "a" * 40,
        "head_repo": REPO,
    }


def test_consumed_request_dedupes_same_head_and_rejects_changed_head_and_replay(tmp_path: Path) -> None:
    store = DeskStore(tmp_path / "desk.sqlite3", local_repo(tmp_path))
    store.register_chair_request(request_payload())
    transport = FakeTransport(
        {REPO: [pull()]},
        {(REPO, 7): ["tier_runner/desk_chair.py"], (REPO, 8): ["tier_runner/desk_chair.py"]},
    )
    inbox = ChairInbox(store, transport, lambda: pytest.fail("scheduler wake"))
    assert inbox.poll_once()["accepted"] == 1
    assert inbox.poll_once()["deduped"] == 1
    transport.pulls[REPO] = [pull(head_sha="b" * 40), pull(number=8, head_sha="c" * 40)]
    assert inbox.poll_once()["rejected"] == 2
    assert len(store.list_tasks()) == 1
    assert "request_consumed" in {row["reason"] for row in store.list_chair_returns()}


def test_non_auto_out_of_scope_return_is_rejected(tmp_path: Path) -> None:
    store = DeskStore(tmp_path / "desk.sqlite3", local_repo(tmp_path))
    store.register_chair_request(request_payload())
    transport = FakeTransport({REPO: [pull()]}, {(REPO, 7): ["outside.txt"]})
    result = ChairInbox(store, transport, lambda: pytest.fail("scheduler wake")).poll_once()
    assert result["rejected"] == 1 and store.list_tasks() == []
    assert store.get_chair_request("chair-1")["status"] == "ACTIVE"
    assert store.list_chair_returns()[0]["reason"] == "changed_paths_outside_contract"


def test_atomic_rollback_when_return_recording_fails(tmp_path: Path) -> None:
    store = DeskStore(tmp_path / "desk.sqlite3", local_repo(tmp_path))
    store.register_chair_request(request_payload())
    store.db().execute(
        "CREATE TRIGGER fail_chair_return BEFORE INSERT ON chair_returns "
        "BEGIN SELECT RAISE(ABORT, 'forced return failure'); END"
    )
    inbox = ChairInbox(
        store,
        FakeTransport({REPO: [pull()]}, {(REPO, 7): ["tier_runner/desk_chair.py"]}),
        lambda: pytest.fail("scheduler wake"),
    )
    with pytest.raises(sqlite3.IntegrityError, match="forced return failure"):
        inbox.poll_once()
    assert store.list_tasks() == [] and store.list_chair_returns() == []
    assert store.get_chair_request("chair-1")["status"] == "ACTIVE"


def test_changed_file_access_failure_is_retryable_and_not_deduped(tmp_path: Path) -> None:
    store = DeskStore(tmp_path / "desk.sqlite3", local_repo(tmp_path))
    store.register_chair_request(request_payload())
    transport = FakeTransport(
        {REPO: [pull()]},
        {(REPO, 7): GitHubAccessError(REPO, "transient", 503)},
    )
    inbox = ChairInbox(store, transport, lambda: pytest.fail("scheduler wake"))
    assert inbox.poll_once()["access_errors"] == 1
    assert store.list_chair_returns() == []
    transport.files[(REPO, 7)] = ["tier_runner/desk_chair.py"]
    assert inbox.poll_once()["accepted"] == 1


def test_transport_fully_paginates_more_than_100_open_prs() -> None:
    transport = PagedTransport(
        {"pulls": {1: [{"number": n} for n in range(1, 101)], 2: [{"number": 101}]}, "files": {}}
    )
    pulls = transport.list_open_pulls(REPO)
    assert len(pulls) == 101 and pulls[-1]["number"] == 101


@pytest.mark.parametrize("count", [100, 101])
def test_transport_fully_paginates_changed_files(count: int) -> None:
    files = [{"filename": f"tier_runner/f{n}.py"} for n in range(count)]
    transport = PagedTransport({"pulls": {}, "files": {1: files[:100], 2: files[100:]}})
    changed = transport.list_pull_files(REPO, 7)
    assert len(changed) == count and changed[-1] == f"tier_runner/f{count - 1}.py"


def test_rejects_malformed_wrong_base_and_fork(tmp_path: Path) -> None:
    store = DeskStore(tmp_path / "desk.sqlite3", local_repo(tmp_path))
    store.register_chair_request(request_payload())
    store.register_chair_request(request_payload("other-1", repo="Other/repo"))
    wrong_base = "b" * 40
    pulls = [
        pull(1, body="no marker"),
        pull(2, body=marker() + "\n" + marker()),
        pull(3, body="<!-- tier-desk-chair:v1 broken -->"),
        pull(4, body=marker(base=wrong_base)),
        pull(5, head={"sha": "a" * 40, "repo": {"full_name": "fork/repo"}}),
        pull(7, body=marker(request_id="other-1")),
    ]
    result = ChairInbox(
        store,
        FakeTransport({REPO: pulls, "Other/repo": []}),
        lambda: pytest.fail("scheduler wake"),
    ).poll_once()
    assert result["rejected"] == 6 and store.list_tasks() == []


def test_open_pr_access_failure_is_per_repo_and_retryable(tmp_path: Path) -> None:
    store = DeskStore(tmp_path / "desk.sqlite3", local_repo(tmp_path))
    store.register_chair_request(request_payload())
    store.register_chair_request(request_payload("private-1", repo="private/repo"))
    transport = FakeTransport(
        {
            "private/repo": GitHubAccessError("private/repo", "gh_then_anonymous", 404),
            REPO: [pull()],
        },
        {(REPO, 7): ["tier_runner/desk_chair.py"]},
    )
    result = ChairInbox(store, transport, lambda: pytest.fail("scheduler wake")).poll_once()
    assert result["access_errors"] == 1 and result["accepted"] == 1


class FakeSources:
    def snapshot(self, force: bool = False) -> dict:
        return {"estate": {"status": "pass"}}


def http_json(url: str, method: str = "GET", body: dict | None = None, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Tier-Desk-Token"] = token
    data = json.dumps(body).encode() if body is not None else None
    with urlopen(Request(url, method=method, data=data, headers=headers), timeout=3) as response:
        return response.status, json.loads(response.read())


def test_manual_refresh_endpoint_surfaces_approval_gated_draft(tmp_path: Path) -> None:
    root = local_repo(tmp_path)
    transport = FakeTransport(
        {REPO: [pull()]},
        {(REPO, 7): ["tier_runner/desk_chair.py"]},
    )
    app = DeskApplication(root, tmp_path / "state", sources=FakeSources(), chair_transport=transport)
    server = DeskServer(("127.0.0.1", 0), app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, registered = http_json(base + "/api/chair/requests", "POST", request_payload(), app.token)
        assert status == 201 and "tier-desk-chair:v1" in registered["prompt"]
        status, refreshed = http_json(base + "/api/chair/refresh", "POST", {}, app.token)
        assert status == 200 and refreshed["result"]["accepted"] == 1
        _, state = http_json(base + "/api/state")
        task = state["state"]["tasks"][0]
        assert task["state"] == "DRAFT" and task["approval_required"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
