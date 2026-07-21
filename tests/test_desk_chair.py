from __future__ import annotations

import json
from pathlib import Path
import subprocess
import threading
from urllib.request import Request, urlopen

from tier_runner.desk_chair import ChairInbox, GitHubAccessError, chair_prompt
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


def pull(number: int = 7, head_sha: str = "a" * 40, body: str | None = None, **patch) -> dict:
    value = {
        "number": number,
        "html_url": f"https://github.com/{REPO}/pull/{number}",
        "state": "open",
        "body": body
        or f"<!-- tier-desk-chair:v1 request_id=chair-1 base_sha={BASE} -->",
        "head": {"sha": head_sha, "repo": {"full_name": REPO}},
        "base": {"sha": BASE, "repo": {"full_name": REPO}},
    }
    value.update(patch)
    return value


class FakeTransport:
    def __init__(self, pulls: dict[str, list[dict]], files: dict[tuple[str, int], list[str]] | None = None):
        self.pulls = pulls
        self.files = files or {}
        self.calls: list[tuple] = []

    def list_open_pulls(self, repo: str) -> list[dict]:
        self.calls.append(("pulls", repo))
        value = self.pulls[repo]
        if isinstance(value, Exception):
            raise value
        return value

    def list_pull_files(self, repo: str, number: int) -> tuple[list[str], bool]:
        self.calls.append(("files", repo, number))
        return self.files[(repo, number)], True


def test_chair_prompt_binds_exact_contract(tmp_path: Path) -> None:
    store = DeskStore(tmp_path / "desk.sqlite3", local_repo(tmp_path))
    registered = store.register_chair_request(request_payload())
    prompt = chair_prompt(registered)
    assert REPO in prompt and BASE in prompt
    assert "tier_runner/" in prompt
    assert f"<!-- tier-desk-chair:v1 request_id=chair-1 base_sha={BASE} -->" in prompt


def test_exact_return_creates_one_draft_and_dedupes(tmp_path: Path) -> None:
    store = DeskStore(tmp_path / "desk.sqlite3", local_repo(tmp_path))
    store.register_chair_request(request_payload())
    wakes: list[bool] = []
    inbox = ChairInbox(store, FakeTransport({REPO: [pull()]}), wakes.append)
    first = inbox.poll_once()
    second = inbox.poll_once()
    assert first["accepted"] == 1 and second["deduped"] == 1
    task = store.list_tasks()[0]
    assert task["state"] == "DRAFT"
    assert set(task["files"]) == {"tier_runner/", "tests/test_desk_chair.py"}
    assert wakes == []


def test_auto_validate_requires_safe_paths_and_changed_head_is_new(tmp_path: Path) -> None:
    store = DeskStore(tmp_path / "desk.sqlite3", local_repo(tmp_path))
    store.register_chair_request(request_payload(auto_validate=True))
    transport = FakeTransport(
        {REPO: [pull()]},
        {(REPO, 7): ["tier_runner/desk_chair.py", "tests/test_desk_chair.py"]},
    )
    wake_count: list[bool] = []
    inbox = ChairInbox(store, transport, lambda: wake_count.append(True))
    assert inbox.poll_once()["accepted"] == 1
    assert store.list_tasks()[0]["state"] == "QUEUED"
    transport.pulls[REPO] = [pull(head_sha="b" * 40)]
    assert inbox.poll_once()["accepted"] == 1
    assert len(store.list_tasks()) == 2 and len(wake_count) == 2


def test_rejects_malformed_wrong_base_fork_and_unsafe_auto_paths(tmp_path: Path) -> None:
    store = DeskStore(tmp_path / "desk.sqlite3", local_repo(tmp_path))
    store.register_chair_request(request_payload(auto_validate=True))
    store.register_chair_request(request_payload("other-1", repo="Other/repo"))
    wrong_base = "b" * 40
    pulls = [
        pull(1, body="no marker"),
        pull(2, body=f"<!-- tier-desk-chair:v1 request_id=chair-1 base_sha={BASE} -->\n<!-- tier-desk-chair:v1 request_id=chair-1 base_sha={BASE} -->"),
        pull(3, body="<!-- tier-desk-chair:v1 broken -->"),
        pull(4, body=f"<!-- tier-desk-chair:v1 request_id=chair-1 base_sha={wrong_base} -->"),
        pull(5, head={"sha": "a" * 40, "repo": {"full_name": "fork/repo"}}),
        pull(6),
        pull(7, body=f"<!-- tier-desk-chair:v1 request_id=other-1 base_sha={BASE} -->"),
    ]
    transport = FakeTransport({REPO: pulls, "Other/repo": []}, {(REPO, 6): ["outside.txt"]})
    wakes: list[bool] = []
    result = ChairInbox(store, transport, wakes.append).poll_once()
    assert result["rejected"] == 7
    assert store.list_tasks() == [] and wakes == []


def test_access_failure_is_per_repo_and_public_polling_continues(tmp_path: Path) -> None:
    store = DeskStore(tmp_path / "desk.sqlite3", local_repo(tmp_path))
    store.register_chair_request(request_payload())
    store.register_chair_request(request_payload("private-1", repo="private/repo"))
    transport = FakeTransport(
        {
            "private/repo": GitHubAccessError("private/repo", "gh_then_anonymous", 404),
            REPO: [pull()],
        }
    )
    result = ChairInbox(store, transport, lambda: None).poll_once()
    assert result["access_errors"] == 1 and result["accepted"] == 1
    assert len(store.list_tasks()) == 1


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


def test_manual_refresh_endpoint_surfaces_return_in_state(tmp_path: Path) -> None:
    root = local_repo(tmp_path)
    transport = FakeTransport({REPO: [pull()]})
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
        assert state["state"]["chair_inbox"]["returns"][0]["pr_number"] == 7
        assert state["state"]["tasks"][0]["state"] == "DRAFT"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
