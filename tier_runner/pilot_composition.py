from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any
import uuid

from .manifest import canonical_json
from .pilot_manifest import PilotArm, PilotComposition, Stage


STATE_SCHEMA = "tier-bench/pilot-arm-state@1"
CALL_SCHEMA = "tier-bench/pilot-call-receipt@1"
TRACE_SCHEMA = "tier-bench/driver-trace@2"
QUESTION_SCHEMA = "tier-bench/tier-pilot-question-receipt@1"
ACCEPTANCE_SCHEMA = "tier-bench/tier-pilot-acceptance-receipt@1"
CALL_FIELDS = {
    "ts",
    "account",
    "model",
    "tier",
    "task_id",
    "phase",
    "outcome",
    "effort",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "cost_usd",
    "latency_ms",
    "trial",
    "note",
    "extra",
}
CALL_STAGES = {"driver_plan", "hands", "repair", "escalation", "hands_resume"}
CALL_OUTCOMES = {"completed", "question", "error"}
QUESTION_RECEIPT_FIELDS = {
    "schema",
    "question_id",
    "task_id",
    "arm",
    "intervention_id",
    "asked_at",
    "answered_at",
    "question_sha256",
    "answer_sha256",
}
STATE_FIELDS = {
    "schema",
    "state_sequence",
    "parent_state_sha256",
    "state_sha256",
    "transition",
    "composition_manifest_sha256",
    "protocol_commit",
    "task_id",
    "task_tier",
    "task",
    "files",
    "acceptance_command",
    "base_commit",
    "arm",
    "status",
    "next_stage",
    "repair_calls",
    "escalation_index",
    "calls",
    "acceptance_attempts",
    "questions",
    "question_receipts",
    "active_question_id",
    "driver_traces",
    "created_at",
    "updated_at",
}


class CompositionError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256(value: Any, label: str) -> str:
    value = _nonempty(value, label)
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise CompositionError(f"{label} must be a lowercase SHA-256")
    return value


def state_hash(state: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in state.items() if key != "state_sha256"}
    return hashlib.sha256(canonical_json(unsigned)).hexdigest()


def _seal_initial(state: dict[str, Any]) -> dict[str, Any]:
    state["state_sequence"] = 0
    state["parent_state_sha256"] = None
    state["transition"] = {"kind": "init", "at": state["created_at"]}
    state["state_sha256"] = state_hash(state)
    return state


def _seal_next(
    previous: dict[str, Any],
    updated: dict[str, Any],
    *,
    kind: str,
    reference_sha256: str,
) -> dict[str, Any]:
    at = _now()
    updated["state_sequence"] = previous["state_sequence"] + 1
    updated["parent_state_sha256"] = previous["state_sha256"]
    updated["transition"] = {
        "kind": kind,
        "reference_sha256": _sha256(reference_sha256, "transition reference_sha256"),
        "at": at,
    }
    updated["updated_at"] = at
    updated["state_sha256"] = state_hash(updated)
    return updated


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise CompositionError(f"{label} must be a non-empty string")
    return value


def _number(value: Any, label: str, *, integer: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise CompositionError(f"{label} must be a non-negative number")
    if integer and not isinstance(value, int):
        raise CompositionError(f"{label} must be a non-negative integer")


def _template(composition: PilotComposition, name: str) -> dict[str, str]:
    template = composition.templates[name]
    return {"name": name, "sha256": template.sha256}


def _expected_stage(composition: PilotComposition, state: dict[str, Any]) -> Stage:
    arm = composition.arms[state["arm"]]
    stage = state["next_stage"]
    if stage == "driver_plan":
        if arm.driver is None:
            raise CompositionError("operator-routed arm has no driver stage")
        return arm.driver
    if stage == "hands":
        return arm.hands
    if stage == "repair":
        return Stage(arm.repair.backend, arm.repair.prompt_template)
    if stage == "hands_resume":
        if arm.question_route is None:
            raise CompositionError("only arm_c may resume from an operator answer")
        return Stage(arm.hands.backend, arm.question_route.resume_prompt_template)
    if stage == "escalation":
        index = state["escalation_index"]
        try:
            return arm.escalations[index]
        except IndexError as exc:
            raise CompositionError("escalation index exceeds the frozen ladder") from exc
    raise CompositionError(f"state has no model-call stage: {stage!r}")


def new_pilot_arm_state(
    composition: PilotComposition,
    *,
    task_id: str,
    task_tier: str,
    arm: str,
    task: str,
    files: list[str],
    acceptance_command: str,
    base_commit: str,
) -> dict[str, Any]:
    _nonempty(task_id, "task_id")
    _nonempty(task_tier, "task_tier")
    _nonempty(task, "task")
    _nonempty(acceptance_command, "acceptance_command")
    if not isinstance(files, list) or not files or not all(
        isinstance(item, str) and item for item in files
    ):
        raise CompositionError("files must be a non-empty string array")
    if not re.fullmatch(r"[0-9a-f]{40}", base_commit):
        raise CompositionError("base_commit must be a full lowercase Git SHA")
    if arm not in composition.arms:
        raise CompositionError(f"unknown arm {arm!r}")
    first_stage = "hands" if arm == "arm_c" else "driver_plan"
    created_at = _now()
    return _seal_initial({
        "schema": STATE_SCHEMA,
        "composition_manifest_sha256": composition.sha256,
        "protocol_commit": composition.protocol_commit,
        "task_id": task_id,
        "task_tier": task_tier,
        "task": task,
        "files": list(files),
        "acceptance_command": acceptance_command,
        "base_commit": base_commit,
        "arm": arm,
        "status": "ACTIVE",
        "next_stage": first_stage,
        "repair_calls": 0,
        "escalation_index": 0,
        "calls": [],
        "acceptance_attempts": [],
        "questions": [],
        "question_receipts": [],
        "active_question_id": None,
        "driver_traces": [],
        "created_at": created_at,
        "updated_at": created_at,
    })


def _last_completed_output(state: dict[str, Any], stages: set[str]) -> str | None:
    for call in reversed(state["calls"]):
        if call["stage"] in stages and call["outcome"] == "completed":
            return call["output"]["text"]
    return None


def _last_failed_report(state: dict[str, Any]) -> str | None:
    for attempt in reversed(state["acceptance_attempts"]):
        if attempt["passed"] is False:
            return attempt["report"]
    return None


def render_next_prompt(composition: PilotComposition, state: dict[str, Any]) -> bytes:
    """Render the next frozen model prompt from sealed causal predecessors.

    This renderer is deliberately independent of any provider adapter. A later
    reviewed bridge must write these exact bytes to the call dispatch; it may
    not reconstruct or paraphrase the plan, candidate, failure, or operator
    answer.
    """
    _validate_state(composition, state)
    if state["status"] != "ACTIVE" or state["next_stage"] not in CALL_STAGES:
        raise CompositionError("arm state is not waiting for a model prompt")
    expected = _expected_stage(composition, state)
    template = composition.templates[expected.prompt_template].raw.decode("utf-8")
    stage = state["next_stage"]
    replacements = {
        "{{TASK}}": state["task"],
        "{{FILES}}": "\n".join(state["files"]),
        "{{ACCEPTANCE}}": state["acceptance_command"],
        "{{BASE_COMMIT}}": state["base_commit"],
    }
    required = set(replacements)
    if stage == "hands":
        replacements["{{DRIVER_PLAN}}"] = (
            _last_completed_output(state, {"driver_plan"}) or "NO_MODEL_DRIVER"
        )
        required.add("{{DRIVER_PLAN}}")
    elif stage in {"repair", "escalation"}:
        replacements["{{CANDIDATE_OUTPUT}}"] = (
            _last_completed_output(state, {"hands", "hands_resume", "repair", "escalation"})
            or "NO_CANDIDATE"
        )
        replacements["{{FAILED_ACCEPTANCE_REPORT}}"] = (
            _last_failed_report(state) or "NO_FAILED_ACCEPTANCE"
        )
        required.update({"{{CANDIDATE_OUTPUT}}", "{{FAILED_ACCEPTANCE_REPORT}}"})
    elif stage == "hands_resume":
        answered = [question for question in state["questions"] if question["answer"] is not None]
        if not answered:
            raise CompositionError("hands_resume has no sealed operator answer")
        question = answered[-1]
        replacements.update(
            {
                "{{QUESTION}}": question["question"],
                "{{ANSWER}}": question["answer"],
                "{{CANDIDATE_OUTPUT}}": (
                    _last_completed_output(state, {"hands", "repair"}) or "NO_CANDIDATE"
                ),
                "{{FAILED_ACCEPTANCE_REPORT}}": (
                    _last_failed_report(state) or "NO_FAILED_ACCEPTANCE"
                ),
            }
        )
        required.update(
            {
                "{{QUESTION}}",
                "{{ANSWER}}",
                "{{CANDIDATE_OUTPUT}}",
                "{{FAILED_ACCEPTANCE_REPORT}}",
            }
        )
    missing = sorted(marker for marker in required if marker not in template)
    if missing:
        raise CompositionError(
            f"{stage} prompt template is missing causal markers: {missing}"
        )
    unknown = set(re.findall(r"\{\{[A-Z_]+\}\}", template)) - set(replacements)
    if unknown:
        raise CompositionError(f"{stage} prompt template has unknown markers: {sorted(unknown)}")
    pattern = re.compile("|".join(re.escape(marker) for marker in replacements))
    return pattern.sub(lambda match: replacements[match.group(0)], template).encode("utf-8")


def _validate_state(composition: PilotComposition, state: dict[str, Any]) -> None:
    if not isinstance(state, dict) or set(state) != STATE_FIELDS:
        missing = STATE_FIELDS - set(state) if isinstance(state, dict) else STATE_FIELDS
        unknown = set(state) - STATE_FIELDS if isinstance(state, dict) else set()
        raise CompositionError(
            f"state fields mismatch; missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    if state.get("schema") != STATE_SCHEMA:
        raise CompositionError(f"state schema must be {STATE_SCHEMA}")
    if state.get("composition_manifest_sha256") != composition.sha256:
        raise CompositionError("state is bound to a different pilot composition manifest")
    if state.get("protocol_commit") != composition.protocol_commit:
        raise CompositionError("state protocol commit contradicts the composition manifest")
    if state.get("arm") not in composition.arms:
        raise CompositionError("state arm is not in the composition manifest")
    if not isinstance(state.get("state_sequence"), int) or state["state_sequence"] < 0:
        raise CompositionError("state_sequence must be a non-negative integer")
    if state["state_sequence"] == 0:
        if state.get("parent_state_sha256") is not None or state.get("transition", {}).get("kind") != "init":
            raise CompositionError("initial state must have no parent and an init transition")
    else:
        _sha256(state.get("parent_state_sha256"), "parent_state_sha256")
        transition = state.get("transition")
        if not isinstance(transition, dict) or set(transition) != {"kind", "reference_sha256", "at"}:
            raise CompositionError("non-initial state needs an exact transition receipt")
        _nonempty(transition["kind"], "transition.kind")
        _sha256(transition["reference_sha256"], "transition.reference_sha256")
        _nonempty(transition["at"], "transition.at")
    for key in ("task_id", "task_tier", "task", "acceptance_command", "base_commit"):
        _nonempty(state.get(key), f"state.{key}")
    if not re.fullmatch(r"[0-9a-f]{40}", state["base_commit"]):
        raise CompositionError("state.base_commit must be a full lowercase Git SHA")
    if not isinstance(state.get("files"), list) or not state["files"] or not all(
        isinstance(item, str) and item for item in state["files"]
    ):
        raise CompositionError("state.files must be a non-empty string array")
    for key in ("calls", "acceptance_attempts", "questions", "question_receipts", "driver_traces"):
        if not isinstance(state.get(key), list):
            raise CompositionError(f"state.{key} must be an array")
    if state.get("status") not in {"ACTIVE", "WAITING_OPERATOR", "COMPLETE", "FAILED"}:
        raise CompositionError("state.status is invalid")
    _sha256(state.get("state_sha256"), "state_sha256")
    if state["state_sha256"] != state_hash(state):
        raise CompositionError("state hash is invalid; snapshot was rewritten")
    if state["state_sequence"] > 0:
        kind = state["transition"]["kind"]
        if kind == "model_call":
            if not state["calls"]:
                raise CompositionError("model_call transition has no call receipt")
            expected_ref = hashlib.sha256(canonical_json(state["calls"][-1])).hexdigest()
        elif kind == "acceptance":
            if not state["acceptance_attempts"]:
                raise CompositionError("acceptance transition has no acceptance receipt")
            expected_ref = state["acceptance_attempts"][-1].get("receipt_sha256")
        elif kind == "operator_answer":
            if not state["question_receipts"]:
                raise CompositionError("operator_answer transition has no question receipt")
            expected_ref = hashlib.sha256(
                canonical_json(state["question_receipts"][-1])
            ).hexdigest()
        elif kind == "operator_decline":
            if not state["question_receipts"]:
                raise CompositionError("operator_decline transition has no question receipt")
            expected_ref = hashlib.sha256(
                canonical_json(state["question_receipts"][-1])
            ).hexdigest()
        else:
            raise CompositionError(f"unknown state transition kind {kind!r}")
        if state["transition"]["reference_sha256"] != expected_ref:
            raise CompositionError("state transition reference does not bind its evidence")
    _validate_state_semantics(composition, state)


def _validate_state_semantics(
    composition: PilotComposition,
    state: dict[str, Any],
) -> None:
    arm = composition.arms[state["arm"]]
    if state["state_sequence"] == 0:
        if any(
            state[name]
            for name in (
                "calls",
                "acceptance_attempts",
                "questions",
                "question_receipts",
                "driver_traces",
            )
        ):
            raise CompositionError("initial state cannot contain preseeded evidence")
        if state["repair_calls"] != 0 or state["escalation_index"] != 0:
            raise CompositionError("initial state counters must be zero")
        if state["active_question_id"] is not None:
            raise CompositionError("initial state cannot contain an active question")
        if not (
            state["created_at"]
            == state["updated_at"]
            == state["transition"].get("at")
        ):
            raise CompositionError("initial state timestamps must share one canonical instant")
        expected = ("ACTIVE", "hands" if state["arm"] == "arm_c" else "driver_plan")
    else:
        kind = state["transition"]["kind"]
        if kind == "operator_answer":
            expected = ("ACTIVE", "hands_resume")
        elif kind == "operator_decline":
            expected = ("FAILED", None)
        elif kind == "model_call":
            call = state["calls"][-1]
            if call["outcome"] == "question":
                routed = any(
                    question.get("call_id") == call["call_id"]
                    for question in state["questions"]
                )
                expected = ("WAITING_OPERATOR", None) if routed else ("FAILED", None)
            elif call["outcome"] == "error":
                expected = ("FAILED", None)
            elif call["stage"] == "driver_plan":
                expected = ("ACTIVE", "hands")
            else:
                expected = ("ACTIVE", "acceptance")
        elif kind == "acceptance":
            receipt = state["acceptance_attempts"][-1]
            if receipt["passed"]:
                expected = ("COMPLETE", None)
            elif state["repair_calls"] < arm.repair.max_calls:
                expected = ("ACTIVE", "repair")
            elif state["escalation_index"] < len(arm.escalations):
                expected = ("ACTIVE", "escalation")
            else:
                expected = ("FAILED", None)
        else:
            raise CompositionError(f"unknown state transition kind {kind!r}")
    if (state["status"], state["next_stage"]) != expected:
        raise CompositionError("state status/next_stage contradicts its sealed evidence")
    if state["status"] == "WAITING_OPERATOR":
        if not state["active_question_id"] or not state["questions"]:
            raise CompositionError("WAITING_OPERATOR state lacks an active question")
        if state["questions"][-1]["question_id"] != state["active_question_id"]:
            raise CompositionError("active question ID does not bind the latest question")
    elif state["active_question_id"] is not None:
        raise CompositionError("non-waiting state cannot carry an active question")


def _validate_parent_transition(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> None:
    immutable = {
        "composition_manifest_sha256",
        "protocol_commit",
        "task_id",
        "task_tier",
        "task",
        "files",
        "acceptance_command",
        "base_commit",
        "arm",
        "created_at",
    }
    if any(current[key] != previous[key] for key in immutable):
        raise CompositionError("pilot state transition rewrites immutable task identity")

    def appended(name: str, maximum: int) -> int:
        before = previous[name]
        after = current[name]
        if after[: len(before)] != before or len(after) - len(before) not in range(maximum + 1):
            raise CompositionError(f"pilot state transition rewrites or over-appends {name}")
        return len(after) - len(before)

    kind = current["transition"]["kind"]
    call_delta = appended("calls", 1)
    acceptance_delta = appended("acceptance_attempts", 1)
    receipt_delta = appended("question_receipts", 1)
    trace_delta = appended("driver_traces", 1)
    if len(current["questions"]) < len(previous["questions"]):
        raise CompositionError("pilot state transition deletes operator questions")
    question_delta = len(current["questions"]) - len(previous["questions"])
    if question_delta > 1:
        raise CompositionError("pilot state transition over-appends operator questions")

    expected = {
        "model_call": (1, 0, 0),
        "acceptance": (0, 1, 0),
        "operator_answer": (0, 0, 1),
        "operator_decline": (0, 0, 1),
    }
    if kind not in expected or (call_delta, acceptance_delta, receipt_delta) != expected[kind]:
        raise CompositionError("state transition kind contradicts appended evidence")
    if kind == "model_call" and question_delta not in {0, 1}:
        raise CompositionError("model call question delta is invalid")
    if kind != "model_call" and question_delta != 0:
        raise CompositionError("non-call transition cannot append a question")
    if kind != "acceptance" and trace_delta != 0:
        raise CompositionError("only acceptance may append a driver trace")
    if kind == "acceptance" and trace_delta not in {0, 1}:
        raise CompositionError("acceptance trace delta is invalid")
    repair_delta = current["repair_calls"] - previous["repair_calls"]
    escalation_delta = current["escalation_index"] - previous["escalation_index"]
    expected_repair_delta = (
        1
        if kind == "model_call"
        and current["calls"][-1]["stage"] == "repair"
        else 0
    )
    expected_escalation_delta = (
        1
        if kind == "acceptance"
        and current["acceptance_attempts"][-1]["passed"] is False
        and previous["calls"][-1]["stage"] == "escalation"
        else 0
    )
    if repair_delta != expected_repair_delta or escalation_delta != expected_escalation_delta:
        raise CompositionError("pilot state transition rewrites repair/escalation counters")

    # Existing questions are immutable except for the one-time answer fields
    # (and the terminal declined marker on the immediately following state).
    for index, before in enumerate(previous["questions"]):
        after = current["questions"][index]
        if before == after:
            continue
        allowed = dict(before)
        if kind == "operator_answer" and before.get("answer") is None:
            for key in ("answer", "answer_sha256", "answered_at", "intervention_id"):
                allowed[key] = after.get(key)
        elif kind == "operator_decline" and before.get("answer") is None:
            for key in ("answer", "answer_sha256", "answered_at", "intervention_id"):
                allowed[key] = after.get(key)
            allowed["declined"] = True
        if after != allowed:
            raise CompositionError("operator question history was rewritten")


def _validate_question_receipt_replay(
    previous: dict[str, Any],
    current: dict[str, Any],
    receipt: dict[str, Any],
) -> None:
    if not isinstance(receipt, dict) or set(receipt) != QUESTION_RECEIPT_FIELDS:
        raise CompositionError("question receipt fields do not match the frozen contract")
    if receipt.get("schema") != QUESTION_SCHEMA:
        raise CompositionError(f"question receipt schema must be {QUESTION_SCHEMA}")
    if previous["arm"] != "arm_c" or previous["status"] != "WAITING_OPERATOR":
        raise CompositionError("question receipt does not resume a paused Arm-C state")
    if receipt.get("task_id") != previous["task_id"] or receipt.get("arm") != "arm_c":
        raise CompositionError("question receipt task/arm contradicts its parent state")
    question_id = previous["active_question_id"]
    if receipt.get("question_id") != question_id:
        raise CompositionError("question receipt does not name the active question")
    prior = next(
        (item for item in previous["questions"] if item["question_id"] == question_id),
        None,
    )
    after = next(
        (item for item in current["questions"] if item["question_id"] == question_id),
        None,
    )
    if prior is None or after is None or prior.get("answer") is not None:
        raise CompositionError("question receipt parent/answer state is invalid")
    if receipt.get("asked_at") != prior.get("asked_at"):
        raise CompositionError("question receipt asked_at contradicts the question")
    if receipt.get("question_sha256") != prior.get("question_sha256"):
        raise CompositionError("question receipt question hash contradicts the question")
    if receipt.get("answered_at") != after.get("answered_at"):
        raise CompositionError("question receipt answered_at contradicts the resumed state")
    if receipt.get("answer_sha256") != after.get("answer_sha256"):
        raise CompositionError("question receipt answer hash contradicts the resumed state")
    if receipt.get("answer_sha256") != _sha_text(
        _nonempty(after.get("answer"), "operator answer")
    ):
        raise CompositionError("question receipt answer hash does not bind the answer bytes")
    if receipt.get("intervention_id") != after.get("intervention_id"):
        raise CompositionError("question receipt intervention ID contradicts the resumed state")
    try:
        uuid.UUID(receipt["intervention_id"])
    except (AttributeError, ValueError) as exc:
        raise CompositionError("question receipt intervention_id must be a UUID") from exc


def _validate_question_route_replay(
    composition: PilotComposition,
    previous: dict[str, Any],
    current: dict[str, Any],
    receipt: dict[str, Any],
) -> None:
    arm = composition.arms[previous["arm"]]
    if receipt["outcome"] != "question":
        if len(current["questions"]) != len(previous["questions"]):
            raise CompositionError("non-question call appended an operator question")
        return
    assert arm.question_route is not None
    if len(previous["questions"]) >= arm.question_route.max_questions:
        if len(current["questions"]) != len(previous["questions"]):
            raise CompositionError("question above the frozen limit was routed")
        return
    if len(current["questions"]) != len(previous["questions"]) + 1:
        raise CompositionError("operator question call lacks its routed question record")
    actual = current["questions"][-1]
    asked_at = _nonempty(actual.get("asked_at"), "operator question asked_at")
    evidence_sha = receipt["output"]["sha256"]
    rendered, template_sha = _render_operator_question(
        composition, current, receipt["output"]["text"], evidence_sha
    )
    expected = {
        "question_id": _sha_text(
            f"{current['task_id']}:{current['arm']}:{receipt['call_id']}:{evidence_sha}"
        ),
        "intervention_id": None,
        "call_id": receipt["call_id"],
        "asked_at": asked_at,
        "question": receipt["output"]["text"],
        "question_sha256": evidence_sha,
        "rendered": rendered,
        "rendered_sha256": _sha_text(rendered),
        "question_template_sha256": template_sha,
        "answer": None,
        "answer_sha256": None,
        "answered_at": None,
    }
    if actual != expected:
        raise CompositionError("operator question record contradicts the causal call receipt")


def _replay_transition_receipt(
    composition: PilotComposition,
    previous: dict[str, Any],
    current: dict[str, Any],
) -> None:
    kind = current["transition"]["kind"]
    if kind == "model_call":
        receipt = current["calls"][-1]
        _validate_call_receipt(composition, previous, receipt)
        _validate_question_route_replay(composition, previous, current, receipt)
    elif kind == "acceptance":
        receipt = current["acceptance_attempts"][-1]
        _validate_acceptance_receipt(composition, previous, receipt)
        expected_trace = _trace_for_repair(composition, current, receipt["passed"])
        new_traces = current["driver_traces"][len(previous["driver_traces"]):]
        if new_traces != ([] if expected_trace is None else [expected_trace]):
            raise CompositionError("driver trace contradicts the causal acceptance transition")
    elif kind == "operator_answer":
        _validate_question_receipt_replay(
            previous, current, current["question_receipts"][-1]
        )
    elif kind == "operator_decline":
        _validate_question_receipt_replay(
            previous, current, current["question_receipts"][-1]
        )
        if current["questions"][-1].get("declined") is not True:
            raise CompositionError("operator decline transition lacks the declined marker")
    else:
        raise CompositionError(f"unknown transition kind during receipt replay: {kind!r}")


def _validate_call_receipt(
    composition: PilotComposition,
    state: dict[str, Any],
    receipt: dict[str, Any],
) -> None:
    if not isinstance(receipt, dict) or receipt.get("schema") != CALL_SCHEMA:
        raise CompositionError(f"call receipt schema must be {CALL_SCHEMA}")
    required = {
        "schema",
        "call_id",
        "task_id",
        "arm",
        "stage",
        "attempt",
        "backend",
        "prompt_template",
        "prompt_sha256",
        "dispatch_receipt_sha256",
        "session_id",
        "outcome",
        "output",
        "ledger_call",
    }
    unknown = set(receipt) - required
    missing = required - set(receipt)
    if missing or unknown:
        raise CompositionError(
            f"call receipt fields mismatch; missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    for key in ("call_id", "task_id", "arm", "stage", "backend", "prompt_sha256", "dispatch_receipt_sha256", "session_id", "outcome"):
        _nonempty(receipt[key], f"call receipt {key}")
    if receipt["task_id"] != state["task_id"] or receipt["arm"] != state["arm"]:
        raise CompositionError("call receipt task/arm contradicts the active state")
    if receipt["stage"] != state["next_stage"] or receipt["stage"] not in CALL_STAGES:
        raise CompositionError("call receipt stage is not the deterministic next stage")
    _number(receipt["attempt"], "call receipt attempt", integer=True)
    expected_attempt = 1 + sum(
        existing["stage"] == receipt["stage"] for existing in state["calls"]
    )
    if receipt["attempt"] != expected_attempt:
        raise CompositionError(
            f"call receipt attempt must be the deterministic ordinal {expected_attempt}"
        )
    if receipt["outcome"] not in CALL_OUTCOMES:
        raise CompositionError(f"unsupported call receipt outcome {receipt['outcome']!r}")

    expected = _expected_stage(composition, state)
    if receipt["backend"] != expected.backend:
        raise CompositionError("call receipt backend contradicts the frozen stage")
    prompt = receipt["prompt_template"]
    if not isinstance(prompt, dict) or set(prompt) != {"name", "sha256"}:
        raise CompositionError("call receipt prompt_template must contain exactly name and sha256")
    if prompt != _template(composition, expected.prompt_template):
        raise CompositionError("call receipt prompt template contradicts the frozen stage")
    expected_prompt_sha = hashlib.sha256(render_next_prompt(composition, state)).hexdigest()
    if receipt["prompt_sha256"] != expected_prompt_sha:
        raise CompositionError("call receipt prompt hash omits or changes frozen causal inputs")

    _sha256(receipt["prompt_sha256"], "call receipt prompt_sha256")
    _sha256(receipt["dispatch_receipt_sha256"], "call receipt dispatch_receipt_sha256")
    output = receipt["output"]
    if not isinstance(output, dict) or set(output) != {"kind", "text", "sha256"}:
        raise CompositionError("call receipt output must contain exactly kind, text, and sha256")
    text = _nonempty(output["text"], "call receipt output.text")
    _sha256(output["sha256"], "call receipt output.sha256")
    expected_kind = (
        "question"
        if receipt["outcome"] == "question"
        else "error"
        if receipt["outcome"] == "error"
        else "plan"
        if receipt["stage"] == "driver_plan"
        else "candidate_patch"
    )
    if output["kind"] != expected_kind:
        raise CompositionError(
            f"call receipt output.kind must be {expected_kind!r} for this stage/outcome"
        )
    if output["sha256"] != _sha_text(text):
        raise CompositionError("call receipt output hash mismatch")
    if receipt["outcome"] == "question" and state["arm"] != "arm_c":
        raise CompositionError("only arm_c may route a model question to the operator")

    if any(existing["call_id"] == receipt["call_id"] for existing in state["calls"]):
        raise CompositionError("call_id is already present in this arm state")
    if any(existing["session_id"] == receipt["session_id"] for existing in state["calls"]):
        raise CompositionError("fresh_session_per_call violated inside this arm state")

    backend = composition.backends[expected.backend]
    call = receipt["ledger_call"]
    if not isinstance(call, dict) or set(call) != CALL_FIELDS:
        raise CompositionError("ledger_call must contain the exact ledger.Call fields")
    expected_fields = {
        "account": backend.account,
        "model": backend.model_id,
        "tier": backend.tier,
        "task_id": state["task_id"],
        "phase": state["arm"],
        "effort": backend.effort,
    }
    for key, value in expected_fields.items():
        if call.get(key) != value:
            raise CompositionError(f"ledger_call.{key} contradicts the frozen backend")
    for key in ("ts", "account", "model", "tier", "task_id", "phase", "outcome", "effort", "note"):
        _nonempty(call.get(key), f"ledger_call.{key}")
    for key in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "trial"):
        _number(call.get(key), f"ledger_call.{key}", integer=True)
    for key in ("cost_usd", "latency_ms"):
        _number(call.get(key), f"ledger_call.{key}")
    try:
        timestamp = datetime.fromisoformat(call["ts"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise CompositionError("ledger_call.ts must be ISO-8601") from exc
    if timestamp.tzinfo is None:
        raise CompositionError("ledger_call.ts must include a timezone")
    expected_call_outcome = (
        "error"
        if receipt["outcome"] == "error"
        else "partial"
        if receipt["outcome"] == "question"
        else "pass"
    )
    if call["outcome"] != expected_call_outcome:
        raise CompositionError("ledger_call.outcome contradicts the call receipt outcome")
    extra = call.get("extra")
    if not isinstance(extra, dict):
        raise CompositionError("ledger_call.extra must be an object")
    extra_expected = {
        "backend_manifest_sha256": composition.sha256,
        "backend_surface": backend.surface,
        "cost_basis": backend.cost_basis,
        "dispatch_receipt_sha256": receipt["dispatch_receipt_sha256"],
        "prompt_template_sha256": prompt["sha256"],
        "runtime_model_id": backend.model_id,
        "session_id": receipt["session_id"],
        "tool_versions": composition.tool_versions,
    }
    for key, value in extra_expected.items():
        if extra.get(key) != value:
            raise CompositionError(f"ledger_call.extra.{key} contradicts the call receipt")
    if extra.get("telemetry_complete") is not True:
        raise CompositionError("ledger_call telemetry is incomplete")
    if backend.cost_basis != "real-billed" and backend.cost_basis not in call["note"]:
        raise CompositionError("non-billed ledger_call note must name its cost basis")


def _render_operator_question(
    composition: PilotComposition,
    state: dict[str, Any],
    question: str,
    evidence_sha256: str,
) -> tuple[str, str]:
    arm = composition.arms["arm_c"]
    assert arm.question_route is not None
    template = composition.templates[arm.question_route.question_template]
    raw = template.raw.decode("utf-8")
    replacements = {
        "{{TASK_ID}}": state["task_id"],
        "{{QUESTION}}": question,
        "{{EVIDENCE_SHA256}}": evidence_sha256,
    }
    missing = [marker for marker in replacements if marker not in raw]
    if missing:
        raise CompositionError(f"operator question template is missing markers: {missing}")
    unknown = set(re.findall(r"\{\{[A-Z_]+\}\}", raw)) - set(replacements)
    if unknown:
        raise CompositionError(f"operator question template has unknown markers: {sorted(unknown)}")
    for marker, value in replacements.items():
        raw = raw.replace(marker, value)
    return raw, template.sha256


def _route_after_failure(state: dict[str, Any], arm: PilotArm) -> None:
    if state["repair_calls"] < arm.repair.max_calls:
        state["next_stage"] = "repair"
        return
    if state["escalation_index"] < len(arm.escalations):
        state["next_stage"] = "escalation"
        return
    state["status"] = "FAILED"
    state["next_stage"] = None


def record_pilot_call(
    composition: PilotComposition,
    state: dict[str, Any],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    _validate_state(composition, state)
    if state["status"] != "ACTIVE" or state["next_stage"] not in CALL_STAGES:
        raise CompositionError("arm state is not waiting for a model call")
    _validate_call_receipt(composition, state, receipt)
    updated = copy.deepcopy(state)
    updated["calls"].append(copy.deepcopy(receipt))
    stage = receipt["stage"]
    outcome = receipt["outcome"]
    arm = composition.arms[updated["arm"]]
    if stage == "repair":
        # A repair invocation consumes the one preregistered repair budget even
        # when it asks a question instead of producing a candidate.
        updated["repair_calls"] += 1

    if outcome == "question":
        assert arm.question_route is not None
        if len(updated["questions"]) >= arm.question_route.max_questions:
            updated["status"] = "FAILED"
            updated["next_stage"] = None
        else:
            evidence_sha = receipt["output"]["sha256"]
            rendered, template_sha = _render_operator_question(
                composition, updated, receipt["output"]["text"], evidence_sha
            )
            question_id = _sha_text(
                f"{updated['task_id']}:{updated['arm']}:{receipt['call_id']}:{evidence_sha}"
            )
            asked_at = _now()
            updated["questions"].append(
                {
                    "question_id": question_id,
                    "intervention_id": None,
                    "call_id": receipt["call_id"],
                    "asked_at": asked_at,
                    "question": receipt["output"]["text"],
                    "question_sha256": evidence_sha,
                    "rendered": rendered,
                    "rendered_sha256": _sha_text(rendered),
                    "question_template_sha256": template_sha,
                    "answer": None,
                    "answer_sha256": None,
                    "answered_at": None,
                }
            )
            updated["active_question_id"] = question_id
            updated["status"] = "WAITING_OPERATOR"
            updated["next_stage"] = None
    elif outcome == "error":
        # Provider/adapter failure is not a candidate failure and carries no
        # immutable acceptance report. Retrying it through a stronger model
        # would be an unregistered stopping-rule change, so preserve it and stop.
        updated["status"] = "FAILED"
        updated["next_stage"] = None
    elif stage == "driver_plan":
        updated["next_stage"] = "hands"
    else:
        updated["next_stage"] = "acceptance"
    return _seal_next(
        state,
        updated,
        kind="model_call",
        reference_sha256=hashlib.sha256(canonical_json(receipt)).hexdigest(),
    )


def _trace_for_repair(
    composition: PilotComposition,
    state: dict[str, Any],
    passed: bool,
) -> dict[str, Any] | None:
    if state["arm"] != "arm_a" or not state["calls"] or state["calls"][-1]["stage"] != "repair":
        return None
    hands_calls = [call for call in state["calls"] if call["stage"] in {"hands", "hands_resume"}]
    if not hands_calls:
        raise CompositionError("arm_a repair has no preceding hands output")
    repair = state["calls"][-1]
    hands = hands_calls[-1]
    arm = composition.arms["arm_a"]
    assert arm.driver is not None
    prior_failures = [
        attempt for attempt in state["acceptance_attempts"][:-1] if attempt["passed"] is False
    ]
    if not prior_failures:
        raise CompositionError("arm_a repair trace has no preceding failed acceptance report")
    failed_report = prior_failures[-1]["report"]
    row = {
        "schema": TRACE_SCHEMA,
        "task_id": state["task_id"],
        "tier": state["task_tier"],
        "hands_model": composition.backends[arm.hands.backend].model_id,
        "hands_output": hands["output"]["text"],
        "hands_output_sha256": hands["output"]["sha256"],
        "validator_report": failed_report,
        "validator_report_sha256": _sha_text(failed_report),
        "driver_model": composition.backends[arm.driver.backend].model_id,
        "driver_output": repair["output"]["text"],
        "driver_output_sha256": repair["output"]["sha256"],
        "repair_call_id": repair["call_id"],
        "passed": bool(passed),
    }
    row["trace_sha256"] = _sha_text(json.dumps(row, sort_keys=True, separators=(",", ":")))
    return row


ACCEPTANCE_FIELDS = {
    "schema",
    "receipt_sha256",
    "task_id",
    "arm",
    "attempt",
    "causal_call_id",
    "base_commit",
    "command",
    "command_sha256",
    "candidate_patch_sha256",
    "candidate_tree_sha256",
    "exit_code",
    "passed",
    "report",
    "report_sha256",
    "stdout_sha256",
    "stderr_sha256",
    "tool_versions",
    "recorded_at",
}


def acceptance_receipt_hash(receipt: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    return hashlib.sha256(canonical_json(unsigned)).hexdigest()


def _validate_acceptance_receipt(
    composition: PilotComposition,
    state: dict[str, Any],
    receipt: dict[str, Any],
) -> None:
    if not isinstance(receipt, dict) or set(receipt) != ACCEPTANCE_FIELDS:
        raise CompositionError("acceptance receipt fields do not match the frozen contract")
    if receipt.get("schema") != ACCEPTANCE_SCHEMA:
        raise CompositionError(f"acceptance receipt schema must be {ACCEPTANCE_SCHEMA}")
    if receipt.get("task_id") != state["task_id"] or receipt.get("arm") != state["arm"]:
        raise CompositionError("acceptance receipt task/arm contradicts the state")
    expected_attempt = len(state["acceptance_attempts"]) + 1
    if receipt.get("attempt") != expected_attempt:
        raise CompositionError(f"acceptance attempt must be {expected_attempt}")
    if not state["calls"] or receipt.get("causal_call_id") != state["calls"][-1]["call_id"]:
        raise CompositionError("acceptance receipt does not bind the causal model call")
    candidate = state["calls"][-1]["output"]
    if candidate["kind"] != "candidate_patch":
        raise CompositionError("acceptance can run only on a sealed candidate patch")
    if receipt.get("candidate_patch_sha256") != candidate["sha256"]:
        raise CompositionError("acceptance candidate patch contradicts the causal call")
    if receipt.get("base_commit") != state["base_commit"]:
        raise CompositionError("acceptance base_commit contradicts the task state")
    if receipt.get("command") != state["acceptance_command"]:
        raise CompositionError("acceptance command contradicts the immutable task state")
    if receipt.get("command_sha256") != _sha_text(state["acceptance_command"]):
        raise CompositionError("acceptance command hash mismatch")
    for key in (
        "candidate_patch_sha256",
        "candidate_tree_sha256",
        "stdout_sha256",
        "stderr_sha256",
        "report_sha256",
        "receipt_sha256",
    ):
        _sha256(receipt.get(key), f"acceptance receipt {key}")
    report = _nonempty(receipt.get("report"), "acceptance receipt report")
    if receipt["report_sha256"] != _sha_text(report):
        raise CompositionError("acceptance report hash mismatch")
    if receipt.get("tool_versions") != composition.acceptance_tool_versions:
        raise CompositionError("acceptance tool versions contradict the frozen manifest")
    if not isinstance(receipt.get("exit_code"), int) or isinstance(receipt["exit_code"], bool):
        raise CompositionError("acceptance exit_code must be an integer")
    if not isinstance(receipt.get("passed"), bool):
        raise CompositionError("acceptance passed must be boolean")
    if receipt["passed"] is not (receipt["exit_code"] == 0):
        raise CompositionError("acceptance passed must equal exit_code == 0")
    _nonempty(receipt.get("recorded_at"), "acceptance receipt recorded_at")
    if receipt["receipt_sha256"] != acceptance_receipt_hash(receipt):
        raise CompositionError("acceptance receipt hash is invalid")


def record_acceptance(
    composition: PilotComposition,
    state: dict[str, Any],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    _validate_state(composition, state)
    if state["status"] != "ACTIVE" or state["next_stage"] != "acceptance":
        raise CompositionError("arm state is not waiting for immutable acceptance")
    _validate_acceptance_receipt(composition, state, receipt)
    passed = receipt["passed"]
    updated = copy.deepcopy(state)
    updated["acceptance_attempts"].append(copy.deepcopy(receipt))
    trace = _trace_for_repair(composition, updated, passed)
    if trace is not None:
        updated["driver_traces"].append(trace)
    if passed:
        updated["status"] = "COMPLETE"
        updated["next_stage"] = None
    else:
        if updated["calls"][-1]["stage"] == "escalation":
            updated["escalation_index"] += 1
        _route_after_failure(updated, composition.arms[updated["arm"]])
    return _seal_next(
        state,
        updated,
        kind="acceptance",
        reference_sha256=receipt["receipt_sha256"],
    )


def answer_operator_question(
    composition: PilotComposition,
    state: dict[str, Any],
    *,
    question_id: str,
    answer: str,
    intervention_id: str,
) -> dict[str, Any]:
    _validate_state(composition, state)
    if state["arm"] != "arm_c" or state["status"] != "WAITING_OPERATOR":
        raise CompositionError("only a paused arm_c state accepts an operator answer")
    if question_id != state["active_question_id"]:
        raise CompositionError("operator answer does not name the active question")
    answer = _nonempty(answer, "operator answer")
    updated = copy.deepcopy(state)
    question = next(
        item for item in updated["questions"] if item["question_id"] == question_id
    )
    if question["answer"] is not None:
        raise CompositionError("operator question was already answered")
    _nonempty(intervention_id, "intervention_id")
    try:
        uuid.UUID(intervention_id)
    except ValueError as exc:
        raise CompositionError("intervention_id must be a UUID") from exc
    answered_at = _now()
    question["intervention_id"] = intervention_id
    question["answer"] = answer
    question["answer_sha256"] = _sha_text(answer)
    question["answered_at"] = answered_at
    question_receipt = {
        "schema": QUESTION_SCHEMA,
        "question_id": question_id,
        "task_id": state["task_id"],
        "arm": "arm_c",
        "intervention_id": intervention_id,
        "asked_at": question["asked_at"],
        "answered_at": answered_at,
        "question_sha256": question["question_sha256"],
        "answer_sha256": question["answer_sha256"],
    }
    _validate_question_receipt_replay(state, updated, question_receipt)
    updated["question_receipts"].append(question_receipt)
    updated["active_question_id"] = None
    updated["status"] = "ACTIVE"
    updated["next_stage"] = "hands_resume"
    return _seal_next(
        state,
        updated,
        kind="operator_answer",
        reference_sha256=hashlib.sha256(canonical_json(question_receipt)).hexdigest(),
    )


def decline_operator_question(
    composition: PilotComposition,
    state: dict[str, Any],
    *,
    question_id: str,
    reason: str,
    intervention_id: str,
) -> dict[str, Any]:
    _validate_state(composition, state)
    if state["arm"] != "arm_c" or state["status"] != "WAITING_OPERATOR":
        raise CompositionError("only a paused arm_c state accepts an operator decline")
    if question_id != state["active_question_id"]:
        raise CompositionError("operator decline does not name the active question")
    reason = _nonempty(reason, "decline reason")
    try:
        uuid.UUID(intervention_id)
    except (AttributeError, ValueError) as exc:
        raise CompositionError("intervention_id must be a UUID") from exc
    updated = copy.deepcopy(state)
    question = next(
        item for item in updated["questions"] if item["question_id"] == question_id
    )
    if question["answer"] is not None:
        raise CompositionError("operator question was already answered")
    answered_at = _now()
    question["intervention_id"] = intervention_id
    question["answer"] = reason
    question["answer_sha256"] = _sha_text(reason)
    question["answered_at"] = answered_at
    question["declined"] = True
    question_receipt = {
        "schema": QUESTION_SCHEMA,
        "question_id": question_id,
        "task_id": state["task_id"],
        "arm": "arm_c",
        "intervention_id": intervention_id,
        "asked_at": question["asked_at"],
        "answered_at": answered_at,
        "question_sha256": question["question_sha256"],
        "answer_sha256": question["answer_sha256"],
    }
    _validate_question_receipt_replay(state, updated, question_receipt)
    updated["question_receipts"].append(question_receipt)
    updated["active_question_id"] = None
    updated["status"] = "FAILED"
    updated["next_stage"] = None
    return _seal_next(
        state,
        updated,
        kind="operator_decline",
        reference_sha256=hashlib.sha256(canonical_json(question_receipt)).hexdigest(),
    )


def read_state(composition: PilotComposition, path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise CompositionError("pilot arm state log does not exist")
    states: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CompositionError(f"invalid pilot state JSON at line {number}") from exc
        if not isinstance(value, dict):
            raise CompositionError(f"pilot state line {number} must be an object")
        _validate_state(composition, value)
        if value["state_sequence"] != len(states):
            raise CompositionError("pilot state sequence is not contiguous")
        expected_parent = states[-1]["state_sha256"] if states else None
        if value["parent_state_sha256"] != expected_parent:
            raise CompositionError("pilot state parent chain is broken or forked")
        if states:
            _validate_parent_transition(states[-1], value)
            _replay_transition_receipt(composition, states[-1], value)
        states.append(value)
    if not states:
        raise CompositionError("pilot arm state log is empty")
    return states[-1]


def write_state(
    path: Path,
    composition: PilotComposition,
    state: dict[str, Any],
) -> None:
    _validate_state(composition, state)
    if path.exists() and path.stat().st_size:
        previous = read_state(composition, path)
        if state["state_sequence"] != previous["state_sequence"] + 1:
            raise CompositionError("refusing non-contiguous state append")
        if state["parent_state_sha256"] != previous["state_sha256"]:
            raise CompositionError("refusing state fork or rewritten parent")
    elif state["state_sequence"] != 0 or state["parent_state_sha256"] is not None:
        raise CompositionError("a new state log must begin with the initial state")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json(state).decode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())


TRACE_FIELDS = {
    "schema",
    "task_id",
    "tier",
    "hands_model",
    "hands_output",
    "hands_output_sha256",
    "validator_report",
    "validator_report_sha256",
    "driver_model",
    "driver_output",
    "driver_output_sha256",
    "repair_call_id",
    "passed",
    "trace_sha256",
}


def _validate_trace_content(row: dict[str, Any], label: str) -> None:
    if not isinstance(row, dict) or set(row) != TRACE_FIELDS:
        raise CompositionError(f"{label} fields do not match the driver trace schema")
    if row.get("schema") != TRACE_SCHEMA or not isinstance(row.get("passed"), bool):
        raise CompositionError(f"{label} schema/passed field is invalid")
    for key in ("task_id", "tier", "hands_model", "driver_model", "repair_call_id"):
        _nonempty(row.get(key), f"{label}.{key}")
    for text_key, hash_key in (
        ("hands_output", "hands_output_sha256"),
        ("validator_report", "validator_report_sha256"),
        ("driver_output", "driver_output_sha256"),
    ):
        text = _nonempty(row.get(text_key), f"{label}.{text_key}")
        if row.get(hash_key) != _sha_text(text):
            raise CompositionError(f"{label}.{hash_key} mismatch")
    unsigned = dict(row)
    trace_hash = unsigned.pop("trace_sha256")
    expected = _sha_text(json.dumps(unsigned, sort_keys=True, separators=(",", ":")))
    if trace_hash != expected:
        raise CompositionError(f"{label} whole-row hash mismatch")


def _validate_trace_causality(
    composition: PilotComposition,
    state: dict[str, Any],
    row: dict[str, Any],
) -> None:
    if state["arm"] != "arm_a" or row["task_id"] != state["task_id"]:
        raise CompositionError("driver trace is not bound to this Arm-A task state")
    repair_indexes = [
        index
        for index, call in enumerate(state["calls"])
        if call["call_id"] == row["repair_call_id"] and call["stage"] == "repair"
    ]
    if len(repair_indexes) != 1:
        raise CompositionError("driver trace repair_call_id is not unique in the state")
    repair_index = repair_indexes[0]
    repair = state["calls"][repair_index]
    hands_candidates = [
        call
        for call in state["calls"][:repair_index]
        if call["stage"] in {"hands", "hands_resume"}
        and call["outcome"] == "completed"
    ]
    if not hands_candidates:
        raise CompositionError("driver trace has no causal cheap-hands candidate")
    hands = hands_candidates[-1]
    failures = [
        receipt
        for receipt in state["acceptance_attempts"]
        if receipt["causal_call_id"] == hands["call_id"] and receipt["passed"] is False
    ]
    outcomes = [
        receipt
        for receipt in state["acceptance_attempts"]
        if receipt["causal_call_id"] == repair["call_id"]
    ]
    if len(failures) != 1 or len(outcomes) != 1:
        raise CompositionError("driver trace acceptance causality is incomplete or ambiguous")
    arm = composition.arms["arm_a"]
    assert arm.driver is not None
    expected = {
        "tier": state["task_tier"],
        "hands_model": composition.backends[arm.hands.backend].model_id,
        "hands_output": hands["output"]["text"],
        "validator_report": failures[0]["report"],
        "driver_model": composition.backends[arm.driver.backend].model_id,
        "driver_output": repair["output"]["text"],
        "passed": outcomes[0]["passed"],
    }
    for key, value in expected.items():
        if row.get(key) != value:
            raise CompositionError(f"driver trace {key} contradicts causal state evidence")


def append_driver_traces(
    composition: PilotComposition,
    evidence_root: Path,
    state: dict[str, Any],
    *,
    forbidden_roots: list[Path],
) -> int:
    _validate_state(composition, state)
    if state.get("arm") != "arm_a":
        if state.get("driver_traces"):
            raise CompositionError("non-arm_a state cannot carry driver traces")
        return 0
    relative = composition.arms["arm_a"].driver_trace_path
    if relative is None:
        raise CompositionError("Arm A has no frozen driver trace path")
    if not forbidden_roots:
        raise CompositionError("driver trace custody requires target/packet/worktree exclusions")
    root = evidence_root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise CompositionError("frozen driver trace path escapes evidence custody") from exc
    for forbidden in forbidden_roots:
        forbidden = forbidden.resolve()
        try:
            root.relative_to(forbidden)
        except ValueError:
            pass
        else:
            raise CompositionError("driver trace evidence root enters target/packet/worktree")
        try:
            path.relative_to(forbidden)
        except ValueError:
            pass
        else:
            raise CompositionError("driver trace path enters target/packet/worktree")
    existing_ids: set[str] = set()
    if path.exists():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CompositionError(f"invalid driver trace row {number}") from exc
            trace_hash = row.get("trace_sha256")
            if not isinstance(trace_hash, str) or trace_hash in existing_ids:
                raise CompositionError(f"invalid or duplicate driver trace row {number}")
            _validate_trace_content(row, f"driver trace row {number}")
            existing_ids.add(trace_hash)
    pending = [row for row in state.get("driver_traces", []) if row["trace_sha256"] not in existing_ids]
    if not pending:
        return 0
    for row in pending:
        _validate_trace_content(row, "pending driver trace")
        _validate_trace_causality(composition, state, row)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in pending:
            handle.write(canonical_json(row).decode("utf-8"))
        handle.flush()
    return len(pending)
