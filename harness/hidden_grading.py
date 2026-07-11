from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from harness.task_schema import Task


DEFAULT_HIDDEN_GRADER_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class HiddenGradeResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


def fixture_copy_ignore(_directory: str, names: list[str]) -> set[str]:
    """Exclude interpreter residue from solver and grader working copies."""
    return {name for name in names
            if name == "__pycache__" or name.endswith((".pyc", ".pyo"))}


def run_hidden_grader(
    task: Task,
    repo: Path,
    *,
    timeout: float = DEFAULT_HIDDEN_GRADER_TIMEOUT_SECONDS,
    fixture_dir: Path | None = None,
) -> HiddenGradeResult:
    """Inject, run, and remove a task's withheld grader under a hard deadline."""
    hidden_files = task.hidden_files or []
    source_fixture = fixture_dir or task.fixture_dir
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    try:
        for hidden_file in hidden_files:
            source = source_fixture / hidden_file
            destination = repo / hidden_file
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        try:
            completed = subprocess.run(
                task.hidden_run_command or [],
                cwd=str(repo),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            return HiddenGradeResult(
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        except subprocess.TimeoutExpired as exc:
            return HiddenGradeResult(
                returncode=124,
                stdout=exc.stdout or "",
                stderr=exc.stderr or f"hidden grader timed out after {timeout}s",
                timed_out=True,
            )
    finally:
        for hidden_file in hidden_files:
            path = repo / hidden_file
            if path.is_file() or path.is_symlink():
                path.unlink()
