"""Rung 0: the zero-inference replay cache over Monster Wrangler receipts.

Every ACCEPTED desk run leaves a receipt at
``<state_dir>/tier-runs/monster-wrangler/<task>/attempt-*/receipt.json``
(with `{task, task_id, files, acceptance_command, base_commit, state,
changes: {files}}`) and a sibling `change.patch`. This module never calls a
model. `index` walks those receipts and builds a lookup table keyed by a
deterministic fingerprint of (acceptance command, declared file scopes,
pre-state content hash of each scope at `base_commit`). `lookup` recomputes
that same fingerprint against a job contract's CURRENT working tree and
reports whether a cached patch exists for that exact pre-state. `apply`
replays a hit.

SAFETY INVARIANT: a cache hit is never trusted on its own. `apply` always
re-decides with the job's own deterministic acceptance command, run fresh in
a disposable `git worktree`, before touching the real repository. A stale or
wrong cached patch costs one throwaway acceptance run in that worktree and
never produces a false accept -- the real repository is mutated only after
the acceptance command has independently exited 0 against the freshly
applied patch. On any miss, apply failure, acceptance failure, or timeout,
the real repository is left byte-for-byte unchanged and the disposable
worktree is always removed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

RECEIPT_GLOB = "tier-runs/monster-wrangler/*/attempt-*/receipt.json"
APPLY_TIMEOUT_SECONDS = 300.0
TIMEOUT_RETURNCODE = 124


class JobError(ValueError):
    """The job contract file is missing a required field or is malformed."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_job(path: Path) -> dict[str, Any]:
    """Load the minimal job-contract fields replay.py needs: files + acceptance."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise JobError(f"cannot read job file: {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise JobError(f"job file is not valid JSON: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise JobError("job contract must be a JSON object")

    files_raw = raw.get("files")
    if not isinstance(files_raw, list) or not files_raw:
        raise JobError('job contract must have a non-empty "files" list')
    files = [str(entry).strip() for entry in files_raw]
    if any(not entry for entry in files):
        raise JobError('job contract "files" entries must be non-empty strings')

    acceptance = raw.get("acceptance")
    if not isinstance(acceptance, str) or not acceptance.strip():
        raise JobError('job contract must have a non-empty "acceptance" string')

    return {"files": files, "acceptance": acceptance.strip()}


# --------------------------------------------------------------------------
# fingerprint
# --------------------------------------------------------------------------


def _is_directory_shaped(entry: str) -> bool:
    """A declared scope is unbounded (directory-shaped), never fingerprinted.

    Matches route.py's judgment: a trailing slash, or a final path component
    carrying no file extension, means a directory scope. Such scopes are
    unusable for a content fingerprint and must be skipped, never guessed.
    """
    normalized = entry.replace("\\", "/").strip()
    if normalized.endswith("/"):
        return True
    tail = normalized.rsplit("/", 1)[-1]
    return bool(tail) and "." not in tail


def compute_fingerprint(
    acceptance: str, files: list[str], read_content: Callable[[str], bytes | None]
) -> str | None:
    """sha256 over the canonical JSON of {acceptance, files, pre_state}.

    `read_content(path)` must return the scoped file's exact bytes, or None
    when the path is unusable (directory scope, unreadable at the relevant
    commit, missing on disk). Any unusable scope makes the whole fingerprint
    unusable: return None rather than guessing a partial hash.
    """
    ordered_files = sorted(files)
    pre_state: list[list[str]] = []
    for path in ordered_files:
        if _is_directory_shaped(path):
            return None
        content = read_content(path)
        if content is None:
            return None
        pre_state.append([path, hashlib.sha256(content).hexdigest()])
    payload = {"acceptance": acceptance, "files": ordered_files, "pre_state": pre_state}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _git_blob_at(repo: Path, base_commit: str, path: str) -> bytes | None:
    """The exact bytes of <base_commit>:<path>, or None if unreadable."""
    try:
        result = subprocess.run(
            ["git", "cat-file", "blob", f"{base_commit}:{path}"],
            cwd=str(repo),
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _disk_content(repo: Path, path: str) -> bytes | None:
    """The exact bytes of <repo>/<path> on disk right now, or None if unreadable."""
    candidate = repo / path
    try:
        if not candidate.is_file():
            return None
        return candidate.read_bytes()
    except OSError:
        return None


# --------------------------------------------------------------------------
# index: build the replay table from receipts already on disk
# --------------------------------------------------------------------------


def _index_one_receipt(receipt_path: Path) -> tuple[str, dict[str, Any]] | None:
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(receipt, dict) or receipt.get("state") != "ACCEPTED":
        return None

    patch_path = receipt_path.parent / "change.patch"
    try:
        patch_bytes = patch_path.read_bytes()
    except OSError:
        return None
    if not patch_bytes.strip():
        return None  # empty patch: nothing to replay, skip

    task_id = receipt.get("task_id")
    acceptance = receipt.get("acceptance_command")
    files = receipt.get("files")
    base_commit = receipt.get("base_commit")
    repo_raw = receipt.get("repo")
    if not isinstance(task_id, str) or not task_id:
        return None
    if not isinstance(acceptance, str) or not acceptance:
        return None
    if not isinstance(files, list) or not files or not all(isinstance(f, str) and f for f in files):
        return None
    if not isinstance(base_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", base_commit):
        return None
    if not isinstance(repo_raw, str) or not repo_raw:
        return None
    repo_path = Path(repo_raw)

    def read_content(path: str, _repo: Path = repo_path, _base: str = base_commit) -> bytes | None:
        return _git_blob_at(_repo, _base, path)

    fingerprint = compute_fingerprint(acceptance, files, read_content)
    if fingerprint is None:
        return None  # directory scope, or unreadable at base_commit: SKIP, never guess

    recorded_at = receipt.get("completed_at") or receipt.get("started_at") or _now()
    entry = {
        "task_id": task_id,
        "patch_path": str(patch_path),
        "acceptance": acceptance,
        "files": sorted(files),
        "recorded_at": recorded_at,
    }
    return fingerprint, entry


def build_index(state_dir: Path) -> dict[str, dict[str, Any]]:
    """Walk every receipt under state_dir and keep the replayable ACCEPTED ones."""
    index: dict[str, dict[str, Any]] = {}
    if not state_dir.exists():
        return index
    for receipt_path in sorted(state_dir.glob(RECEIPT_GLOB)):
        result = _index_one_receipt(receipt_path)
        if result is not None:
            fingerprint, entry = result
            index[fingerprint] = entry
    return index


def default_state_dir(anchor: Path) -> Path | None:
    """The Git common dir (.git of the main checkout) as seen from `anchor`."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(anchor),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout.strip()
    if not raw:
        return None
    path = Path(raw)
    return path.resolve() if path.is_absolute() else (anchor / path).resolve()


def _load_or_build_index(index_arg: Path | None, repo: Path) -> tuple[dict[str, Any], str | None]:
    if index_arg is not None:
        try:
            raw = json.loads(index_arg.read_text(encoding="utf-8"))
        except OSError as exc:
            return {}, f"cannot read index file: {index_arg}: {exc}"
        except json.JSONDecodeError as exc:
            return {}, f"index file is not valid JSON: {index_arg}: {exc}"
        if not isinstance(raw, dict):
            return {}, f"index file must be a JSON object: {index_arg}"
        return raw, None
    state_dir = default_state_dir(repo)
    if state_dir is None:
        return {}, "cannot resolve a default state dir (not inside a Git repository?); pass --index explicitly"
    return build_index(state_dir), None


# --------------------------------------------------------------------------
# apply: replay a hit into a disposable worktree, then the real repo
# --------------------------------------------------------------------------


def _kill_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def _run_acceptance(acceptance: str, cwd: Path, timeout: float) -> tuple[int, str]:
    """Run acceptance with shell=True, PYTHONUTF8=1, and a whole-tree kill on timeout."""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    group_kwargs: dict[str, Any] = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    )
    process = subprocess.Popen(
        acceptance,
        cwd=str(cwd),
        shell=True,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **group_kwargs,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        returncode = process.returncode
    except subprocess.TimeoutExpired:
        _kill_tree(process)
        stdout, stderr = process.communicate()
        returncode = TIMEOUT_RETURNCODE
        stderr = (stderr or "") + f"\nreplay.py: acceptance exceeded {timeout:g}s and was killed (whole tree)\n"
    detail = (stderr or "").strip() or (stdout or "").strip()
    return returncode, detail


def _remove_worktree(repo: Path, worktree: Path, parent: Path) -> None:
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree)],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "worktree", "prune"], cwd=str(repo), capture_output=True, text=True)
    shutil.rmtree(parent, ignore_errors=True)


def _apply_in_disposable_worktree(repo: Path, acceptance: str, patch_bytes: bytes) -> tuple[bool, str]:
    """Apply patch_bytes in a throwaway `git worktree` and run acceptance there.

    Returns (ok, detail). Never touches the real repo. Always removes the
    worktree before returning, on every exit path.
    """
    parent = Path(tempfile.mkdtemp(prefix="replay-worktree-"))
    worktree = parent / "wt"
    try:
        added = subprocess.run(
            ["git", "worktree", "add", "--detach", str(worktree)],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )
        if added.returncode != 0:
            return False, f"git worktree add failed: {added.stderr.strip()}"

        applied = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", "-"],
            input=patch_bytes,
            cwd=str(worktree),
            capture_output=True,
        )
        if applied.returncode != 0:
            detail = applied.stderr.decode("utf-8", errors="replace").strip()
            return False, f"patch failed to apply in the disposable worktree: {detail}"

        returncode, detail = _run_acceptance(acceptance, worktree, APPLY_TIMEOUT_SECONDS)
        if returncode != 0:
            reason = "acceptance timed out" if returncode == TIMEOUT_RETURNCODE else f"acceptance exited {returncode}"
            return False, f"{reason} in the disposable worktree: {detail}"

        return True, "acceptance exited 0 against the freshly applied patch in the disposable worktree"
    finally:
        _remove_worktree(repo, worktree, parent)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def cmd_index(args: argparse.Namespace) -> int:
    if args.state_dir is not None:
        state_dir = args.state_dir.expanduser().resolve()
    else:
        state_dir = default_state_dir(Path.cwd())
        if state_dir is None:
            print(
                "replay.py index: cannot resolve the default --state-dir "
                "(not inside a Git repository?); pass --state-dir explicitly",
                file=sys.stderr,
            )
            return 2

    index = build_index(state_dir)
    out_path = (args.out or Path("index.json")).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(index, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    if args.json:
        payload = {"state_dir": str(state_dir), "out": str(out_path), "count": len(index)}
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"indexed {len(index)} replayable ACCEPTED receipt(s) from {state_dir} -> {out_path}")
    return 0


def cmd_lookup(args: argparse.Namespace) -> int:
    try:
        job = load_job(args.job)
    except JobError as exc:
        print(f"replay.py lookup: {exc}", file=sys.stderr)
        return 2

    repo = args.repo.expanduser().resolve()
    index, err = _load_or_build_index(args.index, repo)
    if err:
        print(f"replay.py lookup: {err}", file=sys.stderr)
        return 2

    fingerprint = compute_fingerprint(job["acceptance"], job["files"], lambda path: _disk_content(repo, path))
    hit = fingerprint is not None and fingerprint in index

    payload: dict[str, Any] = {"hit": hit, "fingerprint": fingerprint}
    if hit:
        entry = index[fingerprint]
        payload["task_id"] = entry.get("task_id")
        payload["patch_path"] = entry.get("patch_path")

    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    elif hit:
        print(f"HIT fingerprint={fingerprint} task_id={payload['task_id']} patch={payload['patch_path']}")
    else:
        print(f"MISS fingerprint={fingerprint if fingerprint is not None else '(unusable job scope)'}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    try:
        job = load_job(args.job)
    except JobError as exc:
        print(f"replay.py apply: {exc}", file=sys.stderr)
        return 2

    repo = args.repo.expanduser().resolve()
    index, err = _load_or_build_index(args.index, repo)
    if err:
        print(f"replay.py apply: {err}", file=sys.stderr)
        return 2

    fingerprint = compute_fingerprint(job["acceptance"], job["files"], lambda path: _disk_content(repo, path))
    if fingerprint is None or fingerprint not in index:
        print("VERDICT: miss -- inference NOT avoided (no cached patch matches the current pre-state)")
        return 1

    entry = index[fingerprint]
    patch_path = Path(str(entry.get("patch_path", "")))
    try:
        patch_bytes = patch_path.read_bytes()
    except OSError as exc:
        print(f"VERDICT: miss -- inference NOT avoided (cannot read cached patch {patch_path}: {exc})")
        return 1
    if not patch_bytes.strip():
        print("VERDICT: miss -- inference NOT avoided (cached patch is empty)")
        return 1

    # Safety invariant: a cache hit is never trusted on its own. Re-decide
    # with the job's own deterministic acceptance command in a disposable
    # worktree before the real repository is touched.
    ok, detail = _apply_in_disposable_worktree(repo, job["acceptance"], patch_bytes)
    if not ok:
        print(
            f"VERDICT: cache hit, but re-verification failed -- inference NOT avoided, "
            f"real repo unchanged ({detail})"
        )
        return 1

    applied = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        input=patch_bytes,
        cwd=str(repo),
        capture_output=True,
    )
    if applied.returncode != 0:
        detail2 = applied.stderr.decode("utf-8", errors="replace").strip()
        print(f"VERDICT: re-verified patch failed to apply to the real repo -- inference NOT avoided ({detail2})")
        return 1

    print(
        f"VERDICT: cache hit, re-verified, applied to the real repo -- inference avoided "
        f"(fingerprint={fingerprint} task_id={entry.get('task_id')} patch={patch_path})"
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="replay.py",
        description="Zero-inference replay cache over Monster Wrangler ACCEPTED receipts.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    index_parser = sub.add_parser("index", help="build the replay lookup table from receipts on disk")
    index_parser.add_argument("--state-dir", type=Path, default=None)
    index_parser.add_argument("--out", type=Path, default=None)
    index_parser.add_argument("--json", action="store_true")

    lookup_parser = sub.add_parser("lookup", help="check whether a job's current pre-state has a cached patch")
    lookup_parser.add_argument("--job", required=True, type=Path)
    lookup_parser.add_argument("--repo", required=True, type=Path)
    lookup_parser.add_argument("--index", type=Path, default=None)
    lookup_parser.add_argument("--json", action="store_true")

    apply_parser = sub.add_parser("apply", help="re-verify and replay a cached patch, avoiding a fresh model call")
    apply_parser.add_argument("--job", required=True, type=Path)
    apply_parser.add_argument("--repo", required=True, type=Path)
    apply_parser.add_argument("--index", type=Path, default=None)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "index":
        return cmd_index(args)
    if args.command == "lookup":
        return cmd_lookup(args)
    if args.command == "apply":
        return cmd_apply(args)
    return 2  # unreachable: argparse enforces a valid subcommand


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # unexpected failure outside the modeled guard paths
        print(f"replay.py: unexpected failure: {exc}", file=sys.stderr)
        raise SystemExit(1)
