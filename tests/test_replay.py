#!/usr/bin/env python3
"""Witness tests for scripts/replay.py.

Builds synthetic Git repos with tempfile + a real `git init`; no desk, no
model. scripts/replay.py is invoked only as a subprocess, against the frozen
CLI:

    python -B scripts/replay.py index  --state-dir <dir> --out <index.json> [--json]
    python -B scripts/replay.py lookup --job <job.json> --repo <repo> [--index <index.json>] [--json]
    python -B scripts/replay.py apply  --job <job.json> --repo <repo> [--index <index.json>]

Every receipt here is authored by hand (this test never runs a desk), with
the shape scripts/replay.py's docstring commits to: a receipt.json carrying
{task_id, state, repo, base_commit, files, acceptance_command} plus a
sibling change.patch in the same attempt directory.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPLAY = ROOT / "scripts" / "replay.py"

# A quoted absolute interpreter path is safe to embed in a shell=True command
# string on both cmd.exe and posix shells.
ACCEPTANCE = f'"{sys.executable}" checker.py'

CHECKER_SOURCE = (
    "import pathlib\n"
    "import sys\n"
    "content = pathlib.Path('work.txt').read_text(encoding='utf-8')\n"
    "sys.exit(0 if content == 'after\\n' else 1)\n"
)


def ok(label: str) -> None:
    print(f"ok - {label}")


def run_replay(args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-B", str(REPLAY)] + args
    return subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, (args, result.returncode, result.stdout, result.stderr)
    return result


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8", newline="\n")


def make_repo(parent: Path, *, before: str) -> tuple[Path, str]:
    """A fresh Git repo with work.txt=before and checker.py, committed once."""
    repo = parent / "repo"
    repo.mkdir()
    run_git(["init", "-q"], repo)
    run_git(["config", "user.email", "replay-test@example.invalid"], repo)
    run_git(["config", "user.name", "Replay Test"], repo)
    # Force disk bytes to match Git blob bytes exactly: the whole fingerprint
    # scheme compares a git-cat-file hash (index time) against a disk-read
    # hash (lookup time), so autocrlf normalization would make an unmodified
    # file fingerprint differently at each stage.
    run_git(["config", "core.autocrlf", "false"], repo)
    (repo / "work.txt").write_text(before, encoding="utf-8", newline="\n")
    (repo / "checker.py").write_text(CHECKER_SOURCE, encoding="utf-8", newline="\n")
    run_git(["add", "-A"], repo)
    run_git(["commit", "-q", "-m", "base"], repo)
    base_commit = run_git(["rev-parse", "HEAD"], repo).stdout.strip()
    return repo, base_commit


def make_patch(repo: Path, target_content: str) -> bytes:
    """A patch that turns HEAD's work.txt into target_content; leaves repo at HEAD."""
    work = repo / "work.txt"
    original = work.read_bytes()
    work.write_text(target_content, encoding="utf-8", newline="\n")
    diff = subprocess.run(
        ["git", "diff", "--binary", "--full-index", "HEAD"],
        cwd=str(repo),
        capture_output=True,
    ).stdout
    run_git(["checkout", "--", "work.txt"], repo)
    assert work.read_bytes() == original, "make_patch must leave the repo at its committed state"
    return diff


def write_receipt_and_patch(
    state_dir: Path,
    task_id: str,
    *,
    repo: Path,
    base_commit: str,
    files: list[str],
    acceptance: str,
    patch_bytes: bytes,
    state: str = "ACCEPTED",
) -> Path:
    directory = state_dir / "tier-runs" / "monster-wrangler" / task_id / "attempt-001"
    directory.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema": "tier-bench/tier-run-receipt@1",
        "run_id": f"{task_id}-run",
        "state": state,
        "task_id": task_id,
        "task": f"synthetic task {task_id}",
        "repo": str(repo),
        "base_commit": base_commit,
        "arm": "arm_a",
        "files": files,
        "acceptance_command": acceptance,
        "changes": {"files": files, "scope_violations": []},
    }
    write_json(directory / "receipt.json", receipt)
    (directory / "change.patch").write_bytes(patch_bytes)
    return directory


def write_job(path: Path, files: list[str], acceptance: str) -> None:
    write_json(path, {"objective": "replay test", "files": files, "acceptance": acceptance})


def count_worktrees(repo: Path) -> int:
    listing = run_git(["worktree", "list", "--porcelain"], repo).stdout
    return listing.count("worktree ")


# -- witnesses -------------------------------------------------------------


def test_index_skips_empty_patch(parent: Path) -> None:
    repo, base = make_repo(parent, before="before\n")
    state_dir = parent / "state"
    write_receipt_and_patch(
        state_dir,
        "task-empty",
        repo=repo,
        base_commit=base,
        files=["work.txt"],
        acceptance=ACCEPTANCE,
        patch_bytes=b"",
    )
    out = parent / "index.json"
    result = run_replay(["index", "--state-dir", str(state_dir), "--out", str(out), "--json"])
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    payload = json.loads(result.stdout)
    assert payload["count"] == 0, payload
    index_data = json.loads(out.read_text(encoding="utf-8"))
    assert index_data == {}, index_data
    ok("index_skips_empty_patch: an ACCEPTED receipt with an empty change.patch contributes zero index entries")


def test_same_prestate_same_fingerprint_twice(parent: Path) -> None:
    repo, base = make_repo(parent, before="before\n")
    patch = make_patch(repo, "after\n")
    state_dir = parent / "state"
    write_receipt_and_patch(
        state_dir,
        "task-1",
        repo=repo,
        base_commit=base,
        files=["work.txt"],
        acceptance=ACCEPTANCE,
        patch_bytes=patch,
    )
    index_path = parent / "index.json"
    indexed = run_replay(["index", "--state-dir", str(state_dir), "--out", str(index_path), "--json"])
    assert indexed.returncode == 0, indexed.stdout
    assert json.loads(indexed.stdout)["count"] == 1, indexed.stdout

    job_path = parent / "job.json"
    write_job(job_path, ["work.txt"], ACCEPTANCE)

    first = run_replay(["lookup", "--job", str(job_path), "--repo", str(repo), "--index", str(index_path), "--json"])
    second = run_replay(["lookup", "--job", str(job_path), "--repo", str(repo), "--index", str(index_path), "--json"])
    assert first.returncode == 0 and second.returncode == 0, (first.stdout, second.stdout)
    p1, p2 = json.loads(first.stdout), json.loads(second.stdout)
    assert p1["hit"] is True, p1
    assert p2["hit"] is True, p2
    assert p1["fingerprint"] is not None
    assert p1["fingerprint"] == p2["fingerprint"], (p1, p2)
    ok("same_prestate_same_fingerprint_twice: identical job over identical pre-state fingerprints identically twice")


def test_one_byte_change_causes_fingerprint_miss(parent: Path) -> None:
    repo, base = make_repo(parent, before="before\n")
    patch = make_patch(repo, "after\n")
    state_dir = parent / "state"
    write_receipt_and_patch(
        state_dir,
        "task-1",
        repo=repo,
        base_commit=base,
        files=["work.txt"],
        acceptance=ACCEPTANCE,
        patch_bytes=patch,
    )
    index_path = parent / "index.json"
    run_replay(["index", "--state-dir", str(state_dir), "--out", str(index_path)])
    job_path = parent / "job.json"
    write_job(job_path, ["work.txt"], ACCEPTANCE)

    before_lookup = run_replay(
        ["lookup", "--job", str(job_path), "--repo", str(repo), "--index", str(index_path), "--json"]
    )
    before_payload = json.loads(before_lookup.stdout)
    assert before_payload["hit"] is True, before_payload

    # One byte appended: still a plausible pre-state, but not a byte-identical one.
    (repo / "work.txt").write_text("before!\n", encoding="utf-8", newline="\n")

    after_lookup = run_replay(
        ["lookup", "--job", str(job_path), "--repo", str(repo), "--index", str(index_path), "--json"]
    )
    after_payload = json.loads(after_lookup.stdout)
    assert after_payload["hit"] is False, after_payload
    assert after_payload["fingerprint"] != before_payload["fingerprint"], (before_payload, after_payload)
    ok("one_byte_change_causes_fingerprint_miss: mutating the scoped file changes the fingerprint into a miss")


def test_apply_pass_mutates_repo_and_reports_inference_avoided(parent: Path) -> None:
    repo, base = make_repo(parent, before="before\n")
    patch = make_patch(repo, "after\n")
    state_dir = parent / "state"
    write_receipt_and_patch(
        state_dir,
        "task-1",
        repo=repo,
        base_commit=base,
        files=["work.txt"],
        acceptance=ACCEPTANCE,
        patch_bytes=patch,
    )
    index_path = parent / "index.json"
    run_replay(["index", "--state-dir", str(state_dir), "--out", str(index_path)])
    job_path = parent / "job.json"
    write_job(job_path, ["work.txt"], ACCEPTANCE)

    result = run_replay(["apply", "--job", str(job_path), "--repo", str(repo), "--index", str(index_path)])
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert "inference avoided" in result.stdout, result.stdout
    content = (repo / "work.txt").read_text(encoding="utf-8")
    assert content == "after\n", content
    assert count_worktrees(repo) == 1, "only the main worktree should remain"
    ok(
        "apply_pass_mutates_repo_and_reports_inference_avoided: a re-verified cache hit mutates the "
        "real repo and prints an inference-avoided verdict"
    )


def test_apply_fail_leaves_repo_untouched_and_exits_nonzero(parent: Path) -> None:
    repo, base = make_repo(parent, before="before\n")
    # A stale/wrong cached patch: acceptance checks for "after\n", this patch produces "wrong\n".
    bad_patch = make_patch(repo, "wrong\n")
    state_dir = parent / "state"
    write_receipt_and_patch(
        state_dir,
        "task-bad",
        repo=repo,
        base_commit=base,
        files=["work.txt"],
        acceptance=ACCEPTANCE,
        patch_bytes=bad_patch,
    )
    index_path = parent / "index.json"
    run_replay(["index", "--state-dir", str(state_dir), "--out", str(index_path)])
    job_path = parent / "job.json"
    write_job(job_path, ["work.txt"], ACCEPTANCE)

    before_bytes = (repo / "work.txt").read_bytes()
    result = run_replay(["apply", "--job", str(job_path), "--repo", str(repo), "--index", str(index_path)])
    assert result.returncode != 0, (result.returncode, result.stdout, result.stderr)
    assert "inference NOT avoided" in result.stdout, result.stdout
    after_bytes = (repo / "work.txt").read_bytes()
    assert after_bytes == before_bytes, (before_bytes, after_bytes)
    ok(
        "apply_fail_leaves_repo_untouched_and_exits_nonzero: a cache hit whose acceptance FAILS leaves "
        "the real repo byte-identical and exits nonzero"
    )


def test_worktree_removed_after_apply_both_outcomes(parent: Path) -> None:
    pass_dir = parent / "pass"
    pass_dir.mkdir()
    repo_pass, base_pass = make_repo(pass_dir, before="before\n")
    patch_pass = make_patch(repo_pass, "after\n")
    state_pass = pass_dir / "state"
    write_receipt_and_patch(
        state_pass,
        "task-1",
        repo=repo_pass,
        base_commit=base_pass,
        files=["work.txt"],
        acceptance=ACCEPTANCE,
        patch_bytes=patch_pass,
    )
    index_pass = pass_dir / "index.json"
    run_replay(["index", "--state-dir", str(state_pass), "--out", str(index_pass)])
    job_pass = pass_dir / "job.json"
    write_job(job_pass, ["work.txt"], ACCEPTANCE)
    result_pass = run_replay(["apply", "--job", str(job_pass), "--repo", str(repo_pass), "--index", str(index_pass)])
    assert result_pass.returncode == 0, result_pass.stdout
    assert count_worktrees(repo_pass) == 1, "passing apply must leave no leftover worktree"

    fail_dir = parent / "fail"
    fail_dir.mkdir()
    repo_fail, base_fail = make_repo(fail_dir, before="before\n")
    patch_fail = make_patch(repo_fail, "wrong\n")
    state_fail = fail_dir / "state"
    write_receipt_and_patch(
        state_fail,
        "task-1",
        repo=repo_fail,
        base_commit=base_fail,
        files=["work.txt"],
        acceptance=ACCEPTANCE,
        patch_bytes=patch_fail,
    )
    index_fail = fail_dir / "index.json"
    run_replay(["index", "--state-dir", str(state_fail), "--out", str(index_fail)])
    job_fail = fail_dir / "job.json"
    write_job(job_fail, ["work.txt"], ACCEPTANCE)
    result_fail = run_replay(["apply", "--job", str(job_fail), "--repo", str(repo_fail), "--index", str(index_fail)])
    assert result_fail.returncode != 0, result_fail.stdout
    assert count_worktrees(repo_fail) == 1, "failing apply must leave no leftover worktree"

    ok("worktree_removed_after_apply_both_outcomes: the disposable worktree is gone after both a pass and a fail")


def main() -> int:
    parent = Path(tempfile.mkdtemp(prefix="test-replay-"))
    tests = [
        test_index_skips_empty_patch,
        test_same_prestate_same_fingerprint_twice,
        test_one_byte_change_causes_fingerprint_miss,
        test_apply_pass_mutates_repo_and_reports_inference_avoided,
        test_apply_fail_leaves_repo_untouched_and_exits_nonzero,
        test_worktree_removed_after_apply_both_outcomes,
    ]
    passed = 0
    try:
        for index, test in enumerate(tests):
            case = parent / f"case-{index}"
            case.mkdir()
            test(case)
            passed += 1
        print(f"PASS replay {passed}/{len(tests)}")
        return 0
    except AssertionError as exc:
        print(f"FAIL replay {passed}/{len(tests)}: {exc}")
        return 1
    finally:
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
