#!/usr/bin/env python3
"""Export one hidden-free task packet for an independent engine session.

The solver directory contains only visible fixture files, ``PROMPT.md`` and a
safe packet manifest.  The coordinator receipt (which names withheld graders)
must be written outside that directory.  Existing destinations are never
overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from harness.prompting import render_prompt  # noqa: E402
from harness.task_schema import Task  # noqa: E402
from harness.validators import capture_behavior  # noqa: E402

FORBIDDEN_NAMES = {"REFERENCE.py", "NAIVE.py", "control_key.json"}
REDACTED_SOLVER_SCOPE = "<SOLVER_SCOPE>"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit(repo: Path) -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
                            text=True, check=True)
    return result.stdout.strip()


def _files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def packet_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in _files(root):
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8") + b"\0" + bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def export_packet(manifest_path: Path, out: Path, receipt_path: Path,
                  repo: Path = REPO) -> dict:
    manifest_path = manifest_path.resolve()
    out = out.resolve()
    receipt_path = receipt_path.resolve()
    if out.exists():
        raise FileExistsError(f"solver destination already exists: {out}")
    if receipt_path.exists():
        raise FileExistsError(f"coordinator receipt already exists: {receipt_path}")
    if receipt_path == out or out in receipt_path.parents:
        raise ValueError("coordinator receipt must live outside the solver directory")
    try:
        manifest_rel = manifest_path.relative_to(repo.resolve())
    except ValueError as exc:
        raise ValueError("task manifest must be inside the repository") from exc

    task = Task.from_json(manifest_path)
    if not task.hidden_files or not task.hidden_run_command:
        raise ValueError(f"{task.task_id} is not hidden-graded")
    fixture = (repo / task.fixture_dir).resolve()
    hidden_paths = [(fixture / name).resolve() for name in task.hidden_files]
    for hidden in hidden_paths:
        if not hidden.is_file():
            raise FileNotFoundError(f"declared hidden grader missing: {hidden}")

    tmp = out.with_name(out.name + ".building")
    receipt_tmp = receipt_path.with_name(receipt_path.name + ".building")
    if tmp.exists():
        raise FileExistsError(f"temporary packet destination already exists: {tmp}")
    if receipt_tmp.exists():
        raise FileExistsError(f"temporary coordinator receipt already exists: {receipt_tmp}")
    try:
        shutil.copytree(fixture, tmp)
        for name in task.hidden_files:
            (tmp / name).unlink(missing_ok=True)

        # Render only after the hidden files are gone, matching harness.attempt.
        before = capture_behavior(tmp, task.run_command)
        # Tracebacks may embed the temporary packet path. Normalize it so two
        # exports of the same source commit produce the same prompt and digest.
        normalize = lambda text: text.replace(str(tmp), "<SOLVER_ROOT>")
        baseline = {"rc": before[0], "stdout": normalize(before[1]),
                    "stderr": normalize(before[2])}
        prompt = render_prompt(task.prompt_template, tmp, task.target_relpath, baseline)
        # Baseline execution may emit path/timestamp-dependent bytecode. Runtime
        # debris is neither solver context nor evidence and would make identical
        # packets hash differently across exports.
        for cache in sorted(tmp.rglob("__pycache__"), reverse=True):
            shutil.rmtree(cache, ignore_errors=True)
        for bytecode in tmp.rglob("*.py[co]"):
            bytecode.unlink(missing_ok=True)
        (tmp / "PROMPT.md").write_text(prompt, encoding="utf-8")

        hidden_hashes = {sha256(path) for path in hidden_paths}
        for visible in _files(tmp):
            rel = visible.relative_to(tmp)
            if visible.name in FORBIDDEN_NAMES or "key" in {part.lower() for part in rel.parts}:
                raise ValueError(f"forbidden key/reference material in solver packet: {rel}")
            if sha256(visible) in hidden_hashes:
                raise ValueError(f"hidden grader content leaked into solver packet: {rel}")
        for name in task.hidden_files:
            if any(path.relative_to(tmp).as_posix() == Path(name).as_posix() for path in _files(tmp)):
                raise ValueError(f"hidden grader path leaked into solver packet: {name}")

        visible = [
            {"path": path.relative_to(tmp).as_posix(), "sha256": sha256(path)}
            for path in _files(tmp)
        ]
        safe_manifest = {
            "schema_version": 1,
            "task_id": task.task_id,
            "source_commit": _git_commit(repo),
            "target_relpath": task.target_relpath,
            "allowed_files": task.allowed_files,
            "run_command": task.run_command,
            "prompt_sha256": sha256(tmp / "PROMPT.md"),
            "visible_files": visible,
            "hidden_material_included": False,
        }
        (tmp / "PACKET.json").write_text(json.dumps(safe_manifest, indent=2) + "\n",
                                          encoding="utf-8")
        digest = packet_digest(tmp)
        receipt = {
            "schema_version": 1,
            "task_id": task.task_id,
            "source_commit": safe_manifest["source_commit"],
            "manifest_path": manifest_rel.as_posix(),
            "manifest_sha256": sha256(manifest_path),
            "packet_sha256": digest,
            "prompt_sha256": safe_manifest["prompt_sha256"],
            "hidden_graders": [
                {"path": (task.fixture_dir / name).as_posix(),
                 "sha256": sha256(fixture / name)}
                for name in task.hidden_files
            ],
            # The coordinator needs the isolation claim, not a workstation path.
            # Absolute paths leak operator identity and make receipts non-portable.
            "solver_scope": REDACTED_SOLVER_SCOPE,
            "peer_conclusions_included": False,
        }
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_tmp.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        tmp.replace(out)
        receipt_tmp.replace(receipt_path)
        return receipt
    except Exception:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        receipt_tmp.unlink(missing_ok=True)
        if out.exists() and not receipt_path.exists():
            shutil.rmtree(out, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    receipt = export_packet(args.manifest, args.out, args.receipt)
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
