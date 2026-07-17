#!/usr/bin/env python3
"""ARC-C broker and validator tests; stdlib-only, pytest or standalone."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from experiments.breadth.residue_broker import decision_for_task, decisions_for_run  # noqa: E402
import validate_orchestration_run as validator  # noqa: E402
from grade_solver_packet import _events  # noqa: E402

PLAN = REPO / "data/orchestration/arc_c_almanac_v1.json"
SPARK_PLAN = REPO / "data/orchestration/spark_residue_t3_null_filter_v1.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _plan() -> dict:
    run = json.loads(PLAN.read_text(encoding="utf-8"))
    run["status"] = "unmeasured"
    run["measurement_claim"] = False
    run["pairing"]["state"] = "planned"
    run["trials"] = []
    run["burden"]["closure_decision"] = "open"
    run["burden"]["gap"] = "synthetic blank test fixture"
    run["decisions"] = decisions_for_run(run)
    return run


def _trial(run: dict, outcome: str, number: int, rung: str | None = None, **over) -> dict:
    task = run["task_set"][0]
    manifest_item = next(m for m in run["task_manifests"] if m["task_id"] == task)
    manifest = json.loads((REPO / manifest_item["path"]).read_text(encoding="utf-8"))
    hidden = Path(manifest["fixture_dir"]) / manifest["hidden_files"][0]
    candidate = Path("README.md")
    selected_rung = rung or run["rungs"][0]
    binding = run["rung_bindings"][selected_rung]
    decision = decision_for_task(run["trials"], task, run["rungs"], run["k"])
    row = {
        "trial_id": f"{task}_{number}", "sequence": number, "task_id": task,
        "rung": selected_rung, "model": binding["model"], "effort": binding["effort"],
        "trial": number, "solver_id": f"solver-{number}", "executor_surface": binding["surface"],
        "route": {"selected_by": "residue_broker", "action": decision["action"],
                  "decision_state": decision["state"], "reason": decision["reason"],
                  "escalation_from": decision["escalation_from"], "evidence": decision["evidence"]},
        "candidate": {"path": str(candidate).replace("\\", "/"), "sha256": _sha(REPO / candidate),
                      "sealed_before_grading": True},
        "verdict": {"outcome": outcome, "source": "coordinator_rerun", "rerun_verified": True,
                    "graded_by": "coordinator-test", "candidate_sha256": _sha(REPO / candidate),
                    "hidden_grader_path": str(hidden).replace("\\", "/"),
                    "hidden_grader_sha256": _sha(REPO / hidden),
                    "grader_output_path": str(candidate).replace("\\", "/"),
                    "grader_output_sha256": _sha(REPO / candidate)},
        "spend": {"cost_usd": 0.0, "cost_basis": "subscription-derived", "input_tokens": 0,
                  "output_tokens": 0},
        "replay": {"is_replay": False},
        "abstention": {"abstained": outcome not in {"pass", "fail"},
                       "reason": "non-decisive test row" if outcome not in {"pass", "fail"} else ""},
        "provenance": {"hidden_grader_visible_to_solver": False,
                       "solver_packet_sha256": "a" * 64, "prompt_sha256": "b" * 64,
                       "solver_thread_id": f"thread-{number}",
                       "raw_response_path": str(candidate).replace("\\", "/"),
                       "raw_response_sha256": _sha(REPO / candidate)},
    }
    row.update(copy.deepcopy(over))
    return row


def _sync(run: dict) -> None:
    run["decisions"] = decisions_for_run(run)


def test_committed_codex_run_is_sealed_after_source_bound_refill():
    run = json.loads(PLAN.read_text(encoding="utf-8"))
    assert run["status"] == "sealed" and run["measurement_claim"] is True
    assert run["pairing"]["state"] == "pair_sealed"
    assert run["pairing"]["source_commit"] == "3d3837165ac9e046acf2cecc27e01f9c41c302e5"
    assert len(run["trials"]) == 9
    assert all(decision["action"] == "seal" for decision in run["decisions"])
    remaining = validator.validate_run(run)
    assert remaining == [], remaining
    decisions = {d["task_id"]: d for d in run["decisions"]}
    assert set(decisions) == set(run["task_set"])
    assert all(decision["action"] == "seal" for decision in decisions.values())
    assert run["burden"]["closure_decision"] == "sealed"
    assert run["burden"]["gap"] == (
        "none; the sealed peer comparison is preserved as a separate artifact"
    )


def test_validator_admits_source_bound_non_almanac_hidden_manifest():
    run = json.loads(SPARK_PLAN.read_text(encoding="utf-8"))
    assert validator.validate_run(run) == []


def test_ollama_receipt_exposes_identity_and_usage():
    event = {
        "type": "ollama.completed",
        "request_id": "local-test-request",
        "usage": {"input_tokens": 11, "output_tokens": 7},
    }
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "events.jsonl"
        path.write_text(json.dumps(event) + "\n", encoding="utf-8")
        parsed = _events(path)
    assert parsed == {
        "thread_id": "local-test-request",
        "usage": {"input_tokens": 11, "output_tokens": 7},
        "capture_kind": "ollama-local-api-receipt-jsonl",
    }


def test_validator_hashes_manifests_at_pinned_source_commit_not_checkout():
    run = _plan()
    run["pairing"]["source_commit"] = "e416462fdf36c711faf06717212d8de19cd07216"
    errors = validator.validate_run(run)
    assert any("pairing.source_commit" in error for error in errors), errors


def test_three_passes_seal_the_floor():
    run = _plan()
    for i in range(1, 4):
        run["trials"].append(_trial(run, "pass", i))
    decision = decision_for_task(run["trials"], run["task_set"][0], run["rungs"], 3)
    assert decision["state"] == "cleared" and decision["action"] == "seal"
    assert decision["route_to"] == run["rungs"][0]


def test_three_failures_earn_exactly_one_escalation():
    run = _plan()
    for i in range(1, 4):
        run["trials"].append(_trial(run, "fail", i))
    decision = decision_for_task(run["trials"], run["task_set"][0], run["rungs"], 3)
    assert decision["action"] == "escalate"
    assert decision["route_to"] == run["rungs"][1]
    assert decision["escalation_from"] == run["rungs"][0]


def test_mixed_results_abstain_instead_of_escalating():
    run = _plan()
    for i, outcome in enumerate(("pass", "fail", "pass"), 1):
        run["trials"].append(_trial(run, outcome, i))
    decision = decision_for_task(run["trials"], run["task_set"][0], run["rungs"], 3)
    assert decision["state"] == "unstable" and decision["action"] == "collect_more"
    assert decision["abstained"] is True
    assert decision["route_to"] == run["rungs"][0]


def test_noise_can_clear_after_a_fresh_k_window():
    run = _plan()
    for i, outcome in enumerate(("pass", "fail", "pass", "pass", "pass"), 1):
        run["trials"].append(_trial(run, outcome, i))
    decision = decision_for_task(run["trials"], run["task_set"][0], run["rungs"], 3)
    assert decision["state"] == "cleared" and decision["action"] == "seal"


def test_errors_do_not_buy_a_wall():
    run = _plan()
    for i in range(1, 4):
        run["trials"].append(_trial(run, "error", i))
    decision = decision_for_task(run["trials"], run["task_set"][0], run["rungs"], 3)
    assert decision["state"] == "collecting" and decision["action"] == "collect_more"
    assert decision["route_to"] == run["rungs"][0]


def test_validator_rejects_unearned_escalation():
    run = _plan()
    run["status"] = "running"
    run["trials"] = [_trial(run, "pass", 1, rung=run["rungs"][1])]
    _sync(run)
    assert any("was not earned" in e for e in validator.validate_run(run))


def test_validator_rejects_self_grading_and_visible_grader():
    run = _plan()
    run["status"] = "running"
    trial = _trial(run, "pass", 1)
    trial["verdict"]["graded_by"] = trial["solver_id"]
    trial["provenance"]["hidden_grader_visible_to_solver"] = True
    run["trials"] = [trial]
    _sync(run)
    errors = validator.validate_run(run)
    assert any("solver may not award" in e for e in errors)
    assert any("visible_to_solver must be false" in e for e in errors)


def test_codex_subscription_basis_is_named():
    run = _plan()
    run["status"] = "running"
    trial = _trial(run, "pass", 1)
    trial["spend"]["cost_basis"] = "shadow-estimated"
    run["trials"] = [trial]
    _sync(run)
    assert any("subscription-derived" in e for e in validator.validate_run(run))


def test_unavailable_desktop_usage_and_capture_kind_are_honest():
    run = _plan()
    run["status"] = "running"
    trial = _trial(run, "pass", 1)
    trial["spend"].update({
        "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
        "reasoning_output_tokens": 0, "usage_available": False,
        "usage_note": "",
    })
    trial["provenance"]["event_stream_capture_kind"] = "invented-stream"
    run["trials"] = [trial]
    _sync(run)
    errors = validator.validate_run(run)
    assert any("usage_note" in e for e in errors)
    assert any("event_stream_capture_kind" in e for e in errors)

    trial["spend"]["usage_note"] = "token telemetry unavailable; zero fields are sentinels"
    trial["provenance"]["event_stream_capture_kind"] = (
        "coordinator-derived-codex-app-thread-snapshot"
    )
    remaining = validator.validate_run(run)
    assert remaining == [], remaining


def test_replay_requires_distinct_work_item_and_artifact():
    run = _plan()
    run["status"] = "running"
    trial = _trial(run, "pass", 1)
    trial["replay"] = {"is_replay": True, "source_capture_id": "capture-x"}
    run["trials"] = [trial]
    _sync(run)
    errors = validator.validate_run(run)
    assert any("distinct_work_item_id" in e for e in errors)
    assert any("artifact_path" in e for e in errors)


def test_recorded_decisions_must_match_broker():
    run = _plan()
    run["decisions"][0]["action"] = "seal"
    assert any("decisions do not match" in e for e in validator.validate_run(run))


def test_validator_accepts_a_valid_collecting_run():
    run = _plan()
    run["status"] = "running"
    run["trials"].append(_trial(run, "pass", 1))
    _sync(run)
    assert validator.validate_run(run) == []


def test_settled_rung_refuses_redundant_dispatch():
    run = _plan()
    for i in range(1, 4):
        run["trials"].append(_trial(run, "pass", i))
    redundant = _trial(run, "pass", 4)
    run["trials"].append(redundant)
    run["status"] = "running"
    _sync(run)
    assert any("was not earned" in e for e in validator.validate_run(run))


def _run_standalone() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        try:
            test(); print(f"  ok  {test.__name__}")
        except AssertionError as exc:
            failed += 1; print(f"FAIL  {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
