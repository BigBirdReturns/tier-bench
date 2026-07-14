from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import uuid

from tier_runner.manifest import ManifestError
from tier_runner.pilot_composition import (
    CALL_SCHEMA,
    CompositionError,
    acceptance_receipt_hash,
    answer_operator_question,
    append_driver_traces,
    decline_operator_question,
    new_pilot_arm_state,
    read_state,
    record_acceptance,
    record_pilot_call,
    render_next_prompt,
    state_hash,
    write_state,
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
        "acceptance_tool_versions": {"fixture-acceptance": "1"},
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
        "outcome": (
            "error" if outcome == "error" else "partial" if outcome == "question" else "pass"
        ),
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


def acceptance_receipt(
    composition: PilotComposition,
    state: dict,
    *,
    passed: bool,
    report: str,
) -> dict:
    causal = state["calls"][-1]
    receipt = {
        "schema": "tier-bench/tier-pilot-acceptance-receipt@1",
        "receipt_sha256": "0" * 64,
        "task_id": state["task_id"],
        "arm": state["arm"],
        "attempt": len(state["acceptance_attempts"]) + 1,
        "causal_call_id": causal["call_id"],
        "base_commit": state["base_commit"],
        "command": state["acceptance_command"],
        "command_sha256": _sha(state["acceptance_command"]),
        "candidate_patch_sha256": causal["output"]["sha256"],
        "candidate_tree_sha256": _sha(f"tree-{causal['call_id']}"),
        "exit_code": 0 if passed else 1,
        "passed": passed,
        "report": report,
        "report_sha256": _sha(report),
        "stdout_sha256": _sha(f"stdout-{report}"),
        "stderr_sha256": _sha(f"stderr-{report}"),
        "tool_versions": composition.acceptance_tool_versions,
        "recorded_at": "2026-07-13T00:00:01Z",
    }
    receipt["receipt_sha256"] = acceptance_receipt_hash(receipt)
    return receipt


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

    composition, path = make_composition(root / "wrong-protocol")
    value = json.loads(path.read_text(encoding="utf-8"))
    value["protocol_commit"] = "f" * 40
    path.write_text(json.dumps(value), encoding="utf-8")
    assert "registered v1.3 bytes" in _raises(
        ManifestError, load_pilot_composition, path
    )


def test_arm_a_repairs_and_emits_driver_trace(root: Path) -> None:
    composition, _ = make_composition(root)
    evidence = root / "evidence"
    state_log = evidence / "arm-state.jsonl"
    state = arm_state(composition, "real-01", "T2", "arm_a")
    write_state(state_log, composition, state)
    state = record_pilot_call(composition, state, call_receipt(composition, state, output="plan"))
    write_state(state_log, composition, state)
    assert state["next_stage"] == "hands"
    assert b"Frozen driver plan:\nplan" in render_next_prompt(composition, state)
    state = record_pilot_call(
        composition, state, call_receipt(composition, state, output="first patch")
    )
    write_state(state_log, composition, state)
    state = record_acceptance(
        composition, state, acceptance_receipt(composition, state, passed=False, report="tests failed")
    )
    write_state(state_log, composition, state)
    assert state["next_stage"] == "repair"
    repair_prompt = render_next_prompt(composition, state)
    assert b"Candidate:\nfirst patch" in repair_prompt
    assert b"Failure:\ntests failed" in repair_prompt
    state = record_pilot_call(
        composition, state, call_receipt(composition, state, output="repaired patch")
    )
    write_state(state_log, composition, state)
    state = record_acceptance(
        composition, state, acceptance_receipt(composition, state, passed=True, report="tests passed")
    )
    write_state(state_log, composition, state)
    assert state["status"] == "COMPLETE"
    assert len(state["calls"]) == 3
    assert len(state["driver_traces"]) == 1
    trace = state["driver_traces"][0]
    assert trace["hands_output"] == "first patch"
    assert trace["validator_report"] == "tests failed"
    assert trace["driver_output"] == "repaired patch"
    assert trace["passed"] is True
    target = root / "target"
    packet = root / "packet"
    worktree = root / "worktree"
    for path in (target, packet, worktree):
        path.mkdir()
    traces = evidence / f"driver_traces.{_sha('real-01')}.jsonl"
    exclusions = [target, packet, worktree]
    assert append_driver_traces(
        composition, evidence, state_log, forbidden_roots=exclusions
    ) == 1
    assert append_driver_traces(
        composition, evidence, state_log, forbidden_roots=exclusions
    ) == 0
    assert "enters target" in _raises(
        CompositionError,
        append_driver_traces,
        composition,
        target,
        state_log,
        forbidden_roots=exclusions,
    )
    assert not (target / f"driver_traces.{_sha('real-01')}.jsonl").exists()
    assert json.loads(traces.read_text(encoding="utf-8"))["trace_sha256"] == trace["trace_sha256"]


def test_arm_b_failure_escalates_only_after_repair(root: Path) -> None:
    composition, _ = make_composition(root)
    state = arm_state(composition, "real-02", "T2", "arm_b")
    state = record_pilot_call(composition, state, call_receipt(composition, state, output="cheap plan"))
    state = record_pilot_call(composition, state, call_receipt(composition, state, output="patch"))
    state = record_acceptance(
        composition, state, acceptance_receipt(composition, state, passed=False, report="first fail")
    )
    assert state["next_stage"] == "repair"
    state = record_pilot_call(composition, state, call_receipt(composition, state, output="cheap repair"))
    state = record_acceptance(
        composition, state, acceptance_receipt(composition, state, passed=False, report="repair failed")
    )
    assert state["next_stage"] == "escalation"
    escalation_prompt = render_next_prompt(composition, state)
    assert b"Candidate:\ncheap repair" in escalation_prompt
    assert b"Failure:\nrepair failed" in escalation_prompt
    state = record_pilot_call(composition, state, call_receipt(composition, state, output="escalated repair"))
    state = record_acceptance(
        composition,
        state,
        acceptance_receipt(composition, state, passed=True, report="escalation passed"),
    )
    assert state["status"] == "COMPLETE"
    assert not state["driver_traces"]


def test_arm_c_question_answer_resume_has_no_driver(root: Path) -> None:
    composition, _ = make_composition(root)
    state = arm_state(composition, "real-03", "T1", "arm_c")
    state_log = root / "evidence" / "arm-c-state.jsonl"
    write_state(state_log, composition, state)
    assert state["next_stage"] == "hands"
    assert b"NO_MODEL_DRIVER" in render_next_prompt(composition, state)
    question_call = call_receipt(
        composition, state, output="Should the parser preserve blanks?", outcome="question"
    )
    assert question_call["ledger_call"]["outcome"] == "partial"
    state = record_pilot_call(
        composition,
        state,
        question_call,
    )
    write_state(state_log, composition, state)
    assert state["status"] == "WAITING_OPERATOR"
    assert state["active_question_id"]
    question = state["questions"][0]
    assert "Should the parser preserve blanks?" in question["rendered"]
    state = answer_operator_question(
        composition,
        state,
        question_id=state["active_question_id"],
        answer="Yes, preserve blanks.",
        intervention_id=str(uuid.uuid4()),
    )
    write_state(state_log, composition, state)
    assert state["next_stage"] == "hands_resume"
    assert len(state["question_receipts"]) == 1
    question_receipt = state["question_receipts"][0]
    assert question_receipt["schema"] == "tier-bench/tier-pilot-question-receipt@1"
    assert question_receipt["question_id"] == question["question_id"]
    assert question_receipt["intervention_id"] == state["questions"][0]["intervention_id"]
    resume_prompt = render_next_prompt(composition, state)
    assert b"Should the parser preserve blanks?" in resume_prompt
    assert b"Yes, preserve blanks." in resume_prompt
    state = record_pilot_call(
        composition, state, call_receipt(composition, state, output="answered patch")
    )
    write_state(state_log, composition, state)
    state = record_acceptance(
        composition, state, acceptance_receipt(composition, state, passed=True, report="tests passed")
    )
    write_state(state_log, composition, state)
    assert state["status"] == "COMPLETE"
    assert [call["stage"] for call in state["calls"]] == ["hands", "hands_resume"]
    assert all(call["backend"] == "cheap_hands" for call in state["calls"])
    assert read_state(composition, state_log)["state_sha256"] == state["state_sha256"]


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
    state = record_acceptance(
        composition, state, acceptance_receipt(composition, state, passed=False, report="tests failed")
    )
    assert state["next_stage"] == "repair"
    receipt = call_receipt(composition, state, output="Need a policy choice", outcome="question")
    assert receipt["backend"] == "cheap_hands"
    state = record_pilot_call(composition, state, receipt)
    assert state["status"] == "WAITING_OPERATOR"
    state = answer_operator_question(
        composition,
        state,
        question_id=state["active_question_id"],
        answer="Use the documented policy.",
        intervention_id=str(uuid.uuid4()),
    )
    state = record_pilot_call(
        composition, state, call_receipt(composition, state, output="resumed repair")
    )
    state = record_acceptance(
        composition,
        state,
        acceptance_receipt(composition, state, passed=False, report="resume still failed"),
    )
    assert state["repair_calls"] == 1
    assert state["status"] == "FAILED"
    assert state["next_stage"] is None


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


def test_acceptance_receipt_binds_candidate_and_tools(root: Path) -> None:
    composition, _ = make_composition(root)
    state = arm_state(composition, "real-07", "T1", "arm_c")
    state = record_pilot_call(composition, state, call_receipt(composition, state, output="patch"))
    wrong = acceptance_receipt(composition, state, passed=True, report="passed")
    wrong["candidate_patch_sha256"] = "0" * 64
    wrong["receipt_sha256"] = acceptance_receipt_hash(wrong)
    assert "candidate patch" in _raises(
        CompositionError, record_acceptance, composition, state, wrong
    )
    wrong = acceptance_receipt(composition, state, passed=True, report="passed")
    wrong["tool_versions"] = {"fixture-acceptance": "drift"}
    wrong["receipt_sha256"] = acceptance_receipt_hash(wrong)
    assert "tool versions" in _raises(
        CompositionError, record_acceptance, composition, state, wrong
    )


def test_state_log_rejects_rewrite_and_fork(root: Path) -> None:
    composition, _ = make_composition(root)
    initial = arm_state(composition, "real-08", "T2", "arm_a")
    log = root / "evidence" / "arm-state.jsonl"
    write_state(log, composition, initial)
    branch_a = record_pilot_call(
        composition, initial, call_receipt(composition, initial, output="plan A")
    )
    write_state(log, composition, branch_a)
    assert read_state(composition, log)["state_sha256"] == branch_a["state_sha256"]
    branch_b = record_pilot_call(
        composition, initial, call_receipt(composition, initial, output="plan B")
    )
    assert "non-contiguous" in _raises(
        CompositionError, write_state, log, composition, branch_b
    )

    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    semantic_rewrite = copy.deepcopy(rows)
    semantic_rewrite[-1]["next_stage"] = "repair"
    semantic_rewrite[-1]["state_sha256"] = state_hash(semantic_rewrite[-1])
    log.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in semantic_rewrite) + "\n",
        encoding="utf-8",
    )
    assert "status/next_stage" in _raises(
        CompositionError, read_state, composition, log
    )

    log.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )
    rows[-1]["task"] = "rewritten after pause"
    log.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")
    assert "state hash is invalid" in _raises(
        CompositionError, read_state, composition, log
    )


def test_trace_rejects_rehashed_but_noncausal_content(root: Path) -> None:
    composition, _ = make_composition(root)
    state_log = root / "trace-state.jsonl"
    state = arm_state(composition, "real-09", "T2", "arm_a")
    write_state(state_log, composition, state)
    state = record_pilot_call(composition, state, call_receipt(composition, state, output="plan"))
    write_state(state_log, composition, state)
    state = record_pilot_call(composition, state, call_receipt(composition, state, output="patch"))
    write_state(state_log, composition, state)
    state = record_acceptance(
        composition, state, acceptance_receipt(composition, state, passed=False, report="real failure")
    )
    write_state(state_log, composition, state)
    state = record_pilot_call(composition, state, call_receipt(composition, state, output="repair"))
    write_state(state_log, composition, state)
    state = record_acceptance(
        composition, state, acceptance_receipt(composition, state, passed=True, report="passed")
    )
    write_state(state_log, composition, state)
    tampered = copy.deepcopy(state)
    trace = tampered["driver_traces"][0]
    trace["validator_report"] = "invented failure"
    trace["validator_report_sha256"] = _sha("invented failure")
    unsigned = dict(trace)
    unsigned.pop("trace_sha256")
    trace["trace_sha256"] = _sha(json.dumps(unsigned, sort_keys=True, separators=(",", ":")))
    tampered["state_sha256"] = state_hash(tampered)
    rows = [json.loads(line) for line in state_log.read_text(encoding="utf-8").splitlines()]
    rows[-1] = tampered
    state_log.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )
    assert "driver trace contradicts" in _raises(
        CompositionError,
        append_driver_traces,
        composition,
        root / "evidence",
        state_log,
        forbidden_roots=[root / "target", root / "packet", root / "worktree"],
    )


def test_preexisting_trace_file_must_match_replayed_task(root: Path) -> None:
    composition, _ = make_composition(root / "preexisting-trace")
    state_log = root / "preexisting-trace-state.jsonl"
    state = arm_state(composition, "real-16", "T2", "arm_a")
    write_state(state_log, composition, state)
    for output in ("plan", "patch"):
        state = record_pilot_call(
            composition, state, call_receipt(composition, state, output=output)
        )
        write_state(state_log, composition, state)
    state = record_acceptance(
        composition,
        state,
        acceptance_receipt(composition, state, passed=False, report="real failure"),
    )
    write_state(state_log, composition, state)
    state = record_pilot_call(
        composition, state, call_receipt(composition, state, output="repair")
    )
    write_state(state_log, composition, state)
    state = record_acceptance(
        composition,
        state,
        acceptance_receipt(composition, state, passed=True, report="passed"),
    )
    write_state(state_log, composition, state)

    fabricated = copy.deepcopy(state["driver_traces"][0])
    fabricated["task_id"] = "fabricated-other-task"
    unsigned = dict(fabricated)
    unsigned.pop("trace_sha256")
    fabricated["trace_sha256"] = _sha(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"))
    )
    evidence = root / "preexisting-evidence"
    evidence.mkdir()
    trace_path = evidence / f"driver_traces.{_sha('real-16')}.jsonl"
    trace_path.write_text(
        json.dumps(fabricated, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    assert "not bound to this Arm-A task" in _raises(
        CompositionError,
        append_driver_traces,
        composition,
        evidence,
        state_log,
        forbidden_roots=[root / "target", root / "packet", root / "worktree"],
    )


def test_read_state_replays_embedded_receipts(root: Path) -> None:
    composition, _ = make_composition(root)
    initial = arm_state(composition, "real-10", "T2", "arm_a")
    called = record_pilot_call(
        composition, initial, call_receipt(composition, initial, output="plan")
    )
    log = root / "call-state.jsonl"
    write_state(log, composition, initial)
    write_state(log, composition, called)
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    rows[-1]["calls"][-1]["ledger_call"]["model"] = "mutated-model"
    rows[-1]["transition"]["reference_sha256"] = hashlib.sha256(
        (json.dumps(rows[-1]["calls"][-1], sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()
    rows[-1]["state_sha256"] = state_hash(rows[-1])
    log.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )
    assert "frozen backend" in _raises(
        CompositionError, read_state, composition, log
    )

    initial = arm_state(composition, "real-11", "T1", "arm_c")
    candidate = record_pilot_call(
        composition, initial, call_receipt(composition, initial, output="patch")
    )
    accepted = record_acceptance(
        composition,
        candidate,
        acceptance_receipt(composition, candidate, passed=True, report="passed"),
    )
    log = root / "acceptance-state.jsonl"
    for item in (initial, candidate, accepted):
        write_state(log, composition, item)
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    mutated = rows[-1]["acceptance_attempts"][-1]
    mutated["tool_versions"] = {"fixture-acceptance": "mutated"}
    mutated["receipt_sha256"] = acceptance_receipt_hash(mutated)
    rows[-1]["transition"]["reference_sha256"] = mutated["receipt_sha256"]
    rows[-1]["state_sha256"] = state_hash(rows[-1])
    log.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )
    assert "tool versions" in _raises(
        CompositionError, read_state, composition, log
    )

    initial = arm_state(composition, "real-15", "T1", "arm_c")
    asked = record_pilot_call(
        composition,
        initial,
        call_receipt(composition, initial, output="Which interpretation?", outcome="question"),
    )
    log = root / "question-state.jsonl"
    write_state(log, composition, initial)
    write_state(log, composition, asked)
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    rows[-1]["questions"][-1]["question"] = "Substituted question"
    rows[-1]["state_sha256"] = state_hash(rows[-1])
    log.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )
    assert "causal call receipt" in _raises(
        CompositionError, read_state, composition, log
    )


def test_max_questions_terminal_state_is_durable(root: Path) -> None:
    composition, _ = make_composition(root)
    state = arm_state(composition, "real-12", "T1", "arm_c")
    log = root / "max-question-state.jsonl"
    write_state(log, composition, state)
    for number in (1, 2):
        state = record_pilot_call(
            composition,
            state,
            call_receipt(composition, state, output=f"question {number}", outcome="question"),
        )
        write_state(log, composition, state)
        state = answer_operator_question(
            composition,
            state,
            question_id=state["active_question_id"],
            answer=f"answer {number}",
            intervention_id=str(uuid.uuid4()),
        )
        write_state(log, composition, state)
    state = record_pilot_call(
        composition,
        state,
        call_receipt(composition, state, output="question 3", outcome="question"),
    )
    assert state["status"] == "FAILED"
    assert state["next_stage"] is None
    assert len(state["questions"]) == 2
    write_state(log, composition, state)
    assert read_state(composition, log)["state_sha256"] == state["state_sha256"]


def test_initial_state_rejects_preseeded_genesis(root: Path) -> None:
    composition, _ = make_composition(root)
    initial = arm_state(composition, "real-13", "T1", "arm_c")
    preseeded = copy.deepcopy(initial)
    preseeded["questions"].append({"question_id": "invented"})
    preseeded["state_sha256"] = state_hash(preseeded)
    assert "preseeded evidence" in _raises(
        CompositionError, write_state, root / "preseeded.jsonl", composition, preseeded
    )
    counter = copy.deepcopy(initial)
    counter["repair_calls"] = 1
    counter["state_sha256"] = state_hash(counter)
    assert "counters must be zero" in _raises(
        CompositionError, write_state, root / "counter.jsonl", composition, counter
    )
    timestamp = copy.deepcopy(initial)
    timestamp["updated_at"] = "2026-07-13T01:00:00Z"
    timestamp["state_sha256"] = state_hash(timestamp)
    assert "canonical instant" in _raises(
        CompositionError, write_state, root / "timestamp.jsonl", composition, timestamp
    )


def test_decline_is_one_appendable_transition(root: Path) -> None:
    composition, _ = make_composition(root)
    state = arm_state(composition, "real-14", "T1", "arm_c")
    log = root / "decline-state.jsonl"
    write_state(log, composition, state)
    state = record_pilot_call(
        composition,
        state,
        call_receipt(composition, state, output="Need operator authority", outcome="question"),
    )
    write_state(log, composition, state)
    paused_sequence = state["state_sequence"]
    state = decline_operator_question(
        composition,
        state,
        question_id=state["active_question_id"],
        reason="Declined; task requires a new authorization.",
        intervention_id=str(uuid.uuid4()),
    )
    assert state["state_sequence"] == paused_sequence + 1
    assert state["status"] == "FAILED"
    assert len(state["question_receipts"]) == 1
    write_state(log, composition, state)
    assert read_state(composition, log)["state_sha256"] == state["state_sha256"]


def main() -> None:
    tests = [
        test_manifest_locks_roles_and_common_hands,
        test_arm_a_repairs_and_emits_driver_trace,
        test_arm_b_failure_escalates_only_after_repair,
        test_arm_c_question_answer_resume_has_no_driver,
        test_call_receipts_fail_closed_on_identity_or_session_drift,
        test_arm_c_acceptance_failure_uses_hands_repair_not_driver,
        test_provider_error_is_terminal_not_model_escalation,
        test_acceptance_receipt_binds_candidate_and_tools,
        test_state_log_rejects_rewrite_and_fork,
        test_trace_rejects_rehashed_but_noncausal_content,
        test_preexisting_trace_file_must_match_replayed_task,
        test_read_state_replays_embedded_receipts,
        test_max_questions_terminal_state_is_durable,
        test_initial_state_rejects_preseeded_genesis,
        test_decline_is_one_appendable_transition,
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
