#!/usr/bin/env python3
"""Witness tests for scripts/desk_driver_loop.py.

These are built strictly against the frozen CLI/desk-client/driftmap interface
documented for desk_driver_loop.py. The script under test is invoked only as a
subprocess (python scripts/desk_driver_loop.py ...) against a stub HTTP desk
started in-process. Nothing here imports desk_driver_loop as a module, so the
tests are safe to run whether or not the implementation exists yet.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "scripts" / "desk_driver_loop.py"

TOKEN = "testtoken"


class ScriptedDeskHandler(BaseHTTPRequestHandler):
    """One handler class shared by all stub-desk witnesses.

    Server-side state lives on `self.server` (an HTTPServer subclass carries
    the scripted attributes) so each test can configure a fresh server.
    """

    protocol_version = "HTTP/1.1"

    def log_message(self, *_args) -> None:  # silence default stderr logging
        return

    # -- helpers -------------------------------------------------------
    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _require_token(self) -> bool:
        if self.headers.get("X-Tier-Desk-Token") != TOKEN:
            self._send_json(403, {"ok": False, "error": "missing token"})
            return False
        return True

    # -- routing ---------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        server = self.server
        if self.path == "/":
            self.send_response(200)
            body = f'const TOKEN="{TOKEN}"'.encode("utf-8")
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        match = re.match(r"^/api/tasks/([^/]+)$", self.path)
        if match:
            task_id = match.group(1)
            server.polls[task_id] = server.polls.get(task_id, 0) + 1
            states = server.scripted.get(task_id, ["ACCEPTED"])
            index = min(server.polls[task_id] - 1, len(states) - 1)
            state = states[index]
            runs = server.runs.get(task_id, [])
            posted = next(
                (item for item in reversed(server.posts) if item.get("id") == task_id),
                {},
            )
            payload = {
                "task": {
                    "id": task_id,
                    "state": state,
                    "runs": runs,
                    "last_error": server.last_error.get(task_id),
                    "acceptance": posted.get("acceptance"),
                }
            }
            self._send_json(200, payload)
            return
        match = re.match(r"^/api/runs/([^/]+)/patch$", self.path)
        if match:
            run_id = match.group(1)
            self.send_response(200)
            body = server.patches.get(run_id, "diff --git a/x b/x\n").encode("utf-8")
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        match = re.match(r"^/api/runs/([^/]+)/log$", self.path)
        if match:
            run_id = match.group(1)
            self.send_response(200)
            body = server.logs.get(run_id, "log tail\n").encode("utf-8")
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        server = self.server
        if self.path == "/api/control/resume":
            body = self._read_json()
            server.resumes.append(body)
            self._send_json(200, {"ok": True})
            return
        if self.path == "/api/tasks":
            if not self._require_token():
                return
            body = self._read_json()
            server.posts.append(body)
            server.polls.setdefault(body["id"], 0)
            self._send_json(201, {"ok": True, "task": {"id": body["id"], "state": "QUEUED"}})
            return
        self._send_json(404, {"ok": False, "error": "not found"})


class ScriptedServer(HTTPServer):
    def __init__(self, address):
        super().__init__(address, ScriptedDeskHandler)
        self.posts: list[dict] = []
        self.resumes: list[dict] = []
        self.polls: dict[str, int] = {}
        self.scripted: dict[str, list[str]] = {}
        self.runs: dict[str, list[dict]] = {}
        self.patches: dict[str, str] = {}
        self.logs: dict[str, str] = {}
        self.last_error: dict[str, str] = {}


def start_server() -> ScriptedServer:
    server = ScriptedServer(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server._thread = thread  # type: ignore[attr-defined]
    return server


def stop_server(server: ScriptedServer) -> None:
    server.shutdown()
    server.server_close()
    server._thread.join(timeout=2)  # type: ignore[attr-defined]


def desk_url(server: ScriptedServer) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}"


FAKE_PLANNER = '''import json
import sys

out_path = sys.argv[-1]
work_items = {
    "work_items": [
        {
            "id": "task-1",
            "title": "Fix caf\\u00e9 rounding",
            "task": "Adjust rounding for caf\\u00e9 totals (non-ascii check: \\u00e9).",
            "files": ["app.py"],
            "acceptance": "python checker.py",
            "depends_on": [],
            "checker_files": [
                {"path": "checker.py", "content": "import sys\\nsys.exit(1)\\n"}
            ],
        }
    ]
}
with open(out_path, "w", encoding="utf-8", newline="\\n") as handle:
    json.dump(work_items, handle)
'''

FAKE_PLANNER_NONDISCRIMINATIVE = '''import json
import sys

out_path = sys.argv[-1]
work_items = {
    "work_items": [
        {
            "id": "task-1",
            "title": "Fix caf\\u00e9 rounding",
            "task": "Adjust rounding for caf\\u00e9 totals.",
            "files": ["app.py"],
            "acceptance": "python checker.py",
            "depends_on": [],
            "checker_files": [
                {"path": "checker.py", "content": "import sys\\nsys.exit(0)\\n"}
            ],
        }
    ]
}
with open(out_path, "w", encoding="utf-8", newline="\\n") as handle:
    json.dump(work_items, handle)
'''

FAKE_PLANNER_SCOPE_VIOLATION = '''import json
import sys

out_path = sys.argv[-1]
work_items = {
    "work_items": [
        {
            "id": "task-1",
            "title": "Bad scope",
            "task": "Touch app.py only.",
            "files": ["app.py"],
            "acceptance": "python app.py",
            "depends_on": [],
        }
    ]
}
with open(out_path, "w", encoding="utf-8", newline="\\n") as handle:
    json.dump(work_items, handle)
'''

# Repair-capable fake planner: first call emits the original item (with a
# discriminative checker outside scope); second call (repair brief) emits a
# single repaired work item. Invocation count is tracked via a counter file
# path passed as argv[1]; out_path is always argv[-1] (the loop appends
# [brief_path, out_path] after the configured planner-cmd argv).
FAKE_PLANNER_REPAIR = '''import json
import sys
from pathlib import Path

counter_path = Path(sys.argv[1])
out_path = sys.argv[-1]

count = 0
if counter_path.exists():
    count = int(counter_path.read_text(encoding="utf-8").strip() or "0")
count += 1
counter_path.write_text(str(count), encoding="utf-8")

if count == 1:
    work_items = {
        "work_items": [
            {
                "id": "task-1",
                "title": "First attempt",
                "task": "Adjust rounding for totals.",
                "files": ["app.py"],
                "acceptance": "python checker.py",
                "depends_on": [],
                "checker_files": [
                    {"path": "checker.py", "content": "import sys\\nsys.exit(1)\\n"}
                ],
            }
        ]
    }
else:
    work_items = {
        "work_items": [
            {
                "id": "task-1",
                "title": "Repaired attempt",
                "task": "Adjust rounding for totals (repaired after rejection).",
                "files": ["app.py"],
                "acceptance": "python checker.py",
                "depends_on": [],
            }
        ]
    }

with open(out_path, "w", encoding="utf-8", newline="\\n") as handle:
    json.dump(work_items, handle)
'''


FAKE_PLANNER_APPLY = '''import json
import sys

out_path = sys.argv[-1]
work_items = {
    "work_items": [
        {
            "id": "task-1",
            "title": "Apply one validated patch",
            "task": "Create app.py with the required exact value.",
            "files": ["app.py"],
            "acceptance": "python checker.py",
            "depends_on": [],
            "checker_files": [],
        }
    ]
}
with open(out_path, "w", encoding="utf-8", newline="\\n") as handle:
    json.dump(work_items, handle)
'''


def write_planner(repo: Path, name: str, source: str, takes_counter: bool = False) -> str:
    script = repo / name
    script.write_text(source, encoding="utf-8")
    if takes_counter:
        # planner-cmd is argv; loop invokes it as argv + [brief_path, out_path].
        # The repair planner additionally needs a counter file argument, so we
        # bake the counter path into the command itself.
        counter = repo / "planner_counter.txt"
        return f'python "{script}" "{counter}"'
    return f'python "{script}"'


def read_driftmap(path: Path) -> list[dict]:
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


def run_loop(
    repo: Path,
    desk: ScriptedServer,
    planner_cmd: str,
    driftmap: Path,
    extra=None,
    *,
    no_commit: bool = True,
):
    cmd = [
        sys.executable,
        str(DRIVER),
        "--repo",
        str(repo),
        "--goal",
        "Improve café rounding",
        "--desk",
        desk_url(desk),
        "--planner-cmd",
        planner_cmd,
        "--poll-seconds",
        "0.05",
        "--timeout-seconds",
        "10",
        "--driftmap",
        str(driftmap),
    ]
    if no_commit:
        cmd.append("--no-commit")
    if extra:
        cmd.extend(extra)
    return subprocess.run(
        cmd,
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def ok(label: str) -> None:
    print(f"ok - {label}")


def test_happy_path(parent: Path) -> None:
    repo = parent / "repo"
    repo.mkdir()
    driftmap = repo / "run" / "desk_driver_loop" / "driftmap.jsonl"
    planner_cmd = write_planner(repo, "planner.py", FAKE_PLANNER)

    server = start_server()
    try:
        server.scripted["task-1"] = ["QUEUED", "ACCEPTED"]
        server.runs["task-1"] = [{"id": "r1", "output_dir": str(parent / "out-task-1")}]
        result = run_loop(repo, server, planner_cmd, driftmap)
        assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
        posted = [p for p in server.posts if p.get("id") == "task-1"]
        assert posted, "expected task-1 to be posted to the desk"
        assert "é" in posted[0]["task"], "non-ASCII task text must survive UTF-8 round trip"
        events = read_driftmap(driftmap)
        kinds = [event["kind"] for event in events]
        assert "accepted" in kinds, kinds
    finally:
        stop_server(server)
    ok("happy_path: exit 0, non-ascii task text preserved, accepted driftmap event")


def test_nondiscriminative_fail_closed(parent: Path) -> None:
    repo = parent / "repo"
    repo.mkdir()
    driftmap = repo / "run" / "desk_driver_loop" / "driftmap.jsonl"
    planner_cmd = write_planner(repo, "planner.py", FAKE_PLANNER_NONDISCRIMINATIVE)

    server = start_server()
    try:
        result = run_loop(repo, server, planner_cmd, driftmap)
        assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
        events = read_driftmap(driftmap)
        kinds = [event["kind"] for event in events]
        assert "nondiscriminative_acceptance" in kinds, kinds
        assert not server.posts, "must fail closed before ever posting to the desk"
    finally:
        stop_server(server)
    ok("nondiscriminative_fail_closed: exit 2, nondiscriminative_acceptance event, no posts")


def test_scope_guard(parent: Path) -> None:
    repo = parent / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("print('hi')\n", encoding="utf-8")
    driftmap = repo / "run" / "desk_driver_loop" / "driftmap.jsonl"
    planner_cmd = write_planner(repo, "planner.py", FAKE_PLANNER_SCOPE_VIOLATION)

    server = start_server()
    try:
        result = run_loop(repo, server, planner_cmd, driftmap)
        assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
        assert not server.posts, "scope guard must trip before any desk call"
        assert not server.resumes
        events = read_driftmap(driftmap)
        kinds = [event["kind"] for event in events]
        assert "scope_guard_violation" in kinds, kinds
    finally:
        stop_server(server)
    ok("scope_guard: exit 2 before any desk POST, zero recorded desk calls")


def test_reject_then_repair(parent: Path) -> None:
    repo = parent / "repo"
    repo.mkdir()
    driftmap = repo / "run" / "desk_driver_loop" / "driftmap.jsonl"
    planner_cmd = write_planner(repo, "planner.py", FAKE_PLANNER_REPAIR, takes_counter=True)

    server = start_server()
    try:
        server.scripted["task-1"] = ["QUEUED", "REJECTED"]
        server.runs["task-1"] = [{"id": "r1", "output_dir": str(parent / "out-task-1")}]
        server.patches["r1"] = "diff --git a/app.py b/app.py\n@@ -1 +1 @@\n-old\n+new\n"
        server.logs["r1"] = "some repair-relevant log tail\n"
        server.last_error["task-1"] = "acceptance command failed"
        server.scripted["task-1-r1"] = ["QUEUED", "ACCEPTED"]
        server.runs["task-1-r1"] = [{"id": "r2", "output_dir": str(parent / "out-task-1-r1")}]

        result = run_loop(
            repo,
            server,
            planner_cmd,
            driftmap,
            extra=["--escalate-arms", "arm_a", "--max-rounds", "2"],
        )
        assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)

        repair_posts = [p for p in server.posts if p.get("id") == "task-1-r1"]
        assert repair_posts, [p.get("id") for p in server.posts]
        assert repair_posts[0]["id"].endswith("-r1")
        assert repair_posts[0].get("arm") == "arm_a", repair_posts[0]

        events = read_driftmap(driftmap)
        kinds = [event["kind"] for event in events]
        assert "rejected" in kinds, kinds
        assert "escalated" in kinds, kinds
        assert "accepted" in kinds, kinds
    finally:
        stop_server(server)
    ok("reject_then_repair: exit 0, repair id '-r1' posted with arm_a, driftmap has rejected/escalated/accepted")


def _init_apply_repo(repo: Path) -> None:
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Desk Driver Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "desk-driver@example.invalid"],
        cwd=repo,
        check=True,
    )
    (repo / "checker.py").write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "actual = Path('app.py').read_text(encoding='utf-8').splitlines() "
        "if Path('app.py').exists() else []\n"
        "raise SystemExit(actual != ['good'])\n",
        encoding="utf-8",
        newline="\n",
    )
    subprocess.run(["git", "add", "checker.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base checker"], cwd=repo, check=True, capture_output=True)


def _new_file_patch(content: str) -> str:
    return (
        "diff --git a/app.py b/app.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/app.py\n"
        "@@ -0,0 +1 @@\n"
        f"+{content}\n"
    )


def test_post_apply_validation_rolls_back(parent: Path) -> None:
    repo = parent / "repo"
    _init_apply_repo(repo)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    driftmap = repo / "run" / "desk_driver_loop" / "driftmap.jsonl"
    planner_cmd = write_planner(repo, "planner.py", FAKE_PLANNER_APPLY)
    server = start_server()
    try:
        server.scripted["task-1"] = ["ACCEPTED"]
        server.runs["task-1"] = [{"id": "r1", "output_dir": str(parent / "out-task-1")}]
        server.patches["r1"] = _new_file_patch("bad")
        result = run_loop(
            repo, server, planner_cmd, driftmap, extra=["--apply"], no_commit=False
        )
        assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
        kinds = [event["kind"] for event in read_driftmap(driftmap)]
        assert "post_apply_rejected" in kinds, kinds
        assert "applied" not in kinds, kinds
        assert not (repo / "app.py").exists(), "failed applied patch must be rolled back"
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
        ).stdout.strip()
        assert head == base, (base, head)
        assert subprocess.run(["git", "diff", "--quiet"], cwd=repo).returncode == 0
        assert subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo).returncode == 0
    finally:
        stop_server(server)
    ok("post_apply_validation_rolls_back: failed authoritative acceptance exits nonzero and restores the patch")


def test_post_apply_validation_commits(parent: Path) -> None:
    repo = parent / "repo"
    _init_apply_repo(repo)
    driftmap = repo / "run" / "desk_driver_loop" / "driftmap.jsonl"
    planner_cmd = write_planner(repo, "planner.py", FAKE_PLANNER_APPLY)
    server = start_server()
    try:
        server.scripted["task-1"] = ["ACCEPTED"]
        server.runs["task-1"] = [{"id": "r1", "output_dir": str(parent / "out-task-1")}]
        server.patches["r1"] = _new_file_patch("good")
        result = run_loop(
            repo, server, planner_cmd, driftmap, extra=["--apply"], no_commit=False
        )
        assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
        kinds = [event["kind"] for event in read_driftmap(driftmap)]
        assert "applied" in kinds, kinds
        assert "post_apply_rejected" not in kinds, kinds
        assert (repo / "app.py").read_text(encoding="utf-8").splitlines() == ["good"]
        subject = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert subject == "tier-desk: apply task-1", subject
        committed = subprocess.run(
            ["git", "show", "--pretty=format:", "--name-only", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        assert [path for path in committed if path] == ["app.py"], committed
    finally:
        stop_server(server)
    ok("post_apply_validation_commits: authoritative acceptance passes before one apply commit")


def main() -> int:
    parent = Path(tempfile.mkdtemp(prefix="desk-driver-loop-"))
    tests = [
        test_happy_path,
        test_nondiscriminative_fail_closed,
        test_scope_guard,
        test_reject_then_repair,
        test_post_apply_validation_rolls_back,
        test_post_apply_validation_commits,
    ]
    try:
        for index, test in enumerate(tests):
            case = parent / f"case-{index}"
            case.mkdir()
            test(case)
        print(f"PASS - {len(tests)}/{len(tests)} desk_driver_loop tests passed; zero model calls")
        return 0
    except AssertionError as exc:
        print(f"FAIL - {exc}")
        return 1
    finally:
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
