from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile

from tier_runner.manifest import ManifestError
from tier_runner.pilot_composition import (
    CALL_SCHEMA,
    CompositionError,
    answer_operator_question,
    append_driver_traces,
    new_pilot_arm_state,
    record_acceptance,
    record_pilot_call,
    render_next_prompt,
)
from tier_runner.pilot_manifest import PilotComposition, load_pilot_composition


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _raises(kind: type[Exception], function, *args, **kwargs) -> str:
    try:
        function(*args, **kwargs)
    except kind as exc:
        return str(exc)
    raise AssertionError(f"expected {kind.__name__}")


def make_composition(root: Path) -> tuple[PilotComposition, Path]:
    prompts = {
        "frontier_driver": "Plan {{TASK}} {{FILES}} {{ACCEPTANCE}} {{BASE_COMMIT}}\n",
        "cheap_driver": "Plan cheaply {{TASK}} {{FILES}} {{ACCEPTANCE}} {{BASE_COMMIT}}\n",
        "hands": (
            "Implement {{TASK}} {{FILES}} {{ACCEPTANCE}} {{BASE_COMMIT}}\n"
            "Frozen driver plan:\n{{DRIVER_PLAN}}\n"
        ),
        "frontier_repair": (
            "Repair {{TASK}} {{FILES}} {{ACCEPTANCE}} {{BASE_COMMIT}}\n"
            "Candidate:\n{{CANDIDATE_OUTPUT}}\nFailure:\n{{FAILED_ACCEPTANCE_REPORT}}\n"
        ),
        "cheap_repair": (
            "Repair cheaply {{TASK}} {{FILES}} {{ACCEPTANCE}} {{BASE_COMMIT}}\n"
            "Candidate:\n{{CANDIDATE_OUTPUT}}\nFailure:\n{{FAILED_ACCEPTANCE_REPORT}}\n"
        ),
        "escalate": (
            "Escalate {{TASK}} {{FILES}} {{ACCEPTANCE}} {{BASE_COMMIT}}\n"
            "Candidate:\n{{CANDIDATE_OUTPUT}}\nFailure:\n{{FAILED_ACCEPTANCE_REPORT}}\n"
        ),
        "operator_question": (
            "Task {{TASK_ID}} needs one operator decision.\n"
            "Question: {{QUESTION}}\nEvidence: {{EVIDENCE_SHA256}}\n"
        ),
        "hands_resume": (
            "Resume {{TASK}} {{FILES}} {{ACCEPTANCE}} {{BASE_COMMIT}} "
            "{{QUESTION}} {{ANSWER}}\nCandidate: {{CANDIDATE_OUTPUT}}\n"
            "Failure: {{FAILED_ACCEPTANCE_REPORT}}\n"
        ),
    }
    prompt_entries: dict[str, dict[str, str]] = {}
    prompt_dir = root / ".tier"
    prompt_dir.mkdir(parents=True)
    for name, content in prompts.items():
        path = prompt_dir / f"{name}.txt"
        path.write_text(content, encoding="utf-8", newline="\n")
        prompt_entries[name] = {
            "path": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    command = [
        "fixture-adapter",
        "--arm", "{arm}",
        "--stage", "{stage}",
        "--dispatch", "{dispatch_receipt}",
        "--prompt", "{prompt}",
        "--result", "{result}",
        "--worktree", "{worktree}",
    ]

    def backend(model: str, tier: str) -> dict:
        return {
            "model_id": model,
            "effort": "low",
            "surface": "fixture",
            "cost_basis": "shadow-estimated",
            "account": f"{model}-account",
            "tier": tier,
            "adapter": {"command": command},
        }

    manifest = {
        "schema": "tier-bench/pilot-backends@2",
        "protocol_commit": "076fd1e3d97c22f7c33933c5dee4ff897d7ba4e6",
        "isolation": {
            "fresh_session_per_call": True,
            "instruction_files": False,
            "auto_memory": False,
            "conversation_carryover": False,
        },
        "tool_versions": {"fixture-adapter": "1"},
        "prompt_templates": prompt_entries,
        "backends": {
            "frontier": backend("fixture-frontier", "frontier"),
            "cheap_driver": backend("fixture-cheap-driver", "cheap"),
            "cheap_hands": backend("fixture-cheap-hands", "cheap"),
            "escalation": backend("fixture-escalation", "frontier"),
        },
        "arms": {
            "arm_a": {
                "mode": "frontier_driver",
                "driver": {"backend": "frontier", "prompt_template": "frontier_driver"},
                "hands": {"backend": "cheap_hands", "prompt_template": "hands"},
                "repair": {
                    "backend": "frontier",
                    "prompt_template": "frontier_repair",
                    "max_calls": 1,
                },
                "escalations": [
                    {"backend": "escalation", "prompt_template": "escalate"}
                ],
                "driver_trace": {"required": True, "path": "driver_traces.jsonl"},
            },
            "arm_b": {
                "mode": "cheap_driver",
                "driver": {"backend": "cheap_driver", "prompt_template": "cheap_driver"},
                "hands": {"backend": "cheap_hands", "prompt_template": "hands"},
                "repair": {
                    "backend": "cheap_driver",
                    "prompt_template": "cheap_repair",
                    "max_calls": 1,
                },
                "escalations": [
                    {"backend": "escalation", "prompt_template": "escalate"}
                ],
            },
            "arm_c": {
                "mode": "operator_routed",
                "hands": {"backend": "cheap_hands", "prompt_template": "hands"},
                "repair": {
                    "backend": "cheap_hands",
                    "prompt_template": "cheap_repair",
                    "max_calls": 1,
                },
                "escalations": [],
                "question_route": {
                    "question_template": "operator_question",
                    "resume_prompt_template": "hands_resume",
                    "max_questions": 2,
                },
            },
        },
    }
    path = root / "pilot_backends.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return load_pilot_composition(path), path


def call_receipt(
    composition: PilotComposition,
    state: dict,
    *,
    output: str,
    outcome: str = "completed",
    session: str | None = None,
) -> dict:
    arm = composition.arms[state["arm"]]
    stage = state["next_stage"]
    if stage == "driver_plan":
        frozen = arm.driver
    elif stage == "hands":
        frozen = arm.hands
    elif stage == "repair":
        frozen = arm.repair
    elif stage == "escalation":
        frozen = arm.escalations[state["escalation_index"]]
    elif stage == "hands_resume":
        frozen = type(arm.hands)(arm.hands.backend, arm.question_route.resume_prompt_template)
    else:
        raise AssertionError(stage)
    assert frozen is not None
    backend = composition.backends[frozen.backend]
    call_id = f"{state['arm']}-{stage}-{len(state['calls']) + 1}"
    session = session or f"session-{call_id}"
    dispatch_hash = _sha(f"dispatch-{call_id}")
    prompt_hash = composition.templates[frozen.prompt_template].sha256
    rendered_prompt_hash = hashlib.sha256(render_next_prompt(composition, state)).hexdigest()
    output_kind = (
        "question"
        if outcome == "question"
        else "error"
        if outcome == "error"
        else "plan"
        if stage == "driver_plan"
        else "candidate_patch"
    )
    ledger = {
        "ts": "2026-07-13T00:00:00Z",
        "account": backend.account,
        "model": backend.model_id,
        "tier": backend.tier,
        "task_id": state["task_id"],
        "phase": state["arm"],
        "outcome": "pass" if outcome != "error" else "error",
        "effort": backend.effort,
        "input_tokens": 1,
        "output_tokens": 1,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": 0.0,
        "latency_ms": 1.0,
        "trial": len(state["calls"]),
        "note": backend.cost_basis,
        "extra": {
            "backend_manifest_sha256": composition.sha256,
            "backend_surface": backend.surface,
            "cost_basis": backend.cost_basis,
            "dispatch_receipt_sha256": dispatch_hash,
            "prompt_template_sha256": prompt_hash,
            "runtime_model_id": backend.model_id,
            "session_id": session,
            "telemetry_complete": True,
            "tool_versions": composition.tool_versions,
        },
    }
    return {
        "schema": CALL_SCHEMA,
        "call_id": call_id,
        "task_id": state["task_id"],
        "arm": state["arm"],
        "stage": stage,
        "attempt": 1 + sum(call["stage"] == stage for call in state["calls"]),
        "backend": frozen.backend,
        "prompt_template": {"name": frozen.prompt_template, "sha256": prompt_hash},
        "prompt_sha256": rendered_prompt_hash,
        "dispatch_receipt_sha256": dispatch_hash,
        "session_id": session,
        "outcome": outcome,
        "output": {"kind": output_kind, "text": output, "sha256": _sha(output)},
        "ledger_call": ledger,
    }


def arm_state(composition: PilotComposition, task_id: str, task_tier: str, arm: str) -> dict:
    return new_pilot_arm_state(
        composition,
        task_id=task_id,
        task_tier=task_tier,
        arm=arm,
        task="Implement the fixture change",
        files=["src/example.py"],
        acceptance_command="python -m pytest -q",
        base_commit="a" * 40,
    )


def test_manifest_locks_roles_and_common_hands(root: Path) -> None:
    composition, path = make_composition(root)
    assert composition.arms["arm_a"].mode == "frontier_driver"
    assert composition.arms["arm_b"].mode == "cheap_driver"
    assert composition.arms["arm_c"].driver is None
    assert len({composition.arms[arm].hands for arm in composition.arms}) == 1

    value = json.loads(path.read_text(encoding="utf-8"))
    value["arms"]["arm_c"]["hands"]["backend"] = "cheap_driver"
    value["arms"]["arm_c"]["repair"]["backend"] = "cheap_driver"
    path.write_text(json.dumps(value), encoding="utf-8")
    assert "identical cheap-hands" in _raises(ManifestError, load_pilot_composition, path)


def test_arm_a_repairs_and_emits_driver_trace(root: Path) -> None:
    composition, _ = make_composition(root)
    state = arm_state(composition, "real-01", "T2", "arm_a")
    state = record_pilot_call(composition, state, call_receipt(composition, state, output="plan"))
    assert state["next_stage"] == "hands"
    assert b"Frozen driver plan:\nplan" in render_next_prompt(composition, state)
    state = record_pilot_call(
        composition, state, call_receipt(composition, state, output="first patch")
    )
    state = record_acceptance(composition, state, passed=False, report="tests failed")
    assert state["next_stage"] == "repair"
    repair_prompt = render_next_prompt(composition, state)
    assert b"Candidate:\nfirst patch" in repair_prompt
    assert b"Failure:\ntests failed" in repair_prompt
    state = record_pilot_call(
        composition, state, call_receipt(composition, state, output="repaired patch")
    )
    state = record_acceptance(composition, state, passed=True, report="tests passed")
    assert state["status"] == "COMPLETE"
    assert len(state["calls"]) == 3
    assert len(state["driver_traces"]) == 1
    trace = state["driver_traces"][0]
    assert trace["hands_output"] == "first patch"
    assert trace["validator_report"] == "tests failed"
    assert trace["driver_output"] == "repaired patch"
    assert trace["passed"] is True
    traces = root / "driver_traces.jsonl"
    assert append_driver_traces(composition, root, state) == 1
    assert append_driver_traces(composition, root, state) == 0
    assert json.loads(traces.read_text(encoding="utf-8"))["trace_sha256"] == trace["trace_sha256"]


def test_arm_b_failure_escalates_only_after_repair(root: Path) -> None:
    composition, _ = make_composition(root)
    state = arm_state(composition, "real-02", "T2", "arm_b")
    state = record_pilot_call(composition, state, call_receipt(composition, state, output="cheap plan"))
    state = record_pilot_call(composition, state, call_receipt(composition, state, output="patch"))
    state = record_acceptance(composition, state, passed=False, report="first fail")
    assert state["next_stage"] == "repair"
    state = record_pilot_call(composition, state, call_receipt(composition, state, output="cheap repair"))
    state = record_acceptance(composition, state, passed=False, report="repair failed")
    assert state["next_stage"] == "escalation"
    escalation_prompt = render_next_prompt(composition, state)
    assert b"Candidate:\ncheap repair" in escalation_prompt
    assert b"Failure:\nrepair failed" in escalation_prompt
    state = record_pilot_call(composition, state, call_receipt(composition, state, output="escalated repair"))
    state = record_acceptance(composition, state, passed=True, report="escalation passed")
    assert state["status"] == "COMPLETE"
    assert not state["driver_traces"]


def test_arm_c_question_answer_resume_has_no_driver(root: Path) -> None:
    composition, _ = make_composition(root)
    state = arm_state(composition, "real-03", "T1", "arm_c")
    assert state["next_stage"] == "hands"
    assert b"NO_MODEL_DRIVER" in render_next_prompt(composition, state)
    state = record_pilot_call(
        composition,
        state,
        call_receipt(composition, state, output="Should the parser preserve blanks?", outcome="question"),
    )
    assert state["status"] == "WAITING_OPERATOR"
    assert state["active_question_id"]
    question = state["questions"][0]
    assert "Should the parser preserve blanks?" in question["rendered"]
    state = answer_operator_question(
        composition,
        state,
        question_id=state["active_question_id"],
        answer="Yes, preserve blanks.",
    )
    assert state["next_stage"] == "hands_resume"
    resume_prompt = render_next_prompt(composition, state)
    assert b"Should the parser preserve blanks?" in resume_prompt
    assert b"Yes, preserve blanks." in resume_prompt
    state = record_pilot_call(
        composition, state, call_receipt(composition, state, output="answered patch")
    )
    state = record_acceptance(composition, state, passed=True, report="tests passed")
    assert state["status"] == "COMPLETE"
    assert [call["stage"] for call in state["calls"]] == ["hands", "hands_resume"]
    assert all(call["backend"] == "cheap_hands" for call in state["calls"])


def test_call_receipts_fail_closed_on_identity_or_session_drift(root: Path) -> None:
    composition, _ = make_composition(root)
    state = arm_state(composition, "real-04", "T2", "arm_a")
    first = call_receipt(composition, state, output="plan", session="reused")
    state = record_pilot_call(composition, state, first)
    wrong = call_receipt(composition, state, output="patch", session="reused")
    assert "fresh_session_per_call" in _raises(
        CompositionError, record_pilot_call, composition, state, wrong
    )
    wrong = call_receipt(composition, state, output="patch")
    wrong["backend"] = "frontier"
    assert "frozen stage" in _raises(
        CompositionError, record_pilot_call, composition, state, wrong
    )
    wrong = call_receipt(composition, state, output="patch")
    wrong["prompt_sha256"] = "0" * 64
    assert "causal inputs" in _raises(
        CompositionError, record_pilot_call, composition, state, wrong
    )


def test_arm_c_acceptance_failure_uses_hands_repair_not_driver(root: Path) -> None:
    composition, _ = make_composition(root)
    state = arm_state(composition, "real-05", "T1", "arm_c")
    state = record_pilot_call(composition, state, call_receipt(composition, state, output="patch"))
    state = record_acceptance(composition, state, passed=False, report="tests failed")
    assert state["next_stage"] == "repair"
    receipt = call_receipt(composition, state, output="Need a policy choice", outcome="question")
    assert receipt["backend"] == "cheap_hands"
    state = record_pilot_call(composition, state, receipt)
    assert state["status"] == "WAITING_OPERATOR"


def test_provider_error_is_terminal_not_model_escalation(root: Path) -> None:
    composition, _ = make_composition(root)
    state = arm_state(composition, "real-06", "T2", "arm_a")
    receipt = call_receipt(
        composition, state, output="fixture provider unavailable", outcome="error"
    )
    state = record_pilot_call(composition, state, receipt)
    assert state["status"] == "FAILED"
    assert state["next_stage"] is None
    assert [call["stage"] for call in state["calls"]] == ["driver_plan"]


def main() -> None:
    tests = [
        test_manifest_locks_roles_and_common_hands,
        test_arm_a_repairs_and_emits_driver_trace,
        test_arm_b_failure_escalates_only_after_repair,
        test_arm_c_question_answer_resume_has_no_driver,
        test_call_receipts_fail_closed_on_identity_or_session_drift,
        test_arm_c_acceptance_failure_uses_hands_repair_not_driver,
        test_provider_error_is_terminal_not_model_escalation,
    ]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for index, test in enumerate(tests):
            case = root / f"case-{index}"
            case.mkdir()
            test(case)
    print(f"ok: {len(tests)} tier pilot composition tests")


if __name__ == "__main__":
    main()
