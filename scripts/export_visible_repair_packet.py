#!/usr/bin/env python3
"""Export one hidden-free repair packet from a sealed visible failure."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from export_solver_packet import REPO, REDACTED_SOLVER_SCOPE, _git_commit, packet_digest, sha256
from harness.task_schema import Task


def _json_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def export_repair_packet(
    manifest_path: Path,
    parent_candidate: Path,
    parent_grade_receipt: Path,
    grader_outputs: Path,
    out: Path,
    receipt_path: Path,
    repo: Path = REPO,
) -> dict:
    manifest_path = manifest_path.resolve()
    parent_candidate = parent_candidate.resolve()
    parent_grade_receipt = parent_grade_receipt.resolve()
    grader_outputs = grader_outputs.resolve()
    out = out.resolve()
    receipt_path = receipt_path.resolve()
    if out.exists() or receipt_path.exists():
        raise FileExistsError("repair packet destinations must not already exist")
    if receipt_path == out or out in receipt_path.parents:
        raise ValueError("coordinator receipt must live outside the solver directory")

    task = Task.from_json(manifest_path)
    if not task.hidden_files or not task.hidden_run_command:
        raise ValueError(f"{task.task_id} is not hidden-graded")
    grade = json.loads(parent_grade_receipt.read_text(encoding="utf-8"))
    if sha256(parent_candidate) != grade.get("candidate_sha256"):
        raise ValueError("parent candidate does not match its sealed grade receipt")
    if sha256(grader_outputs) != grade.get("grader_output_sha256"):
        raise ValueError("grader outputs do not match the sealed grade receipt")
    outputs = json.loads(grader_outputs.read_text(encoding="utf-8"))
    visible = outputs.get("visible")
    if not isinstance(visible, dict):
        raise ValueError("grader outputs do not contain a visible result")
    normalized_visible = dict(visible)
    for key in ("stdout", "stderr"):
        text = normalized_visible.get(key)
        if isinstance(text, str):
            normalized_visible[key] = text.replace(str(repo.resolve()), "<REPO>")
    visible_failure_sha256 = _json_sha256(normalized_visible)

    fixture = (repo / task.fixture_dir).resolve()
    hidden_graders = [fixture / name for name in task.hidden_files]
    tmp = out.with_name(out.name + ".building")
    receipt_tmp = receipt_path.with_name(receipt_path.name + ".building")
    try:
        tmp.mkdir(parents=True)
        target = tmp / task.target_relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(parent_candidate, target)
        prompt = (
            f"Task: Repair {task.target_relpath} using the observed visible failure below.\n\n"
            "Rules:\n"
            f"- Return ONLY the full updated content for {task.target_relpath}.\n"
            "- Do not add commentary or Markdown fences.\n"
            "- Preserve and implement the complete docstring contract, not merely the visible checks.\n"
            "- Do not modify any other file.\n"
            "- The hidden grader is unavailable; do not speculate about hidden test contents.\n\n"
            f"Current file content:\n{target.read_text(encoding='utf-8')}\n\n"
            "Observed visible command result:\n"
            f"command={json.dumps(normalized_visible.get('command'))}\n"
            f"exit={normalized_visible.get('returncode')}\n"
            f"stdout:\n{normalized_visible.get('stdout', '')}\n"
            f"stderr:\n{normalized_visible.get('stderr', '')}\n"
        )
        prompt_path = tmp / "PROMPT.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        visible_files = [
            {"path": path.relative_to(tmp).as_posix(), "sha256": sha256(path)}
            for path in sorted(tmp.rglob("*")) if path.is_file()
        ]
        packet = {
            "schema_version": 1,
            "task_id": task.task_id,
            "source_commit": _git_commit(repo),
            "target_relpath": task.target_relpath,
            "allowed_files": task.allowed_files,
            "run_command": task.run_command,
            "prompt_sha256": sha256(prompt_path),
            "visible_files": visible_files,
            "hidden_material_included": False,
            "repair_stage": 1,
            "parent_candidate_sha256": sha256(parent_candidate),
            "visible_failure_sha256": visible_failure_sha256,
        }
        (tmp / "PACKET.json").write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")
        receipt = {
            "schema_version": 1,
            "task_id": task.task_id,
            "source_commit": packet["source_commit"],
            "manifest_path": manifest_path.relative_to(repo.resolve()).as_posix(),
            "manifest_sha256": sha256(manifest_path),
            "packet_sha256": packet_digest(tmp),
            "prompt_sha256": packet["prompt_sha256"],
            "hidden_graders": [
                {"path": (task.fixture_dir / name).as_posix(), "sha256": sha256(fixture / name)}
                for name in task.hidden_files
            ],
            "solver_scope": REDACTED_SOLVER_SCOPE,
            "peer_conclusions_included": False,
            "repair_stage": 1,
            "parent_candidate_sha256": packet["parent_candidate_sha256"],
            "parent_grade_receipt_sha256": sha256(parent_grade_receipt),
            "visible_failure_sha256": visible_failure_sha256,
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
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--parent-candidate", type=Path, required=True)
    parser.add_argument("--parent-grade-receipt", type=Path, required=True)
    parser.add_argument("--grader-outputs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    receipt = export_repair_packet(
        args.manifest,
        args.parent_candidate,
        args.parent_grade_receipt,
        args.grader_outputs,
        args.out,
        args.receipt,
    )
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
