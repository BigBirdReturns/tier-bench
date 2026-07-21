from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
from typing import Any


SCHEMA = "tier-bench/monster-wrangler@1"
TERMINAL = {"ACCEPTED", "REJECTED", "ERROR", "CANCELED", "INTERRUPTED"}
DEFAULTS: dict[str, Any] = {
    "paused": False,
    "pause_reason": "",
    "max_workers": 1,
    "daily_task_limit": 8,
    "daily_cost_limit_usd": 10.0,
    "stop_on_failure": True,
}
MAX_BODY = 1_000_000
MAX_LOG = 200_000


def hidden_process_kwargs(
    platform_name: str = os.name, *, new_process_group: bool = False
) -> dict[str, object]:
    if platform_name == "nt":
        flags = subprocess.CREATE_NO_WINDOW
        if new_process_group:
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP
        return {"creationflags": flags}
    return {}


class DeskError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_json(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value) if value is not None else fallback
    except json.JSONDecodeError:
        return fallback


def safe_scope(raw: str) -> str:
    value = raw.strip().replace("\\", "/")
    if len(value) > 500:
        raise DeskError("repository scopes must be at most 500 characters")
    pure = PurePosixPath(value.rstrip("/"))
    if not value or pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise DeskError(f"unsafe repository scope: {raw!r}")
    if pure.parts[0] == ".git":
        raise DeskError(".git cannot be in task scope")
    return pure.as_posix() + ("/" if value.endswith("/") else "")


def normalize_files(value: Any) -> list[str]:
    if isinstance(value, str):
        values = value.replace(",", "\n").splitlines()
    elif isinstance(value, list):
        values = value
    else:
        raise DeskError("files must be a list or newline-separated string")
    result = sorted({safe_scope(str(item)) for item in values if str(item).strip()})
    if not result:
        raise DeskError("at least one allowed file scope is required")
    if len(result) > 100:
        raise DeskError("at most 100 file scopes are allowed")
    return result


def normalize_dependencies(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        values = value.replace("\n", ",").split(",")
    elif isinstance(value, list):
        values = value
    else:
        raise DeskError("depends_on must be a list or comma-separated string")
    return sorted({str(item).strip() for item in values if str(item).strip()})


def as_bool(value: Any, label: str) -> bool:
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    raise DeskError(f"{label} must be boolean")


def as_int(value: Any, label: str, low: int, high: int) -> int:
    if isinstance(value, bool):
        raise DeskError(f"{label} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise DeskError(f"{label} must be an integer") from exc
    if not low <= result <= high:
        raise DeskError(f"{label} must be between {low} and {high}")
    return result


def as_float(value: Any, label: str, low: float, high: float) -> float:
    if isinstance(value, bool):
        raise DeskError(f"{label} must be a number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DeskError(f"{label} must be a number") from exc
    if not low <= result <= high:
        raise DeskError(f"{label} must be between {low} and {high}")
    return result


def resolve_repo(path: Path) -> Path:
    try:
        result = subprocess.run(
            ["git", "-C", str(path.expanduser()), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            **hidden_process_kwargs(),
        )
    except subprocess.TimeoutExpired as exc:
        raise DeskError(f"timed out resolving Git repository: {path}") from exc
    if result.returncode:
        raise DeskError(f"not a Git repository: {path}: {result.stderr.strip()}")
    return Path(result.stdout.strip()).resolve()


def common_git_dir(repo: Path) -> Path:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
            **hidden_process_kwargs(),
        )
    except subprocess.TimeoutExpired as exc:
        raise DeskError(f"timed out locating Git common directory: {repo}") from exc
    if result.returncode:
        raise DeskError(f"cannot locate Git common directory: {result.stderr.strip()}")
    path = Path(result.stdout.strip())
    return (repo / path).resolve() if not path.is_absolute() else path.resolve()


def committed_blob(repo: Path, relative: str, label: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "cat-file", "blob", f"HEAD:{relative}"],
            cwd=repo,
            capture_output=True,
            timeout=5,
            **hidden_process_kwargs(),
        )
    except subprocess.TimeoutExpired as exc:
        raise DeskError(f"timed out reading committed {label}: {relative}") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise DeskError(f"{label} is not committed at repository HEAD: {relative}: {detail}")
    return result.stdout


def resolve_state_dir(repo: Path, requested: Path | None) -> Path:
    path = requested.expanduser().resolve() if requested else common_git_dir(repo) / "tier-desk"
    path.mkdir(parents=True, exist_ok=True)
    return path
