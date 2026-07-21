from __future__ import annotations

import hashlib
import json
import os
from pathlib import PurePosixPath
import re
import shlex
import subprocess
import threading
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .desk_common import DeskError, hidden_process_kwargs, now


POLL_SECONDS = 300
MARKER_PREFIX = "<!-- tier-desk-chair:v1"
MARKER = re.compile(
    r"<!-- tier-desk-chair:v1 request_id=([A-Za-z0-9._-]{1,80}) "
    r"base_sha=([0-9a-f]{40}) -->"
)
SHA = re.compile(r"^[0-9a-f]{40}$")


class GitHubAccessError(RuntimeError):
    def __init__(self, repo: str, surface: str, status: int | None):
        self.repo = repo
        self.surface = surface
        self.status = status
        super().__init__(f"GitHub access unavailable for {repo} via {surface} (status={status})")


class GitHubTransport:
    """Read-only GitHub transport: process-local gh first, anonymous public REST fallback."""

    def __init__(
        self,
        *,
        gh_executable: str | None = None,
        urlopen_fn: Callable[..., Any] = urlopen,
        timeout: float = 15,
    ):
        self.gh_executable = gh_executable or os.environ.get("TIER_DESK_GH", "gh")
        self.urlopen_fn = urlopen_fn
        self.timeout = timeout
        self.last_surface = "none"

    def _gh(self, endpoint: str) -> Any | None:
        try:
            result = subprocess.run(
                [self.gh_executable, "api", "--method", "GET", endpoint],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
                **hidden_process_kwargs(),
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode:
            return None
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
        self.last_surface = "sandbox-child-gh"
        return payload

    def _anonymous(self, repo: str, endpoint: str) -> Any:
        request = Request(
            "https://api.github.com/" + endpoint,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "tier-desk-chair-inbox-v1",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with self.urlopen_fn(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise GitHubAccessError(repo, "gh_then_anonymous", exc.code) from exc
        except (URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
            raise GitHubAccessError(repo, "gh_then_anonymous", None) from exc
        self.last_surface = "anonymous-public-rest"
        return payload

    def _json(self, repo: str, endpoint: str) -> Any:
        payload = self._gh(endpoint)
        return payload if payload is not None else self._anonymous(repo, endpoint)

    def list_open_pulls(self, repo: str) -> list[dict[str, Any]]:
        payload = self._json(repo, f"repos/{repo}/pulls?state=open&per_page=100")
        if not isinstance(payload, list):
            raise GitHubAccessError(repo, self.last_surface, None)
        return [item for item in payload if isinstance(item, dict)]

    def list_pull_files(self, repo: str, number: int) -> tuple[list[str], bool]:
        payload = self._json(repo, f"repos/{repo}/pulls/{number}/files?per_page=100")
        if not isinstance(payload, list):
            raise GitHubAccessError(repo, self.last_surface, None)
        files = [str(item.get("filename", "")) for item in payload if isinstance(item, dict)]
        return files, len(payload) < 100


def chair_prompt(request: dict[str, Any]) -> str:
    paths = "\n".join(f"- {path}" for path in request["allowed_paths"])
    marker = (
        f"<!-- tier-desk-chair:v1 request_id={request['request_id']} "
        f"base_sha={request['base_sha']} -->"
    )
    return (
        "ChatGPT Chair return contract v1\n"
        f"Repository (exact): {request['repo']}\n"
        f"Base commit (exact): {request['base_sha']}\n"
        "Allowed changed paths:\n"
        f"{paths}\n"
        f"Acceptance command: {request['acceptance']}\n"
        f"Auto-validate requested: {str(request['auto_validate']).lower()}\n\n"
        "Create an open GitHub pull request against that exact repository and base commit. "
        "Do not widen the path scope. Put this marker exactly once in the PR body:\n"
        f"{marker}\n"
        "Return the PR URL. Tier Desk will independently bind the repository, PR number, "
        "head SHA, base SHA, changed paths, and marker."
    )


def _safe_acceptance(command: str) -> bool:
    if any(character in command for character in "\r\n;&|><`"):
        return False
    try:
        parts = shlex.split(command, posix=False)
    except ValueError:
        return False
    if not parts:
        return False
    executable = parts[0].lower().strip('"')
    if executable in {"python", "python.exe", "py"}:
        return "-c" not in parts and (
            parts[1:3] == ["-m", "pytest"]
            or (len(parts) > 1 and parts[1] == "-B")
            or (len(parts) > 1 and parts[1].endswith(".py"))
        )
    return executable in {"npm", "npm.cmd"} and len(parts) > 1 and parts[1] in {"test", "run"}


def _path_allowed(path: str, allowed: list[str]) -> bool:
    candidate = PurePosixPath(path)
    if not path or candidate.is_absolute() or ".." in candidate.parts:
        return False
    return any(path == scope or (scope.endswith("/") and path.startswith(scope)) for scope in allowed)


class ChairInbox:
    def __init__(
        self,
        store: Any,
        transport: Any | None,
        wake: Callable[[], None],
        *,
        interval: int = POLL_SECONDS,
    ):
        self.store = store
        self.transport = transport or GitHubTransport()
        self.wake = wake
        self.interval = max(POLL_SECONDS, int(interval))
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.poll_lock = threading.Lock()
        self.last_result: dict[str, Any] | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, name="tier-desk-chair-inbox", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.poll_once()
            except Exception as exc:  # noqa: BLE001
                self.store.event("chair.poll.error", detail={"error_type": type(exc).__name__})
            self.stop_event.wait(self.interval)

    def snapshot(self) -> dict[str, Any]:
        return {
            "poll_interval_seconds": self.interval,
            "last_poll": self.last_result,
            "requests": self.store.list_chair_requests(),
            "returns": self.store.list_chair_returns(),
        }

    def poll_once(self) -> dict[str, Any]:
        with self.poll_lock:
            result = {
                "observed_at": now(),
                "repos": 0,
                "accepted": 0,
                "rejected": 0,
                "deduped": 0,
                "access_errors": 0,
            }
            repos = sorted({row["repo"] for row in self.store.list_chair_requests(active_only=True)})
            for repo in repos:
                result["repos"] += 1
                try:
                    pulls = self.transport.list_open_pulls(repo)
                except GitHubAccessError as exc:
                    result["access_errors"] += 1
                    self.store.event(
                        "chair.poll.access_error",
                        detail={"repo": repo, "surface": exc.surface, "status": exc.status},
                    )
                    continue
                for pr in pulls:
                    outcome = self._process(repo, pr)
                    result[outcome] += 1
            self.last_result = result
            return result

    def _identity(self, pr: dict[str, Any]) -> tuple[int, str]:
        try:
            number = int(pr.get("number"))
        except (TypeError, ValueError):
            number = 0
        head_sha = str(pr.get("head", {}).get("sha", "")).lower()
        if not SHA.fullmatch(head_sha):
            encoded = json.dumps(pr, sort_keys=True, default=str).encode()
            head_sha = "invalid-" + hashlib.sha256(encoded).hexdigest()[:32]
        return number, head_sha

    def _reject(
        self,
        repo: str,
        pr: dict[str, Any],
        reason: str,
        request_id: str | None = None,
        base_sha: str | None = None,
    ) -> str:
        number, head_sha = self._identity(pr)
        self.store.record_chair_return(
            repo=repo,
            pr_number=number,
            head_sha=head_sha,
            request_id=request_id,
            base_sha=base_sha,
            status="REJECTED",
            reason=reason,
            detail={"url": pr.get("html_url")},
        )
        return "rejected"

    def _process(self, repo: str, pr: dict[str, Any]) -> str:
        number, head_sha = self._identity(pr)
        if self.store.chair_return_seen(repo, number, head_sha):
            return "deduped"
        body = str(pr.get("body") or "")
        prefix_count = body.count(MARKER_PREFIX)
        matches = MARKER.findall(body)
        if prefix_count == 0:
            return self._reject(repo, pr, "missing_marker")
        if prefix_count != 1 or len(matches) != 1:
            return self._reject(repo, pr, "duplicate_or_malformed_marker")
        request_id, marker_base = matches[0]
        request = self.store.get_chair_request(request_id)
        if request is None:
            return self._reject(repo, pr, "unknown_request", request_id, marker_base)
        if request["repo"] != repo:
            return self._reject(repo, pr, "wrong_repo", request_id, marker_base)
        pr_base = str(pr.get("base", {}).get("sha", "")).lower()
        base_repo = str(pr.get("base", {}).get("repo", {}).get("full_name", ""))
        if marker_base != request["base_sha"] or pr_base != request["base_sha"] or base_repo != repo:
            return self._reject(repo, pr, "wrong_base", request_id, marker_base)
        head_repo = str(pr.get("head", {}).get("repo", {}).get("full_name", ""))
        if head_repo != repo and not request["allow_forks"]:
            return self._reject(repo, pr, "fork_not_allowed", request_id, marker_base)

        queue_now = False
        changed_files: list[str] = []
        if request["auto_validate"]:
            if not _safe_acceptance(request["acceptance"]):
                return self._reject(repo, pr, "unsafe_acceptance", request_id, marker_base)
            try:
                changed_files, complete = self.transport.list_pull_files(repo, number)
            except GitHubAccessError:
                return self._reject(repo, pr, "changed_files_unavailable", request_id, marker_base)
            if not complete:
                return self._reject(repo, pr, "changed_files_incomplete", request_id, marker_base)
            if not changed_files or not all(
                _path_allowed(path, request["allowed_paths"]) for path in changed_files
            ):
                return self._reject(repo, pr, "changed_paths_outside_contract", request_id, marker_base)
            queue_now = True

        task_id = f"chair-{request_id[:40]}-{number}-{head_sha[:8]}"
        task = self.store.create_task(
            {
                "id": task_id,
                "title": f"Chair return {repo}#{number}",
                "task": (
                    f"Validate the preregistered ChatGPT Chair return {pr.get('html_url')}. "
                    f"Bind repo={repo}, pr={number}, head_sha={head_sha}, base_sha={marker_base}. "
                    "Do not merge, push, checkout, or execute code from the pull request."
                ),
                "files": request["allowed_paths"],
                "acceptance": request["acceptance"],
                "manifest": "pilot_backends.json",
                "arm": "arm_b",
                "priority": 60,
                "queue_now": queue_now,
                "approval_required": False,
            }
        )
        self.store.record_chair_return(
            repo=repo,
            pr_number=number,
            head_sha=head_sha,
            request_id=request_id,
            base_sha=marker_base,
            status="ACCEPTED",
            task_id=task["id"],
            detail={
                "url": pr.get("html_url"),
                "changed_files": changed_files,
                "auto_validate": queue_now,
            },
        )
        if queue_now:
            self.wake()
        return "accepted"
