from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .manifest import canonical_json
from .pilot_manifest import PilotArm, PilotComposition, Stage


STATE_SCHEMA = "tier-bench/pilot-arm-state@1"
CALL_SCHEMA = "tier-bench/pilot-call-receipt@1"
TRACE_SCHEMA = "tier-bench/driver-trace@2"
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
    return {
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
        "active_question_id": None,
        "driver_traces": [],
        "created_at": _now(),
        "updated_at": _now(),
    }


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
    if state.get("schema") != STATE_SCHEMA:
        raise CompositionError(f"state schema must be {STATE_SCHEMA}")
    if state.get("composition_manifest_sha256") != composition.sha256:
        raise CompositionError("state is bound to a different pilot composition manifest")
    if state.get("protocol_commit") != composition.protocol_commit:
        raise CompositionError("state protocol commit contradicts the composition manifest")
    if state.get("arm") not in composition.arms:
        raise CompositionError("state arm is not in the composition manifest")


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
    expected_call_outcome = "error" if receipt["outcome"] == "error" else "pass"
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
            updated["questions"].append(
                {
                    "question_id": question_id,
                    "call_id": receipt["call_id"],
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
        if stage == "repair":
            updated["repair_calls"] += 1
        updated["next_stage"] = "acceptance"
    updated["updated_at"] = _now()
    return updated


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


def record_acceptance(
    composition: PilotComposition,
    state: dict[str, Any],
    *,
    passed: bool,
    report: str,
) -> dict[str, Any]:
    _validate_state(composition, state)
    if state["status"] != "ACTIVE" or state["next_stage"] != "acceptance":
        raise CompositionError("arm state is not waiting for immutable acceptance")
    if not isinstance(passed, bool):
        raise CompositionError("acceptance passed must be boolean")
    report = _nonempty(report, "acceptance report")
    updated = copy.deepcopy(state)
    updated["acceptance_attempts"].append(
        {
            "attempt": len(updated["acceptance_attempts"]) + 1,
            "passed": passed,
            "report": report,
            "report_sha256": _sha_text(report),
            "recorded_at": _now(),
        }
    )
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
    updated["updated_at"] = _now()
    return updated


def answer_operator_question(
    composition: PilotComposition,
    state: dict[str, Any],
    *,
    question_id: str,
    answer: str,
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
    question["answer"] = answer
    question["answer_sha256"] = _sha_text(answer)
    question["answered_at"] = _now()
    updated["active_question_id"] = None
    updated["status"] = "ACTIVE"
    updated["next_stage"] = "hands_resume"
    updated["updated_at"] = _now()
    return updated


def decline_operator_question(
    composition: PilotComposition,
    state: dict[str, Any],
    *,
    question_id: str,
    reason: str,
) -> dict[str, Any]:
    updated = answer_operator_question(
        composition, state, question_id=question_id, answer=_nonempty(reason, "decline reason")
    )
    updated["status"] = "FAILED"
    updated["next_stage"] = None
    updated["questions"][-1]["declined"] = True
    updated["updated_at"] = _now()
    return updated


def write_state(path: Path, state: dict[str, Any]) -> None:
    path.write_bytes(canonical_json(state))


def read_state(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CompositionError("pilot arm state must be a JSON object")
    return value


def append_driver_traces(
    composition: PilotComposition,
    repository_root: Path,
    state: dict[str, Any],
) -> int:
    _validate_state(composition, state)
    if state.get("arm") != "arm_a":
        if state.get("driver_traces"):
            raise CompositionError("non-arm_a state cannot carry driver traces")
        return 0
    relative = composition.arms["arm_a"].driver_trace_path
    if relative is None:
        raise CompositionError("Arm A has no frozen driver trace path")
    root = repository_root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise CompositionError("frozen driver trace path escapes the repository") from exc
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
            unsigned = dict(row)
            unsigned.pop("trace_sha256", None)
            expected = _sha_text(json.dumps(unsigned, sort_keys=True, separators=(",", ":")))
            if trace_hash != expected:
                raise CompositionError(f"driver trace row {number} hash mismatch")
            existing_ids.add(trace_hash)
    pending = [row for row in state.get("driver_traces", []) if row["trace_sha256"] not in existing_ids]
    if not pending:
        return 0
    for row in pending:
        unsigned = dict(row)
        trace_hash = unsigned.pop("trace_sha256", None)
        expected = _sha_text(json.dumps(unsigned, sort_keys=True, separators=(",", ":")))
        if trace_hash != expected:
            raise CompositionError("pending driver trace hash mismatch")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in pending:
            handle.write(canonical_json(row).decode("utf-8"))
        handle.flush()
    return len(pending)
