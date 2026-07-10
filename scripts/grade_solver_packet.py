#!/usr/bin/env python3
"""Seal and independently grade one exported solver response twice."""
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
sys.path.insert(0, str(REPO / "scripts"))

from export_solver_packet import packet_digest, sha256  # noqa: E402


def _run(command: list[str], cwd: Path) -> dict:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    return {"command": command, "returncode": result.returncode,
            "stdout": result.stdout, "stderr": result.stderr}


def _events(path: Path | None) -> dict:
    data = {"thread_id": None, "usage": {},
            "capture_kind": "provider-raw-jsonl"}
    if path is None or not path.is_file():
        return data
    raw = path.read_bytes()
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    for line in raw.decode(encoding).splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("capture_kind"):
            data["capture_kind"] = event["capture_kind"]
        if event.get("type") == "thread.started":
            data["thread_id"] = event.get("thread_id")
        if event.get("type") == "turn.completed":
            data["usage"] = event.get("usage", {})
    return data


def grade(receipt_path: Path, solver: Path, raw_response: Path, out_dir: Path,
          coordinator_id: str, events_path: Path | None = None,
          repo: Path = REPO) -> dict:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if packet_digest(solver) != receipt.get("packet_sha256"):
        raise ValueError("solver packet hash drifted after export")
    manifest_path = repo / receipt["manifest_path"]
    if sha256(manifest_path) != receipt.get("manifest_sha256"):
        raise ValueError("task manifest hash drifted after packet export")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if out_dir.exists():
        raise FileExistsError(f"grading output already exists: {out_dir}")
    event_data = _events(events_path)
    tmp = out_dir.with_name(out_dir.name + ".building")
    if tmp.exists():
        raise FileExistsError(f"temporary grading output already exists: {tmp}")
    try:
        work = tmp / "work"
        shutil.copytree(solver, work)
        target = work / manifest["target_relpath"]
        target.write_text(raw_response.read_text(encoding="utf-8"), encoding="utf-8")
        candidate_hash = sha256(target)

        compile_result = _run([sys.executable, "-m", "py_compile", manifest["target_relpath"]], work)
        visible_result = _run(list(manifest["run_command"]), work)
        for hidden in manifest["hidden_files"]:
            shutil.copy2(repo / manifest["fixture_dir"] / hidden, work / hidden)
        hidden_one = _run(list(manifest["hidden_run_command"]), work)
        hidden_two = _run(list(manifest["hidden_run_command"]), work)
        deterministic = hidden_one == hidden_two
        passed = (compile_result["returncode"] == 0 and visible_result["returncode"] == 0
                  and hidden_one["returncode"] == 0 and hidden_two["returncode"] == 0
                  and deterministic)

        outputs = {"compile": compile_result, "visible": visible_result,
                   "hidden_1": hidden_one, "hidden_2": hidden_two}
        outputs_path = tmp / "grader-outputs.json"
        outputs_path.write_text(json.dumps(outputs, indent=2, ensure_ascii=False) + "\n",
                                encoding="utf-8")
        grade_receipt = {
            "schema_version": 1, "task_id": receipt["task_id"],
            "source_commit": receipt["source_commit"],
            "packet_sha256": receipt["packet_sha256"],
            "prompt_sha256": receipt["prompt_sha256"],
            "candidate_sha256": candidate_hash,
            "raw_response_sha256": sha256(raw_response),
            "thread_id": event_data["thread_id"], "usage": event_data["usage"],
            "usage_available": bool(event_data["usage"]),
            "event_stream_capture_kind": event_data["capture_kind"],
            "coordinator_id": coordinator_id,
            "solver_equals_grader": event_data["thread_id"] == coordinator_id,
            "grader_output_sha256": sha256(outputs_path),
            "hidden_grader_sha256": receipt["hidden_graders"][0]["sha256"],
            "hidden_grader_runs": 2, "hidden_grader_deterministic": deterministic,
            "outcome": "pass" if passed else "fail",
            "visible_returncode": visible_result["returncode"],
            "hidden_returncodes": [hidden_one["returncode"], hidden_two["returncode"]],
            "cost_basis": "subscription-derived", "cost_usd": 0.0,
        }
        if grade_receipt["solver_equals_grader"]:
            grade_receipt["outcome"] = "error"
        (tmp / "grade-receipt.json").write_text(
            json.dumps(grade_receipt, indent=2) + "\n", encoding="utf-8")
        tmp.replace(out_dir)
        return grade_receipt
    except Exception:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--solver", type=Path, required=True)
    parser.add_argument("--raw-response", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--events", type=Path)
    parser.add_argument("--coordinator-id", required=True)
    args = parser.parse_args()
    result = grade(args.receipt, args.solver, args.raw_response, args.out,
                   args.coordinator_id, args.events)
    print(json.dumps(result, indent=2))
    return 0 if result["outcome"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
