from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
from typing import Any, Callable

from .desk_common import hidden_process_kwargs, now


CLAUDE_USAGE = re.compile(
    r"^\s*(?P<label>[^:\r\n]+):\s*"
    r"(?P<used>100|[0-9]{1,2})\s*%\s*used\s*[·-]\s*"
    r"resets\s+(?P<resets>[^\r\n]*?)\s*$",
    re.MULTILINE,
)


def parse_claude_usage(text: str) -> list[dict[str, Any]]:
    """Parse Claude's built-in /usage display without guessing missing buckets."""
    return [
        {
            "label": match.group("label").strip(),
            "used_percent": int(match.group("used")),
            "resets": match.group("resets").strip(),
        }
        for match in CLAUDE_USAGE.finditer(text)
    ]


def _command(
    argv: list[str], cwd: Path | None = None, timeout: float = 12
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        **hidden_process_kwargs(),
    )


def read_claude_usage(
    cwd: Path,
    runner: Callable[..., subprocess.CompletedProcess[str]] = _command,
) -> dict[str, Any]:
    observed = now()
    executable = shutil.which("claude")
    source = 'claude -p "/usage" --output-format json (zero model tokens)'
    if not executable:
        return {"status": "fail", "source": source, "observed_at": observed, "windows": [], "error": "claude CLI is not on PATH"}
    try:
        result = runner(
            [
                executable,
                "-p",
                "/usage",
                "--output-format",
                "json",
                "--max-budget-usd",
                "0.000001",
                "--no-session-persistence",
            ],
            cwd=cwd,
            timeout=25,
        )
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout or f"exit {result.returncode}").strip())
        payload = json.loads(result.stdout)
        raw = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(raw, str):
            raise RuntimeError("Claude usage response omitted its result text")
        windows = parse_claude_usage(raw)
        if not windows:
            raise RuntimeError("Claude usage format changed; no usage windows parsed")
        return {
            "status": "pass",
            "source": source,
            "observed_at": observed,
            "windows": windows,
            "error": None,
            "raw": raw,
        }
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, RuntimeError) as exc:
        return {"status": "fail", "source": source, "observed_at": observed, "windows": [], "error": str(exc)}


def _reader(stream: Any, messages: queue.Queue[Any] | None = None) -> None:
    try:
        for line in iter(stream.readline, b""):
            if messages is None:
                continue
            try:
                messages.put(json.loads(line.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
    finally:
        stream.close()


def _response(
    messages: queue.Queue[Any], response_id: int, process: subprocess.Popen[bytes], deadline: float
) -> dict[str, Any]:
    while time.monotonic() < deadline:
        try:
            value = messages.get(timeout=min(0.2, max(0.01, deadline - time.monotonic())))
        except queue.Empty:
            if process.poll() is not None:
                break
            continue
        if isinstance(value, dict) and value.get("id") == response_id:
            return value
    raise RuntimeError(f"no Codex app-server response for request {response_id}")


def read_codex_usage(timeout: float = 20) -> dict[str, Any]:
    observed = now()
    source = "codex app-server account/rateLimits/read"
    executable = shutil.which("codex")
    if not executable:
        return {"status": "fail", "source": source, "observed_at": observed, "windows": [], "error": "codex CLI is not on PATH"}
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            [executable, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **hidden_process_kwargs(),
        )
        assert process.stdin is not None and process.stdout is not None and process.stderr is not None
        messages: queue.Queue[Any] = queue.Queue()
        threading.Thread(target=_reader, args=(process.stdout, messages), daemon=True).start()
        threading.Thread(target=_reader, args=(process.stderr,), daemon=True).start()

        def send(value: dict[str, Any]) -> None:
            assert process is not None and process.stdin is not None
            process.stdin.write(json.dumps(value, separators=(",", ":")).encode("utf-8") + b"\n")
            process.stdin.flush()

        deadline = time.monotonic() + timeout
        send({"method": "initialize", "id": 0, "params": {"clientInfo": {"name": "tier-desk", "title": "Tier Desk", "version": "0.1.0"}}})
        initialized = _response(messages, 0, process, deadline)
        if initialized.get("error"):
            raise RuntimeError(f"Codex initialize failed: {initialized['error']}")
        send({"method": "initialized", "params": {}})
        send({"method": "account/rateLimits/read", "id": 1})
        response = _response(messages, 1, process, deadline)
        if response.get("error"):
            raise RuntimeError(f"Codex rate-limit read failed: {response['error']}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("Codex rate-limit response omitted its result")
        buckets = result.get("rateLimitsByLimitId")
        if not isinstance(buckets, dict) or not buckets:
            legacy = result.get("rateLimits")
            buckets = {str((legacy or {}).get("limitId") or "codex"): legacy} if isinstance(legacy, dict) else {}
        windows: list[dict[str, Any]] = []
        for bucket_id, bucket in buckets.items():
            if not isinstance(bucket, dict):
                continue
            primary = bucket.get("primary")
            if not isinstance(primary, dict) or not isinstance(primary.get("usedPercent"), (int, float)):
                continue
            reset = primary.get("resetsAt")
            resets = None
            if isinstance(reset, (int, float)):
                resets = datetime.fromtimestamp(reset, timezone.utc).isoformat().replace("+00:00", "Z")
            windows.append(
                {
                    "label": bucket.get("limitName") or ("Codex" if bucket_id == "codex" else str(bucket_id)),
                    "bucket_id": str(bucket_id),
                    "used_percent": int(primary["usedPercent"]),
                    "resets": resets,
                    "window_minutes": primary.get("windowDurationMins"),
                }
            )
        if not windows:
            raise RuntimeError("Codex returned no readable rate-limit buckets")
        return {"status": "pass", "source": source, "observed_at": observed, "windows": windows, "error": None}
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
        return {"status": "fail", "source": source, "observed_at": observed, "windows": [], "error": str(exc)}
    finally:
        if process is not None:
            try:
                if process.stdin:
                    process.stdin.close()
            except OSError:
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)


def default_estate_roots(repo: Path) -> list[Path]:
    configured = os.environ.get("TIER_DESK_ESTATE_ROOTS")
    if configured:
        return [Path(value).resolve() for value in configured.split(os.pathsep) if value.strip()]
    for candidate in [repo, *repo.parents]:
        if candidate.name.casefold() == "projects":
            return [candidate]
    return [repo.parent]


def _git(repo: Path, *args: str) -> str | None:
    try:
        # The desk may run under a local service account. Trust only this exact
        # discovered repository for this one read; never mutate global Git config.
        result = _command(["git", "-c", f"safe.directory={repo}", *args], cwd=repo, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _queue(repo: Path) -> list[dict[str, str]]:
    path = repo / "docs" / "agents" / "QUEUE.md"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    items: list[dict[str, str]] = []
    indexes: dict[str, int] | None = None
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        normalized = [cell.replace("**", "").strip().casefold() for cell in cells]
        state_name = "state" if "state" in normalized else "status" if "status" in normalized else None
        id_name = "id" if "id" in normalized else None
        title_name = next((name for name in ("task", "work item", "title") if name in normalized), None)
        if state_name and id_name and title_name:
            indexes = {
                "state": normalized.index(state_name),
                "id": normalized.index(id_name),
                "title": normalized.index(title_name),
            }
            continue
        if indexes is None or max(indexes.values()) >= len(cells):
            continue
        if all(set(cell) <= {"-", ":"} for cell in normalized if cell):
            continue
        state = cells[indexes["state"]].replace("**", "").strip().casefold()
        active = state.startswith(("claimed", "open", "blocked"))
        terminal_claim = state.startswith(("claimed+done", "claimed and done"))
        if active and not terminal_claim:
            items.append(
                {
                    "id": cells[indexes["id"]].strip("`"),
                    "title": cells[indexes["title"]],
                    "state": state,
                }
            )
    return items


def _project_paths(root: Path, stop_event: threading.Event | None = None) -> list[Path]:
    try:
        children = [value for value in root.iterdir() if value.is_dir()]
    except OSError:
        return []
    found: set[Path] = set()
    for child in children:
        if stop_event is not None and stop_event.is_set():
            break
        main = child / "main"
        if (main / ".git").exists():
            found.add(main)
            continue
        if (child / ".git").exists() and _git(child, "rev-parse", "--is-inside-work-tree") == "true":
            found.add(child)
            continue
        try:
            nested: list[Path] = []
            for value in child.iterdir():
                if stop_event is not None and stop_event.is_set():
                    break
                if not value.is_dir():
                    continue
                if (value / "main" / ".git").exists():
                    nested.append(value / "main")
                elif (value / ".git").exists() and _git(value, "rev-parse", "--is-inside-work-tree") == "true":
                    nested.append(value)
        except OSError:
            nested = []
        found.update(nested)
    return sorted(found, key=lambda value: str(value).casefold())


def read_estate(
    repo: Path,
    roots: list[Path] | None = None,
    stop_event: threading.Event | None = None,
) -> dict[str, Any]:
    observed = now()
    selected = roots or default_estate_roots(repo)
    projects: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in selected:
        if stop_event is not None and stop_event.is_set():
            return {
                "status": "canceled",
                "source": "local git + docs/agents/QUEUE.md",
                "observed_at": observed,
                "roots": [str(value) for value in selected],
                "projects": projects,
                "error": "estate scan canceled because Tier Desk is stopping",
                "max_parallel_processes": 1,
            }
        for path in _project_paths(root, stop_event):
            if stop_event is not None and stop_event.is_set():
                return {
                    "status": "canceled",
                    "source": "local git + docs/agents/QUEUE.md",
                    "observed_at": observed,
                    "roots": [str(value) for value in selected],
                    "projects": projects,
                    "error": "estate scan canceled because Tier Desk is stopping",
                    "max_parallel_processes": 1,
                }
            identity = str(path.resolve()).casefold()
            if identity in seen:
                continue
            seen.add(identity)
            status = _git(path, "status", "--porcelain=v1", "--untracked-files=normal")
            branch = _git(path, "branch", "--show-current") or _git(path, "rev-parse", "--short", "HEAD") or "unknown"
            last = _git(path, "log", "-1", "--format=%h%x09%cI%x09%s") or ""
            head_sha, _, remainder = last.partition("\t")
            last_at, _, last_subject = remainder.partition("\t")
            open_items = _queue(path)
            worktrees = _git(path, "worktree", "list", "--porcelain") or ""
            projects.append(
                {
                    "name": path.parent.name if path.name.casefold() == "main" else path.name,
                    "path": str(path),
                    "branch": branch,
                    "dirty_count": len(status.splitlines()) if status is not None and status else 0,
                    "status": "ok" if status is not None else "unreadable",
                    "open_items": open_items,
                    "open_count": len(open_items),
                    "worktree_count": sum(1 for line in worktrees.splitlines() if line.startswith("worktree ")),
                    "last_commit_at": last_at or None,
                    "last_commit": last_subject or None,
                    "head_sha": head_sha or None,
                }
            )
    projects.sort(key=lambda item: (item["open_count"] == 0 and item["dirty_count"] == 0, item["name"].casefold()))
    return {
        "status": "pass",
        "source": "local git + docs/agents/QUEUE.md",
        "observed_at": observed,
        "roots": [str(root) for root in selected],
        "projects": projects,
        "error": None,
        "max_parallel_processes": 1,
    }


class DeskSources:
    def __init__(self, repo: Path, *, gauge_ttl: float = 300, estate_ttl: float = 900):
        self.repo = repo
        self.gauge_ttl = gauge_ttl
        self.estate_ttl = estate_ttl
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self._gauge_at = 0.0
        self._estate_at = 0.0
        self._gauges: dict[str, Any] = {}
        self._estate: dict[str, Any] = {}

    def snapshot(self, force: bool = False) -> dict[str, Any]:
        if not self.lock.acquire(blocking=False):
            with self.lock:
                return {"observed_at": now(), "gauges": self._gauges, "estate": self._estate}
        try:
            current = time.monotonic()
            if force or not self._gauges or current - self._gauge_at >= self.gauge_ttl:
                self._gauges = {"claude": read_claude_usage(self.repo), "codex": read_codex_usage()}
                self._gauge_at = time.monotonic()
            if force or not self._estate or current - self._estate_at >= self.estate_ttl:
                self._estate = read_estate(self.repo, stop_event=self.stop_event)
                self._estate_at = time.monotonic()
            return {"observed_at": now(), "gauges": self._gauges, "estate": self._estate}
        finally:
            self.lock.release()

    def stop(self) -> None:
        self.stop_event.set()
        with self.lock:
            pass
