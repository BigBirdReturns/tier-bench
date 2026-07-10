#!/usr/bin/env python3
"""Atomically ingest one sealed engine trial into an ARC-C run artifact."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from experiments.breadth.residue_broker import decision_for_task, decisions_for_run  # noqa: E402
from export_solver_packet import sha256  # noqa: E402
from validate_orchestration_run import validate_run  # noqa: E402


def ingest(run_path: Path, packet_receipt_path: Path, grade_receipt_path: Path,
           candidate_path: Path, raw_response_path: Path, grader_outputs_path: Path,
           events_path: Path, rung: str, trial_number: int, repo: Path = REPO) -> dict:
    run = json.loads(run_path.read_text(encoding="utf-8"))
    packet = json.loads(packet_receipt_path.read_text(encoding="utf-8"))
    grade = json.loads(grade_receipt_path.read_text(encoding="utf-8"))
    task_id = packet.get("task_id")
    if task_id not in run.get("task_set", []):
        raise ValueError(f"task {task_id!r} is not in the run task set")
    if grade.get("task_id") != task_id:
        raise ValueError("packet and grade receipts name different tasks")
    for key in ("source_commit", "packet_sha256", "prompt_sha256"):
        if packet.get(key) != grade.get(key):
            raise ValueError(f"packet and grade receipt disagree on {key}")
    if run.get("pairing", {}).get("source_commit") != grade.get("source_commit"):
        raise ValueError("grade receipt source commit does not match the run contract")
    if sha256(candidate_path) != grade.get("candidate_sha256"):
        raise ValueError("candidate file does not match the sealed grade receipt")
    if sha256(raw_response_path) != grade.get("raw_response_sha256"):
        raise ValueError("raw response does not match the sealed grade receipt")
    if sha256(grader_outputs_path) != grade.get("grader_output_sha256"):
        raise ValueError("grader outputs do not match the sealed grade receipt")
    if rung not in run.get("rungs", []):
        raise ValueError(f"unknown normalized rung {rung!r}")
    binding = run["rung_bindings"][rung]
    route = decision_for_task(run.get("trials", []), task_id, run["rungs"], run["k"])
    if route.get("route_to") != rung or route.get("action") not in {"route", "collect_more", "escalate"}:
        raise ValueError(f"broker did not authorize {task_id} at {rung}: {route}")

    sequence = max((row.get("sequence", 0) for row in run.get("trials", [])), default=0) + 1
    engine_id = run["engine"]["engine_id"]
    thread_id = grade.get("thread_id")
    trial_id = f"{engine_id}_{task_id}_{trial_number}"
    artifact_rel = Path("data/orchestration/runs") / run["run_id"] / task_id / f"trial-{trial_number}"
    artifact_dir = repo / artifact_rel
    tmp = artifact_dir.with_name(artifact_dir.name + ".building")
    if artifact_dir.exists() or tmp.exists():
        raise FileExistsError(f"trial artifact already exists: {artifact_dir}")
    tmp.mkdir(parents=True)
    try:
        copies = {
            "candidate.py": candidate_path,
            "raw_response.txt": raw_response_path,
            "grader_outputs.json": grader_outputs_path,
            "packet_receipt.json": packet_receipt_path,
            "grade_receipt.json": grade_receipt_path,
            "events.jsonl": events_path,
        }
        for name, source in copies.items():
            shutil.copy2(source, tmp / name)
        tmp.replace(artifact_dir)

        rel = lambda name: (artifact_rel / name).as_posix()
        hidden = packet["hidden_graders"][0]
        usage = grade.get("usage", {})
        outcome = grade.get("outcome")
        trial = {
            "trial_id": trial_id,
            "sequence": sequence,
            "task_id": task_id,
            "rung": rung,
            "model": binding["model"],
            "effort": binding["effort"],
            "trial": trial_number,
            "solver_id": f"{engine_id}:{thread_id}",
            "executor_surface": binding["surface"],
            "route": {
                "selected_by": "residue_broker", "action": route["action"],
                "decision_state": route["state"], "reason": route["reason"],
                "escalation_from": route["escalation_from"], "evidence": route["evidence"],
            },
            "candidate": {"path": rel("candidate.py"),
                          "sha256": grade["candidate_sha256"],
                          "sealed_before_grading": True},
            "verdict": {
                "outcome": outcome, "source": "coordinator_rerun",
                "rerun_verified": grade.get("hidden_grader_runs") == 2
                                  and grade.get("hidden_grader_deterministic") is True,
                "graded_by": f"coordinator:{grade.get('coordinator_id')}",
                "candidate_sha256": grade["candidate_sha256"],
                "hidden_grader_path": hidden["path"],
                "hidden_grader_sha256": hidden["sha256"],
                "grader_output_path": rel("grader_outputs.json"),
                "grader_output_sha256": grade["grader_output_sha256"],
            },
            "spend": {
                "cost_usd": grade.get("cost_usd", 0.0),
                "cost_basis": grade.get("cost_basis"),
                "input_tokens": int(usage.get("input_tokens", 0) or 0),
                "output_tokens": int(usage.get("output_tokens", 0) or 0),
                "cache_read_tokens": int(usage.get("cached_input_tokens", 0) or 0),
                "reasoning_output_tokens": int(usage.get("reasoning_output_tokens", 0) or 0),
            },
            "replay": {"is_replay": False},
            "abstention": {"abstained": outcome not in {"pass", "fail"},
                           "reason": "non-decisive engine observation" if outcome not in {"pass", "fail"} else ""},
            "provenance": {
                "hidden_grader_visible_to_solver": False,
                "solver_packet_sha256": packet["packet_sha256"],
                "prompt_sha256": packet["prompt_sha256"],
                "solver_thread_id": thread_id,
                "raw_response_path": rel("raw_response.txt"),
                "raw_response_sha256": grade["raw_response_sha256"],
                "event_stream_path": rel("events.jsonl"),
                "event_stream_sha256": sha256(artifact_dir / "events.jsonl"),
            },
        }
        run.setdefault("trials", []).append(trial)
        run["decisions"] = decisions_for_run(run)
        finished = all(d["action"] in {"seal", "abstain"} for d in run["decisions"])
        run["status"] = "sealed" if finished else "partial"
        run["measurement_claim"] = finished
        run["pairing"]["state"] = "independent_run_sealed" if finished else "planned"
        run["burden"]["closure_decision"] = "sealed" if finished else "partial"
        final_count = sum(d["action"] in {"seal", "abstain"} for d in run["decisions"])
        run["burden"]["gap"] = ("none for this engine run; peer comparison remains separate"
                                  if finished else
                                  f"{final_count}/{len(run['task_set'])} tasks final; continue only broker-authorized trials")
        errors = validate_run(run, repo)
        if errors:
            raise ValueError("ingested run failed validation: " + "; ".join(errors))
        temp_run = run_path.with_suffix(run_path.suffix + ".tmp")
        temp_run.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
        temp_run.replace(run_path)
        return trial
    except Exception:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--packet-receipt", type=Path, required=True)
    parser.add_argument("--grade-receipt", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--raw-response", type=Path, required=True)
    parser.add_argument("--grader-outputs", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--rung", required=True)
    parser.add_argument("--trial", type=int, required=True)
    args = parser.parse_args()
    trial = ingest(args.run, args.packet_receipt, args.grade_receipt, args.candidate,
                   args.raw_response, args.grader_outputs, args.events, args.rung,
                   args.trial)
    print(json.dumps(trial, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
