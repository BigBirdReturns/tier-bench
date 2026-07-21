"""Drive tier-desk through a goal-to-acceptance loop with fail-closed guards."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


TERMINAL_STATES = {"ACCEPTED", "REJECTED", "ERROR", "CANCELED", "INTERRUPTED"}
ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


class GuardViolation(RuntimeError):
    def __init__(self, kind: str, task_id: str | None, detail: str):
        super().__init__(detail)
        self.kind = kind
        self.task_id = task_id


class PlannerQuestions(RuntimeError):
    def __init__(self, questions: list[str]):
        super().__init__("planner returned clarifying questions")
        self.questions = questions


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Drive tier-desk from a goal to accepted work")
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--goal")
    parser.add_argument("--plan-file", type=Path)
    parser.add_argument("--desk", default="http://127.0.0.1:8876")
    parser.add_argument("--planner-cmd", default="python scripts/planner_codex.py")
    # Subscription-covered arms are the default ladder. The local arm is not in
    # it: measured 2026-07-19, it needed >180s on a T2 task (adapter transport
    # timeout) where arm_spark returned a perfect result in 5.5s, and its one
    # completed attempt hung the referee. Ask for it explicitly with --arm arm_b.
    parser.add_argument("--arm", default="arm_spark")
    parser.add_argument("--escalate-arms", default="arm_luna,arm_a")
    parser.add_argument("--max-rounds", type=int, default=2)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--no-commit", action="store_true")
    parser.add_argument("--driftmap", type=Path)
    args = parser.parse_args(argv)
    if not args.goal and not args.plan_file:
        parser.error("--goal is required unless --plan-file is given")
    args.repo = args.repo.expanduser().resolve()
    default_driftmap = args.repo / "run" / "desk_driver_loop" / "driftmap.jsonl"
    args.driftmap = args.driftmap.expanduser().resolve() if args.driftmap else default_driftmap
    return args


def split_command(command: str) -> list[str]:
    """Split a command line without mangling Windows backslashes as escapes."""
    lexer = shlex.shlex(command, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    lexer.escape = ""
    return list(lexer)


def run_planner(planner_cmd: str, brief_text: str, repo: Path, workdir: Path, name: str) -> Any:
    brief_path = workdir / f"{name}.brief.txt"
    out_path = workdir / f"{name}.out.json"
    brief_path.write_text(brief_text, encoding="utf-8", newline="\n")
    argv = split_command(planner_cmd) + [str(brief_path), str(out_path)]
    result = subprocess.run(argv, cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no output"
        raise RuntimeError(f"planner command exited {result.returncode}: {detail}")
    try:
        return json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"planner did not write valid JSON to {out_path}: {exc}") from exc


def load_plan(args: argparse.Namespace, workdir: Path) -> list[Any]:
    if args.plan_file:
        raw = json.loads(args.plan_file.read_text(encoding="utf-8"))
    else:
        raw = run_planner(args.planner_cmd, args.goal, args.repo, workdir, "plan")
    if not isinstance(raw, dict):
        raise RuntimeError("planner output must be a JSON object")
    questions = raw.get("questions")
    if questions:
        if not isinstance(questions, list):
            raise RuntimeError('"questions" must be a list of strings')
        raise PlannerQuestions([str(question) for question in questions])
    items = raw.get("work_items")
    if not isinstance(items, list) or not items:
        raise RuntimeError('planner output must contain a non-empty "work_items" array')
    return items


def _normalize_scope(item_id: str, raw: str) -> str:
    value = raw.strip().replace("\\", "/")
    pure = PurePosixPath(value.rstrip("/")) if value else None
    if (
        not value or value.startswith("/") or re.match(r"^[A-Za-z]:", value)
        or not pure.parts or ".." in pure.parts or pure.parts[0] == ".git"
    ):
        raise GuardViolation("scope_guard_violation", item_id, f"unsafe file scope: {raw!r}")
    return pure.as_posix() + ("/" if value.endswith("/") else "")


def _scope_contains(scope: str, candidate: str) -> bool:
    base = scope.rstrip("/")
    return candidate == base or candidate.startswith(base + "/")


def validate_items(raw_items: list[Any], repo: Path) -> list[dict[str, Any]]:  # noqa: ARG001
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise GuardViolation("scope_guard_violation", None, "each work item must be an object")
        item_id = str(raw.get("id", ""))
        if not ID_RE.match(item_id):
            raise GuardViolation("scope_guard_violation", item_id or None, f"invalid item id: {item_id!r}")
        if item_id in seen_ids:
            raise GuardViolation("scope_guard_violation", item_id, f"duplicate item id: {item_id}")
        seen_ids.add(item_id)
        title = str(raw.get("title", "")).strip()
        task_text = str(raw.get("task", "")).strip()
        acceptance = str(raw.get("acceptance", "")).strip()
        if not title or not task_text or not acceptance:
            raise GuardViolation("scope_guard_violation", item_id, "title, task, and acceptance are required")
        files_raw = raw.get("files")
        if not isinstance(files_raw, list) or not files_raw:
            raise GuardViolation("scope_guard_violation", item_id, "files must be a non-empty list")
        files = [_normalize_scope(item_id, str(entry)) for entry in files_raw]
        depends_raw = raw.get("depends_on") or []
        if not isinstance(depends_raw, list):
            raise GuardViolation("scope_guard_violation", item_id, "depends_on must be a list")
        checker_files_raw = raw.get("checker_files") or []
        if not isinstance(checker_files_raw, list):
            raise GuardViolation("scope_guard_violation", item_id, "checker_files must be a list")
        checker_files = []
        for entry in checker_files_raw:
            if not isinstance(entry, dict) or "path" not in entry or "content" not in entry:
                raise GuardViolation("scope_guard_violation", item_id, "checker_files entries need path and content")
            path = _normalize_scope(item_id, str(entry["path"]))
            checker_files.append({"path": path, "content": str(entry["content"])})
        arm = str(raw["arm"]).strip() if raw.get("arm") else None
        normalized.append(
            {
                "id": item_id,
                "title": title,
                "task": task_text,
                "acceptance": acceptance,
                "files": files,
                "depends_on": [str(dep) for dep in depends_raw],
                "checker_files": checker_files,
                "arm": arm,
            }
        )
    known_ids = {item["id"] for item in normalized}
    for item in normalized:
        for dep in item["depends_on"]:
            if dep not in known_ids:
                raise GuardViolation("scope_guard_violation", item["id"], f"depends_on references unknown id: {dep}")
    all_scopes = [scope for item in normalized for scope in item["files"]]
    for item in normalized:
        for token in item["acceptance"].split():
            candidate = token.replace("\\", "/")
            for scope in item["files"]:
                if _scope_contains(scope, candidate):
                    detail = f"acceptance command touches its own file scope: {token!r}"
                    raise GuardViolation("scope_guard_violation", item["id"], detail)
        for checker in item["checker_files"]:
            for scope in all_scopes:
                if _scope_contains(scope, checker["path"]):
                    detail = f"checker file path is inside a task scope: {checker['path']}"
                    raise GuardViolation("scope_guard_violation", item["id"], detail)
    return normalized


def write_checkers(repo: Path, items: list[dict[str, Any]]) -> list[Path]:
    written: list[Path] = []
    for item in items:
        for checker in item["checker_files"]:
            target = repo / Path(*PurePosixPath(checker["path"]).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(checker["content"], encoding="utf-8", newline="\n")
            written.append(target)
    return written


def discriminative_precheck(items: list[dict[str, Any]], repo: Path) -> None:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    for item in items:
        result = subprocess.run(item["acceptance"], shell=True, cwd=repo, env=env, capture_output=True, text=True)
        if result.returncode == 0:
            raise GuardViolation(
                "nondiscriminative_acceptance",
                item["id"],
                f"acceptance for {item['id']} passed before any patch was applied",
            )


def seal_checkers(repo: Path, written: list[Path], no_commit: bool) -> None:
    if no_commit or not written:
        return
    relative = [str(path.relative_to(repo)) for path in written]
    subprocess.run(["git", "add", "--"] + relative, cwd=repo, check=True, capture_output=True, text=True)
    staged = subprocess.run(["git", "diff", "--cached", "--quiet", "--"] + relative, cwd=repo)
    if staged.returncode == 0:
        return
    message = "tier-desk driver: seal discriminative checkers"
    subprocess.run(["git", "commit", "-m", message], cwd=repo, check=True, capture_output=True, text=True)


class DeskClient:
    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.token = self._fetch_token()

    def _open(self, request: Request) -> bytes:
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"desk request failed ({request.full_url}): {exc}") from exc

    def _fetch_token(self) -> str:
        body = self._open(Request(self.base_url + "/")).decode("utf-8", errors="replace")
        match = re.search(r'TOKEN="([^"]+)"', body)
        if not match:
            raise RuntimeError("could not locate the desk mutation token on /")
        return match.group(1)

    def _get_json(self, path: str) -> dict[str, Any]:
        return json.loads(self._open(Request(self.base_url + path)).decode("utf-8"))

    def _get_text(self, path: str) -> str:
        return self._open(Request(self.base_url + path)).decode("utf-8", errors="replace")

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json; charset=utf-8", "X-Tier-Desk-Token": self.token}
        request = Request(self.base_url + path, data=data, method="POST", headers=headers)
        return json.loads(self._open(request).decode("utf-8"))

    def post_task(self, item: dict[str, Any], arm: str, task_id: str) -> dict[str, Any]:
        payload = {
            "id": task_id,
            "title": item["title"],
            "task": item["task"],
            "files": item["files"],
            "acceptance": item["acceptance"],
            "arm": arm,
            "queue_now": True,
            "depends_on": item.get("depends_on", []),
        }
        return self._post("/api/tasks", payload)

    def resume(self) -> dict[str, Any]:
        return self._post("/api/control/resume", {})

    def get_task(self, task_id: str) -> dict[str, Any]:
        return self._get_json(f"/api/tasks/{task_id}")

    def get_patch(self, run_id: str) -> str:
        return self._get_text(f"/api/runs/{run_id}/patch")

    def get_log(self, run_id: str, tail: int = 4000) -> str:
        return self._get_text(f"/api/runs/{run_id}/log?tail={tail}")


def drift(path: Path, driftlog: list[dict[str, Any]], kind: str, task_id: str | None, round_no: int, detail: str) -> None:
    event = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "kind": kind,
        "task_id": task_id,
        "round": round_no,
        "detail": detail,
    }
    driftlog.append(event)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")


def summary(driftlog: list[dict[str, Any]], ok: bool, reason: str) -> None:
    counts: dict[str, int] = {}
    for event in driftlog:
        counts[event["kind"]] = counts.get(event["kind"], 0) + 1
    for kind in sorted(counts):
        print(f"{kind}: {counts[kind]}")
    if ok:
        print("DRIFTMAP: within spec")
    else:
        print(f"DRIFTMAP: goal drifted outside spec ({reason})")


def _last_run(task_json: dict[str, Any] | None) -> dict[str, Any] | None:
    task = task_json.get("task") if isinstance(task_json, dict) else None
    runs = task.get("runs") if isinstance(task, dict) else None
    return runs[0] if isinstance(runs, list) and runs else None


def _last_error(task_json: dict[str, Any] | None, timed_out: bool, timeout_seconds: float) -> str:
    if timed_out:
        return f"timed out after {timeout_seconds}s waiting for a terminal state"
    task = task_json.get("task") if isinstance(task_json, dict) else None
    if isinstance(task, dict) and task.get("last_error"):
        return str(task["last_error"])
    run = _last_run(task_json)
    if run and run.get("error"):
        return str(run["error"])
    return "no error message reported"


def poll_all(client: DeskClient, task_ids: dict[str, str], poll_seconds: float, timeout_seconds: float) -> dict[str, Any]:
    """Poll every task_id to a terminal state or its own timeout; keyed by lineage id."""
    deadlines = {lineage: time.monotonic() + timeout_seconds for lineage in task_ids}
    results: dict[str, Any] = {}
    remaining = dict(task_ids)
    while remaining:
        for lineage, task_id in list(remaining.items()):
            try:
                task_json = client.get_task(task_id)
            except RuntimeError:
                task_json = None
            state = None
            if isinstance(task_json, dict) and isinstance(task_json.get("task"), dict):
                state = task_json["task"].get("state")
            if state in TERMINAL_STATES:
                results[lineage] = (state, task_json, False)
                del remaining[lineage]
            elif time.monotonic() >= deadlines[lineage]:
                results[lineage] = ("ERROR", task_json, True)
                del remaining[lineage]
        if remaining:
            time.sleep(poll_seconds)
    return results


def check_instruction_violation(task_json: dict[str, Any] | None, emit: Any, task_id: str, round_no: int) -> None:
    run = _last_run(task_json)
    if not run or not run.get("output_dir"):
        return
    receipt_path = Path(run["output_dir"]) / "receipt.json"
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return
    changes = receipt.get("changes") if isinstance(receipt, dict) else None
    violations = changes.get("scope_violations") if isinstance(changes, dict) else None
    if violations:
        emit("instruction_violation", task_id, round_no, f"receipt reported scope violations: {violations}")


def _process_detail(result: subprocess.CompletedProcess[str], fallback: str) -> str:
    detail = (result.stderr or "").strip() or (result.stdout or "").strip() or fallback
    return detail[-2000:]


def apply_accept(
    client: DeskClient,
    args: argparse.Namespace,
    task_json: Any,
    task_id: str,
    round_no: int,
    emit: Any,
) -> bool:
    if args.no_commit:
        return True
    run = _last_run(task_json)
    if not run or not run.get("id"):
        emit("error", task_id, round_no, "accepted task has no run to apply")
        return False
    task = task_json.get("task") if isinstance(task_json, dict) else None
    acceptance = task.get("acceptance") if isinstance(task, dict) else None
    if not isinstance(acceptance, str) or not acceptance.strip():
        emit("error", task_id, round_no, "accepted task has no acceptance command to revalidate")
        return False
    try:
        patch_text = client.get_patch(run["id"])
    except RuntimeError as exc:
        emit("error", task_id, round_no, f"could not fetch patch: {exc}")
        return False
    if not patch_text.strip():
        emit("error", task_id, round_no, "accepted task returned an empty patch")
        return False
    # Stage exactly the accepted patch. The planner/driftmap may live inside the
    # repository, so `git add -A` would accidentally mix driver residue into
    # the apply commit.
    apply_cmd = ["git", "apply", "--index", "--whitespace=nowarn", "-"]
    applied = subprocess.run(apply_cmd, input=patch_text, cwd=args.repo, capture_output=True, text=True)
    if applied.returncode != 0:
        emit("error", task_id, round_no, f"git apply failed: {applied.stderr.strip()}")
        return False

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    verified = subprocess.run(
        acceptance,
        shell=True,
        cwd=args.repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if verified.returncode != 0:
        rollback = subprocess.run(
            ["git", "apply", "-R", "--index", "--whitespace=nowarn", "-"],
            input=patch_text,
            cwd=args.repo,
            capture_output=True,
            text=True,
        )
        detail = _process_detail(verified, f"acceptance exited {verified.returncode}")
        if rollback.returncode != 0:
            rollback_detail = _process_detail(rollback, f"rollback exited {rollback.returncode}")
            detail += f"; rollback failed: {rollback_detail}"
        emit("post_apply_rejected", task_id, round_no, detail)
        return False

    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=args.repo)
    if staged.returncode == 0:
        emit("error", task_id, round_no, "post-apply acceptance passed but no changes were staged")
        return False
    commit = subprocess.run(["git", "commit", "-m", f"tier-desk: apply {task_id}"], cwd=args.repo, capture_output=True, text=True)
    if commit.returncode != 0:
        emit("error", task_id, round_no, f"git commit failed: {commit.stderr.strip()}")
        return False
    emit("applied", task_id, round_no, "patch applied and committed")
    return True


def compose_repair_brief(task_text: str, last_error: str, patch_text: str, log_tail: str) -> str:
    sections = [
        ("ORIGINAL TASK", task_text.strip()),
        ("LAST ERROR", last_error.strip() or "(no error message)"),
        ("PATCH", patch_text.strip() or "(no patch produced)"),
        ("LOG TAIL", log_tail.strip() or "(no log captured)"),
    ]
    lines: list[str] = []
    for heading, body in sections:
        lines.append(f"=== {heading} ===")
        lines.append(body)
        lines.append("")
    return "\n".join(lines)


def build_repair_item(
    client: DeskClient, args: argparse.Namespace, workdir: Path, lineage: str, task_id: str,
    round_no: int, task_json: Any, current_item: dict[str, Any], last_error: str,
) -> dict[str, Any]:
    run = _last_run(task_json)
    patch_text = ""
    log_text = ""
    if run and run.get("id"):
        try:
            patch_text = client.get_patch(run["id"])
        except RuntimeError:
            patch_text = ""
        try:
            log_text = client.get_log(run["id"], 4000)
        except RuntimeError:
            log_text = ""
    brief = compose_repair_brief(current_item["task"], last_error, patch_text, log_text)
    name = f"repair-{lineage}-r{round_no + 1}"
    result = run_planner(args.planner_cmd, brief, args.repo, workdir, name)
    if not isinstance(result, dict):
        raise RuntimeError("repair planner output must be a JSON object")
    if result.get("questions"):
        raise RuntimeError("planner returned clarifying questions during a repair round")
    work_items = result.get("work_items")
    if not isinstance(work_items, list) or len(work_items) != 1:
        raise RuntimeError('repair planner must return exactly one "work_items" entry')
    repaired = work_items[0]
    if not isinstance(repaired, dict):
        raise RuntimeError("repair work item must be an object")
    return repaired


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    driftlog: list[dict[str, Any]] = []

    def emit(kind: str, task_id: str | None, round_no: int, detail: str) -> None:
        drift(args.driftmap, driftlog, kind, task_id, round_no, detail)

    workdir = args.driftmap.parent / "planner"
    workdir.mkdir(parents=True, exist_ok=True)

    try:
        raw_items = load_plan(args, workdir)
    except PlannerQuestions as exc:
        emit("planner_questions", None, 0, "; ".join(exc.questions))
        for question in exc.questions:
            print(question)
        return 3
    except (RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"desk_driver_loop: {exc}", file=sys.stderr)
        return 2

    try:
        items = validate_items(raw_items, args.repo)
        written = write_checkers(args.repo, items)
        discriminative_precheck(items, args.repo)
        seal_checkers(args.repo, written, args.no_commit)
    except GuardViolation as exc:
        emit(exc.kind, exc.task_id, 0, str(exc))
        print(f"desk_driver_loop: {exc}", file=sys.stderr)
        summary(driftlog, False, str(exc))
        return 2

    try:
        client = DeskClient(args.desk)
    except RuntimeError as exc:
        print(f"desk_driver_loop: cannot reach desk: {exc}", file=sys.stderr)
        summary(driftlog, False, f"cannot reach desk: {exc}")
        return 2

    escalate = [part.strip() for part in args.escalate_arms.split(",") if part.strip()]
    lineages: dict[str, dict[str, Any]] = {}
    for item in items:
        lineages[item["id"]] = {
            "current_id": item["id"],
            "item": dict(item),
            "arm_ladder": [item["arm"] or args.arm] + escalate,
            "rounds_used": 0,
        }
    outcomes: dict[str, str] = {}
    active = dict(lineages)
    round_no = 0

    while active:
        for lineage, state in active.items():
            arm = state["arm_ladder"][min(round_no, len(state["arm_ladder"]) - 1)]
            client.post_task(state["item"], arm, state["current_id"])
        client.resume()
        polled = poll_all(
            client,
            {lineage: state["current_id"] for lineage, state in active.items()},
            args.poll_seconds,
            args.timeout_seconds,
        )
        next_active: dict[str, dict[str, Any]] = {}
        for lineage, state in active.items():
            task_id = state["current_id"]
            outcome_state, task_json, timed_out = polled[lineage]
            check_instruction_violation(task_json, emit, task_id, round_no)
            if outcome_state == "ACCEPTED":
                emit("accepted", task_id, round_no, "item accepted")
                applied = not args.apply or apply_accept(
                    client, args, task_json, task_id, round_no, emit
                )
                outcomes[lineage] = "accepted" if applied else "failed"
                continue
            last_error = _last_error(task_json, timed_out, args.timeout_seconds)
            emit("rejected" if outcome_state == "REJECTED" else "error", task_id, round_no, last_error)
            if state["rounds_used"] >= args.max_rounds:
                outcomes[lineage] = "failed"
                continue
            try:
                repaired = build_repair_item(
                    client, args, workdir, lineage, task_id, round_no, task_json, state["item"], last_error
                )
            except (RuntimeError, OSError) as exc:
                outcomes[lineage] = "failed"
                emit("error", task_id, round_no, f"repair planning failed: {exc}")
                continue
            state["rounds_used"] += 1
            new_id = f"{lineage}-r{state['rounds_used']}"
            new_arm = state["arm_ladder"][min(round_no + 1, len(state["arm_ladder"]) - 1)]
            emit("escalated", new_id, round_no + 1, f"escalated {task_id} to arm {new_arm}")
            new_task_text = str(repaired.get("task") or state["item"]["task"]).strip()
            if new_task_text != state["item"]["task"]:
                emit("spec_revision", new_id, round_no + 1, "planner revised task text during repair")
            new_title = str(repaired.get("title") or state["item"]["title"]).strip()
            state["item"] = {**state["item"], "task": new_task_text, "title": new_title}
            state["current_id"] = new_id
            next_active[lineage] = state
        active = next_active
        round_no += 1

    ok = bool(outcomes) and all(value == "accepted" for value in outcomes.values())
    if ok:
        summary(driftlog, True, "")
        return 0
    failed = sorted(lineage for lineage, value in outcomes.items() if value != "accepted")
    reason = f"{len(failed)} item(s) never reached ACCEPTED within {args.max_rounds} repair round(s): {', '.join(failed)}"
    summary(driftlog, False, reason)
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # unexpected failure outside the modeled guard paths
        print(f"desk_driver_loop: unexpected failure: {exc}", file=sys.stderr)
        raise SystemExit(1)
