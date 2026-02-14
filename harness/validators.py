from __future__ import annotations

import fnmatch
import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from harness.util_git import git_diff_numstat

def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)

def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

Snapshot = Tuple[int, str, str]  # (returncode, stdout, stderr)

@dataclass
class ValidationResult:
    compile_ok: bool
    ruff_imports_ok: bool
    functional_equivalence: bool
    diff_lines: int
    changed_files: list[str]
    allowed_files_ok: bool
    max_lines_ok: bool
    tests_ok: bool
    canonical_match: bool | None
    pass_all: bool
    notes: dict

def check_allowed_files(changed_files: list[str], allowed_globs: list[str]) -> bool:
    for f in changed_files:
        ok = any(fnmatch.fnmatch(f, g) for g in allowed_globs)
        if not ok:
            return False
    return True

def capture_behavior(cwd: Path, run_command: list[str]) -> Snapshot:
    p = _run(run_command, cwd)
    return p.returncode, p.stdout, p.stderr

def validate_all(
    cwd: Path,
    target_relpath: str,
    run_command: list[str],
    max_lines_changed: int,
    allowed_files: list[str],
    require_functional_equivalence: bool,
    require_ruff_imports: bool,
    require_compile: bool,
    require_tests: bool,
    before: Optional[Snapshot] = None,
    after: Optional[Snapshot] = None,
) -> ValidationResult:
    compile_ok = True
    if require_compile:
        c = _run(["python", "-m", "compileall", target_relpath], cwd)
        compile_ok = (c.returncode == 0)

    ruff_imports_ok = True
    if require_ruff_imports:
        r = _run(["ruff", "check", "--select", "I", target_relpath], cwd)
        ruff_imports_ok = (r.returncode == 0)

    diff_lines, changed_files, raw_numstat = git_diff_numstat(cwd)
    max_lines_ok = diff_lines <= max_lines_changed
    allowed_files_ok = check_allowed_files(changed_files, allowed_files)

    tests_ok = True
    functional_equivalence = True
    notes: dict = {"diff_numstat": raw_numstat}

    if require_tests or require_functional_equivalence:
        if before is None:
            before = capture_behavior(cwd, run_command)
        if after is None:
            after = capture_behavior(cwd, run_command)

        before_rc, before_out, before_err = before
        after_rc, after_out, after_err = after

        if require_tests:
            tests_ok = (after_rc == 0)

        if require_functional_equivalence:
            functional_equivalence = (
                before_rc == after_rc and before_out == after_out and before_err == after_err
            )

        notes["before_rc"] = before_rc
        notes["after_rc"] = after_rc

    pass_all = (
        compile_ok
        and ruff_imports_ok
        and max_lines_ok
        and allowed_files_ok
        and tests_ok
        and (functional_equivalence if require_functional_equivalence else True)
    )

    return ValidationResult(
        compile_ok=compile_ok,
        ruff_imports_ok=ruff_imports_ok,
        functional_equivalence=functional_equivalence,
        diff_lines=diff_lines,
        changed_files=changed_files,
        allowed_files_ok=allowed_files_ok,
        max_lines_ok=max_lines_ok,
        tests_ok=tests_ok,
        canonical_match=None,
        pass_all=pass_all,
        notes=notes,
    )
