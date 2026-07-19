# MACHINE-GENERATED characterization test (gpt-5.3-codex-spark), mutation-verified.
# module=harness\validators.py  mutation_score=5/6
# Pins CURRENT behavior; review before trusting.
from __future__ import annotations
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "harness"))

import sys
import types
import subprocess
import tempfile
from pathlib import Path

import util_git

harness_module = types.ModuleType("harness")
harness_util_git = types.ModuleType("harness.util_git")
harness_util_git.git_diff_numstat = util_git.git_diff_numstat
harness_module.util_git = harness_util_git

sys.modules["harness"] = harness_module
sys.modules["harness.util_git"] = harness_util_git

from validators import ValidationResult, capture_behavior, check_allowed_files, sha256_text, validate_all
import validators


def _completion(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _tmp_repo_file(content: str, name: str = "target.py") -> tuple[tempfile.TemporaryDirectory, Path]:
    temp_dir_obj = tempfile.TemporaryDirectory()
    temp_dir = Path(temp_dir_obj.name)
    target = temp_dir / name
    target.write_text(content)
    return temp_dir_obj, target


def test_sha256_text():
    assert sha256_text("") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert sha256_text("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert sha256_text("😀") == "f0443a342c5ef54783a111b51ba56c938e474c32324d90c3a60c9c8e3a37e2d9"


def test_check_allowed_files():
    assert check_allowed_files([], ["*"]) is True
    assert check_allowed_files(["src/main.py"], ["src/*.py"]) is True
    assert check_allowed_files(["docs/readme.md", "src/main.py"], ["src/*.py"]) is False


def test_capture_behavior_success_and_error():
    cwd = Path.cwd()
    rc, out, err = capture_behavior(cwd, ["python", "-c", "print('ok', end='')"])
    assert rc == 0
    assert out == "ok"
    assert err == ""

    rc, out, err = capture_behavior(
        cwd, ["python", "-c", "import sys; print('err', file=sys.stderr); sys.exit(3)"]
    )
    assert rc == 3
    assert out == ""
    assert err == "err\n"


def test_validate_all_public_defaults_and_notes():
    original_git = validators.git_diff_numstat
    validators.git_diff_numstat = lambda cwd: (0, ["main.py"], "1\t1\tmain.py")

    try:
        result = validate_all(
            cwd=Path.cwd(),
            target_relpath="foo.py",
            run_command=["python", "-c", "print('run')"],
            max_lines_changed=5,
            allowed_files=["*.py"],
            require_functional_equivalence=False,
            require_ruff_imports=False,
            require_compile=False,
            require_tests=False,
        )
    finally:
        validators.git_diff_numstat = original_git

    assert isinstance(result, ValidationResult)
    assert result.compile_ok is True
    assert result.ruff_imports_ok is True
    assert result.functional_equivalence is True
    assert result.diff_lines == 0
    assert result.changed_files == ["main.py"]
    assert result.allowed_files_ok is True
    assert result.max_lines_ok is True
    assert result.tests_ok is True
    assert result.canonical_match is None
    assert result.notes == {"diff_numstat": "1\t1\tmain.py"}
    assert result.pass_all is True


def test_validate_all_max_lines_and_allowed_files_boundaries():
    original_run = validators._run
    original_git = validators.git_diff_numstat
    validators._run = lambda cmd, cwd: _completion(0, "", "")
    validators.git_diff_numstat = lambda cwd: (3, ["src/main.py"], "3\t0\tsrc/main.py")

    try:
        result = validate_all(
            cwd=Path.cwd(),
            target_relpath="foo.py",
            run_command=["python", "-c", "print('run')"],
            max_lines_changed=3,
            allowed_files=["src/*.py"],
            require_functional_equivalence=False,
            require_ruff_imports=False,
            require_compile=False,
            require_tests=False,
        )
    finally:
        validators._run = original_run
        validators.git_diff_numstat = original_git

    assert result.max_lines_ok is True
    assert result.allowed_files_ok is True
    assert result.pass_all is True

    original_run = validators._run
    original_git = validators.git_diff_numstat
    validators._run = lambda cmd, cwd: _completion(0, "", "")
    validators.git_diff_numstat = lambda cwd: (4, ["src/main.py"], "3\t0\tsrc/main.py")

    try:
        result = validate_all(
            cwd=Path.cwd(),
            target_relpath="foo.py",
            run_command=["python", "-c", "print('run')"],
            max_lines_changed=3,
            allowed_files=["src/*.py"],
            require_functional_equivalence=False,
            require_ruff_imports=False,
            require_compile=False,
            require_tests=False,
        )
    finally:
        validators._run = original_run
        validators.git_diff_numstat = original_git

    assert result.max_lines_ok is False
    assert result.pass_all is False


def test_validate_all_checks_compile_gate():
    original_run = validators._run
    original_git = validators.git_diff_numstat

    def fake_run(cmd, cwd):
        if cmd[:3] == ["python", "-m", "compileall"]:
            return _completion(1, "", "compile fail")
        return _completion(0, "", "")

    validators._run = fake_run
    validators.git_diff_numstat = lambda cwd: (0, ["main.py"], "0\t0\tmain.py")

    temp_dir_obj, target = _tmp_repo_file("not complete syntax =\n", name="broken.py")
    try:
        result = validate_all(
            cwd=Path(temp_dir_obj.name),
            target_relpath=target.name,
            run_command=["python", "-c", "print('run')"],
            max_lines_changed=10,
            allowed_files=["*.py"],
            require_functional_equivalence=False,
            require_ruff_imports=False,
            require_compile=True,
            require_tests=False,
        )
    finally:
        temp_dir_obj.cleanup()
        validators._run = original_run
        validators.git_diff_numstat = original_git

    assert result.compile_ok is False
    assert result.pass_all is False


def test_validate_all_functional_and_tests_checks_with_supplied_snapshots():
    original_run = validators._run
    original_git = validators.git_diff_numstat
    validators._run = lambda cmd, cwd: _completion(0, "", "")
    validators.git_diff_numstat = lambda cwd: (1, ["src/main.py"], "1\t0\tsrc/main.py")

    try:
        result = validate_all(
            cwd=Path.cwd(),
            target_relpath="foo.py",
            run_command=["python", "-c", "print('run')"],
            max_lines_changed=5,
            allowed_files=["src/*.py"],
            require_functional_equivalence=True,
            require_ruff_imports=False,
            require_compile=False,
            require_tests=True,
            before=(0, "before", "stderr-before"),
            after=(1, "after", "stderr-after"),
        )
    finally:
        validators._run = original_run
        validators.git_diff_numstat = original_git

    assert result.functional_equivalence is False
    assert result.tests_ok is False
    assert result.pass_all is False
    assert result.notes["before_rc"] == 0
    assert result.notes["after_rc"] == 1


def test_validate_all_captures_behavior_when_snapshots_missing_and_compares_output():
    original_run = validators._run
    original_git = validators.git_diff_numstat

    calls = []

    def fake_run(cmd, cwd):
        calls.append(cmd)
        if cmd[:3] == ["python", "-c", "print('run')"]:
            return _completion(0, "run\n", "")
        return _completion(0, "", "")

    validators._run = fake_run
    validators.git_diff_numstat = lambda cwd: (0, [], "0\t0\t")

    result = validate_all(
        cwd=Path.cwd(),
        target_relpath="foo.py",
        run_command=["python", "-c", "print('run')"],
        max_lines_changed=1,
        allowed_files=["*.py"],
        require_functional_equivalence=True,
        require_ruff_imports=False,
        require_compile=False,
        require_tests=False,
    )
    validators._run = original_run
    validators.git_diff_numstat = original_git

    assert len(calls) == 2
    assert result.functional_equivalence is True
    assert result.tests_ok is True
    assert result.pass_all is True


def main() -> None:
    test_sha256_text()
    test_check_allowed_files()
    test_capture_behavior_success_and_error()
    test_validate_all_public_defaults_and_notes()
    test_validate_all_max_lines_and_allowed_files_boundaries()
    test_validate_all_checks_compile_gate()
    test_validate_all_functional_and_tests_checks_with_supplied_snapshots()
    test_validate_all_captures_behavior_when_snapshots_missing_and_compares_output()
    print("OK")


if __name__ == "__main__":
    main()
