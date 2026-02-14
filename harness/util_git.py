from __future__ import annotations

import subprocess
from pathlib import Path

def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)

def ensure_git_repo(cwd: Path) -> None:
    if (cwd / ".git").exists():
        return
    _run(["git", "init"], cwd)
    _run(["git", "config", "user.email", "harness@example.local"], cwd)
    _run(["git", "config", "user.name", "Harness"], cwd)
    # Exclude build artifacts from diffs
    gitignore = cwd / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("__pycache__/\n*.pyc\n*.pyo\n")

def git_commit_all(cwd: Path, message: str) -> None:
    _run(["git", "add", "-A"], cwd)
    _run(["git", "commit", "-m", message, "--no-gpg-sign"], cwd)

def git_diff_numstat(cwd: Path) -> tuple[int, list[str], list[str]]:
    """Returns (total_lines_changed, changed_files, raw_numstat_lines)."""
    p = _run(["git", "diff", "--numstat"], cwd)
    total = 0
    files: list[str] = []
    raw_lines: list[str] = [ln for ln in p.stdout.splitlines() if ln.strip()]
    for line in raw_lines:
        parts = line.split("\t")
        if len(parts) >= 3:
            ins, dele, fname = parts[0], parts[1], parts[2]
            files.append(fname)
            try:
                total += int(ins) + int(dele)
            except ValueError:
                total += 10_000
    return total, files, raw_lines
