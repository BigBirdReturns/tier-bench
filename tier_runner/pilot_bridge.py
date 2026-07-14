from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import uuid
from typing import Any

from .core import (
    BACKEND_SCHEMA,
    RunError,
    _backend_artifacts,
    _changed_files,
    _git,
    _git_common_dir,
    _in_scope,
    _inside,
    _normalize_scope,
    _packet_temp_root,
    _prepare_packet,
    _register_session,
    _repo_root,
    _safe_id,
    _sync_packet,
)
from .manifest import ManifestError, sha256_file
from .pilot_composition import (
    ACCEPTANCE_SCHEMA,
    CALL_SCHEMA,
    CompositionError,
    acceptance_receipt_hash,
    canonical_json,
    new_pilot_arm_state,
    read_state,
    record_acceptance,
    record_pilot_call,
    render_next_prompt,
    write_state,
)
from .pilot_manifest import PilotComposition, Stage, load_pilot_composition


SESSION_SCHEMA = "tier-bench/tier-pilot-bridge-session@1"
RECEIPT_SCHEMA = "tier-bench/tier-pilot-fixture-bridge-receipt@1"
DISPATCH_SCHEMA = "tier-bench/tier-pilot-fixture-dispatch-receipt@1"
PROVIDER_EVIDENCE_SCHEMA = "tier-bench/tier-pilot-fixture-provider-evidence@1"
ACCEPTANCE_EVIDENCE_SCHEMA = "tier-bench/tier-pilot-fixture-acceptance-evidence@1"
EXECUTION_MODE = "fixture"
FIXTURE_EXECUTOR_ID = "tier-bench/in-process-data-fixture@1"
QUESTION_ENVELOPE_SCHEMA = "tier-bench/tier-pilot-operator-question@1"
QUESTION_CATEGORIES = {"interpretation", "policy", "authorization"}
MAX_QUESTION_BYTES = 512
MAX_ACCEPTANCE_OUTPUT_BYTES = 8192
FIXTURE_RESPONSE_FIELDS = {"outcome", "text", "session_id", "changes", "fault"}
PROVIDER_OUTPUT_FIELDS = {"outcome", "text"}
PROVIDER_RESULT_FIELDS = {"schema", "calls", "pilot_output", "artifacts"}


class BridgeError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_json(path: Path, value: Any) -> dict[str, str]:
    raw = canonical_json(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"path": path.name, "sha256": _sha(raw)}


def _artifact_ref(root: Path, path: Path) -> dict[str, str]:
    return {"path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)}


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BridgeError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise BridgeError(f"{label} must be a JSON object")
    return value


def _stage(composition: PilotComposition, state: dict[str, Any]) -> Stage:
    arm = composition.arms[state["arm"]]
    stage = state["next_stage"]
    if stage == "driver_plan":
        assert arm.driver is not None
        return arm.driver
    if stage == "hands":
        return arm.hands
    if stage == "repair":
        return arm.repair
    if stage == "escalation":
        try:
            return arm.escalations[state["escalation_index"]]
        except IndexError as exc:
            raise BridgeError("frozen escalation index is unavailable") from exc
    if stage == "hands_resume":
        assert arm.question_route is not None
        return Stage(arm.hands.backend, arm.question_route.resume_prompt_template)
    raise BridgeError(f"state is not waiting for a provider call: {stage!r}")


def _fixture_script(value: Any) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(value, list) or not value:
        raise BridgeError("fixture_script must be a non-empty data-only response array")
    validated: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != FIXTURE_RESPONSE_FIELDS:
            raise BridgeError(f"fixture_script[{index}] fields are invalid")
        if item.get("outcome") not in {"completed", "question", "error"}:
            raise BridgeError(f"fixture_script[{index}].outcome is invalid")
        if not isinstance(item.get("text"), str) or not item["text"]:
            raise BridgeError(f"fixture_script[{index}].text must be non-empty")
        if not isinstance(item.get("session_id"), str) or not item["session_id"]:
            raise BridgeError(f"fixture_script[{index}].session_id must be non-empty")
        if item.get("fault") not in {None, "before_result"}:
            raise BridgeError(f"fixture_script[{index}].fault is invalid")
        changes = item.get("changes")
        if not isinstance(changes, dict):
            raise BridgeError(f"fixture_script[{index}].changes must be an object")
        for raw, content in changes.items():
            if not isinstance(raw, str):
                raise BridgeError(f"fixture_script[{index}] change path must be a string")
            pure = PurePosixPath(raw.replace("\\", "/"))
            if pure.is_absolute() or ".." in pure.parts or not pure.parts or pure.parts[0] == ".git":
                raise BridgeError(f"fixture_script[{index}] change path is unsafe: {raw!r}")
            if content is not None and not isinstance(content, str):
                raise BridgeError(f"fixture_script[{index}] change content must be text or null")
        validated.append({
            "outcome": item["outcome"],
            "text": item["text"],
            "session_id": item["session_id"],
            "changes": dict(changes),
            "fault": item["fault"],
        })
    raw = canonical_json(validated)
    return validated, _sha(raw)


def _last_candidate(state: dict[str, Any]) -> bytes:
    for call in reversed(state["calls"]):
        if call["outcome"] == "completed" and call["output"]["kind"] == "candidate_patch":
            return call["output"]["text"].encode("utf-8")
    return b""


def _patch(worktree: Path) -> bytes:
    return subprocess.run(
        ["git", "diff", "--binary", "--full-index", "HEAD"],
        cwd=worktree,
        check=True,
        capture_output=True,
    ).stdout


def _ignored_scoped_files(
    worktree: Path, scopes: list[tuple[str, bool]]
) -> list[str]:
    ignored = _git(
        worktree, "ls-files", "--others", "--ignored", "--exclude-standard"
    ).stdout.splitlines()
    return sorted(
        path.replace("\\", "/")
        for path in ignored
        if path.strip() and _in_scope(path.replace("\\", "/"), scopes)
    )


def _refuse_ignored_scope(worktree: Path, scopes: list[tuple[str, bool]]) -> None:
    ignored = _ignored_scoped_files(worktree, scopes)
    if ignored:
        raise BridgeError(
            "ignored files in pilot scope cannot be sealed by the fixture patch contract: "
            f"{ignored}"
        )


def _tree(worktree: Path) -> str:
    descriptor, temporary = tempfile.mkstemp(prefix="tier-pilot-index-")
    os.close(descriptor)
    Path(temporary).unlink()
    env = dict(os.environ)
    env["GIT_INDEX_FILE"] = temporary
    try:
        read = subprocess.run(
            ["git", "read-tree", "HEAD"], cwd=worktree, env=env,
            capture_output=True, text=True,
        )
        if read.returncode:
            raise BridgeError(f"cannot seed candidate tree index: {read.stderr.strip()}")
        add = subprocess.run(
            ["git", "add", "-A"], cwd=worktree, env=env,
            capture_output=True, text=True,
        )
        if add.returncode:
            raise BridgeError(f"cannot stage candidate tree: {add.stderr.strip()}")
        written = subprocess.run(
            ["git", "write-tree"], cwd=worktree, env=env,
            capture_output=True, text=True,
        )
        if written.returncode:
            raise BridgeError(f"cannot write candidate tree: {written.stderr.strip()}")
        value = written.stdout.strip()
    finally:
        Path(temporary).unlink(missing_ok=True)
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise BridgeError("candidate tree did not produce a full Git object id")
    raw = subprocess.run(
        ["git", "cat-file", "tree", value], cwd=worktree, check=True,
        capture_output=True,
    ).stdout
    return _sha(raw)


def _question_envelope(text: str) -> dict[str, str]:
    if len(text.encode("utf-8")) > MAX_QUESTION_BYTES:
        raise BridgeError("operator question envelope exceeds the bounded byte limit")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BridgeError("operator question must be a strict JSON envelope") from exc
    fields = {"schema", "category", "question"}
    if not isinstance(value, dict) or set(value) != fields:
        raise BridgeError("operator question envelope fields are invalid")
    if value.get("schema") != QUESTION_ENVELOPE_SCHEMA:
        raise BridgeError("operator question envelope schema is invalid")
    if value.get("category") not in QUESTION_CATEGORIES:
        raise BridgeError("operator question category is invalid")
    question = value.get("question")
    if (
        not isinstance(question, str)
        or not (1 <= len(question.encode("utf-8")) <= 280)
        or "\n" in question
        or "\r" in question
        or question.count("?") != 1
    ):
        raise BridgeError("operator question must be one bounded single-line question")
    canonical = canonical_json(value).decode("utf-8").rstrip("\n")
    if text != canonical:
        raise BridgeError("operator question envelope is not canonical JSON")
    return value


def _provider_result(path: Path, call_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    value = _read_object(path, "provider result")
    if set(value) != PROVIDER_RESULT_FIELDS or value.get("schema") != BACKEND_SCHEMA:
        raise BridgeError("provider result fields/schema do not match the bridge contract")
    calls = value.get("calls")
    if not isinstance(calls, list) or len(calls) != 1 or not isinstance(calls[0], dict):
        raise BridgeError("one bridge dispatch must preserve exactly one provider ledger call")
    output = value.get("pilot_output")
    if not isinstance(output, dict) or set(output) != PROVIDER_OUTPUT_FIELDS:
        raise BridgeError("provider pilot_output must contain exactly outcome and text")
    if output.get("outcome") not in {"completed", "question", "error"}:
        raise BridgeError("provider pilot_output outcome is invalid")
    if not isinstance(output.get("text"), str) or not output["text"]:
        raise BridgeError("provider pilot_output text must be non-empty")
    if output.get("outcome") == "question":
        _question_envelope(output["text"])
    artifacts = _backend_artifacts(value, call_dir)
    if "provider_raw" not in artifacts:
        raise BridgeError("provider result must preserve a provider_raw artifact descriptor")
    try:
        raw = json.loads(artifacts["provider_raw"][0].read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BridgeError("fixture provider_raw must be an exact JSON output witness") from exc
    if raw != {"pilot_output": output}:
        raise BridgeError("fixture provider_raw does not deterministically open pilot_output")
    return calls[0], output


def _append_state(
    path: Path, composition: PilotComposition, state: dict[str, Any]
) -> dict[str, Any]:
    write_state(path, composition, state)
    replayed = read_state(composition, path)
    if replayed["state_sha256"] != state["state_sha256"]:
        raise BridgeError("state append did not replay to the exact transition")
    return replayed


def _read_journal(path: Path, call_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    allowed = ["PREPARED", "DISPATCH_STARTED", "EVIDENCE_SEALED"]
    for sequence, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BridgeError(f"call journal row {sequence} is invalid JSON") from exc
        fields = {
            "schema", "sequence", "call_id", "event", "previous_event_sha256",
            "recorded_at", "event_sha256",
        }
        if not isinstance(row, dict) or set(row) != fields:
            raise BridgeError(f"call journal row {sequence} fields are invalid")
        if row.get("schema") != "tier-bench/tier-pilot-call-journal-event@1":
            raise BridgeError(f"call journal row {sequence} schema is invalid")
        if row.get("sequence") != sequence or row.get("call_id") != call_id:
            raise BridgeError(f"call journal row {sequence} coordinate is invalid")
        if sequence >= len(allowed) or row.get("event") != allowed[sequence]:
            raise BridgeError(f"call journal row {sequence} transition is invalid")
        previous = rows[-1]["event_sha256"] if rows else None
        if row.get("previous_event_sha256") != previous:
            raise BridgeError(f"call journal row {sequence} chain is invalid")
        claimed = row.get("event_sha256")
        unhashed = dict(row)
        del unhashed["event_sha256"]
        if claimed != _sha(canonical_json(unhashed)):
            raise BridgeError(f"call journal row {sequence} hash is invalid")
        rows.append(row)
    return rows


def _append_journal(path: Path, event: str, call_id: str) -> None:
    rows = _read_journal(path, call_id)
    previous = rows[-1]["event_sha256"] if rows else None
    sequence = len(rows)
    row = {
        "schema": "tier-bench/tier-pilot-call-journal-event@1",
        "sequence": sequence,
        "call_id": call_id,
        "event": event,
        "previous_event_sha256": previous,
        "recorded_at": _now(),
    }
    row["event_sha256"] = _sha(canonical_json(row))
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json(row).decode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    _read_journal(path, call_id)


def _open_fixture_ref(root: Path, value: Any, label: str) -> tuple[Path, str]:
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise BridgeError(f"{label} artifact reference fields are invalid")
    relative = value.get("path")
    expected = value.get("sha256")
    if not isinstance(relative, str) or not isinstance(expected, str):
        raise BridgeError(f"{label} artifact reference values are invalid")
    path = (root / relative).resolve()
    if not _inside(path, root) or not path.is_file():
        raise BridgeError(f"{label} artifact is missing or escapes fixture custody")
    actual = sha256_file(path)
    if actual != expected:
        raise BridgeError(f"{label} artifact hash drifted")
    return path, actual


def _verify_fixture_evidence(session_dir: Path) -> None:
    calls_dir = session_dir / "calls"
    if not calls_dir.is_dir():
        return
    for call_dir in sorted(path for path in calls_dir.iterdir() if path.is_dir()):
        dispatch_path = call_dir / "dispatch.json"
        if not dispatch_path.is_file():
            raise BridgeError(f"prior fixture call {call_dir.name} has no dispatch evidence")
        dispatch = _read_object(dispatch_path, "fixture dispatch")
        call_id = dispatch.get("call_id")
        if (
            dispatch.get("schema") != DISPATCH_SCHEMA
            or dispatch.get("execution_mode") != EXECUTION_MODE
            or dispatch.get("executor_identity") != FIXTURE_EXECUTOR_ID
            or not isinstance(call_id, str)
            or not call_id
        ):
            raise BridgeError(f"prior fixture call {call_dir.name} dispatch identity drifted")
        journal = _read_journal(call_dir / "journal.jsonl", call_id)
        if [row["event"] for row in journal] != [
            "PREPARED", "DISPATCH_STARTED", "EVIDENCE_SEALED"
        ]:
            raise BridgeError(f"prior fixture call {call_dir.name} is not durably sealed")
        provider_path = call_dir / "provider-evidence.json"
        provider = _read_object(provider_path, "fixture provider evidence")
        provider_fields = {
            "schema", "execution_mode", "executor_identity", "call_id",
            "dispatch_receipt_sha256", "provider_result", "raw_artifacts",
        }
        if (
            set(provider) != provider_fields
            or provider.get("schema") != PROVIDER_EVIDENCE_SCHEMA
            or provider.get("execution_mode") != EXECUTION_MODE
            or provider.get("executor_identity") != FIXTURE_EXECUTOR_ID
            or provider.get("call_id") != call_id
            or provider.get("dispatch_receipt_sha256") != _sha(dispatch_path.read_bytes())
        ):
            raise BridgeError(f"prior fixture call {call_dir.name} provider custody drifted")
        result_path, _ = _open_fixture_ref(
            session_dir, provider.get("provider_result"), "fixture provider result"
        )
        try:
            _provider_result(result_path, call_dir)
        except RunError as exc:
            raise BridgeError(f"prior fixture provider evidence is invalid: {exc}") from exc
        result = _read_object(result_path, "fixture provider result")
        expected_raw: list[tuple[str, Path, str]] = []
        for item in result["artifacts"]:
            expected_raw.append((
                item["name"], (call_dir / item["path"]).resolve(), item["sha256"]
            ))
        opened_raw: list[tuple[str, Path, str]] = []
        raws = provider.get("raw_artifacts")
        if not isinstance(raws, list):
            raise BridgeError("fixture raw_artifacts must be an array")
        for index, raw in enumerate(raws):
            if not isinstance(raw, dict) or set(raw) != {"name", "path", "sha256"}:
                raise BridgeError(f"fixture raw artifact {index} fields are invalid")
            opened, digest = _open_fixture_ref(
                session_dir, {"path": raw["path"], "sha256": raw["sha256"]},
                f"fixture raw artifact {index}",
            )
            opened_raw.append((raw["name"], opened, digest))
        if opened_raw != expected_raw:
            raise BridgeError("fixture raw artifact custody is not an exact ordered match")
        acceptance_path = call_dir / "acceptance-evidence.json"
        if not acceptance_path.exists():
            continue
        acceptance = _read_object(acceptance_path, "fixture acceptance evidence")
        acceptance_fields = {
            "schema", "execution_mode", "executor_identity", "receipt_sha256",
            "receipt", "stdout", "stderr", "candidate_before", "candidate_after", "report",
        }
        if (
            set(acceptance) != acceptance_fields
            or acceptance.get("schema") != ACCEPTANCE_EVIDENCE_SCHEMA
            or acceptance.get("execution_mode") != EXECUTION_MODE
            or acceptance.get("executor_identity") != FIXTURE_EXECUTOR_ID
        ):
            raise BridgeError(f"prior fixture call {call_dir.name} acceptance custody drifted")
        opened = {
            name: _open_fixture_ref(
                session_dir, acceptance.get(name), f"fixture acceptance {name}"
            )
            for name in (
                "receipt", "stdout", "stderr", "candidate_before", "candidate_after", "report"
            )
        }
        if opened["candidate_before"][0] == opened["candidate_after"][0]:
            raise BridgeError("fixture acceptance before/after snapshots alias one artifact")
        if opened["candidate_before"][0].read_bytes() != opened["candidate_after"][0].read_bytes():
            raise BridgeError("fixture acceptance candidate changed during execution")
        receipt = _read_object(opened["receipt"][0], "fixture acceptance receipt")
        if receipt.get("receipt_sha256") != acceptance.get("receipt_sha256"):
            raise BridgeError("fixture acceptance receipt identity drifted")
        if opened["report"][0].read_bytes() != receipt.get("report", "").encode("utf-8"):
            raise BridgeError("fixture acceptance raw report drifted")


def _dispatch(
    composition: PilotComposition,
    state: dict[str, Any],
    stage_spec: Stage,
    call_id: str,
    prompt_raw: bytes,
    fixture_script_sha256: str,
) -> dict[str, Any]:
    attempt = 1 + sum(call["stage"] == state["next_stage"] for call in state["calls"])
    template = composition.templates[stage_spec.prompt_template]
    return {
        "schema": DISPATCH_SCHEMA,
        "execution_mode": EXECUTION_MODE,
        "executor_identity": FIXTURE_EXECUTOR_ID,
        "fixture_script_sha256": fixture_script_sha256,
        "call_id": call_id,
        "task_id": state["task_id"],
        "arm": state["arm"],
        "stage": state["next_stage"],
        "attempt": attempt,
        "backend": stage_spec.backend,
        "prompt_template": {"name": template.name, "sha256": template.sha256},
        "prompt_sha256": _sha(prompt_raw),
        "base_commit": state["base_commit"],
        "task_sha256": _sha(state["task"].encode("utf-8")),
        "files": state["files"],
        "acceptance_sha256": _sha(state["acceptance_command"].encode("utf-8")),
        "composition_manifest_sha256": composition.sha256,
    }


def _call_receipt(
    composition: PilotComposition,
    state: dict[str, Any],
    stage_spec: Stage,
    dispatch: dict[str, Any],
    dispatch_sha: str,
    ledger_call: dict[str, Any],
    provider_output: dict[str, Any],
    candidate_patch: bytes,
) -> dict[str, Any]:
    stage = state["next_stage"]
    outcome = provider_output["outcome"]
    prior = _last_candidate(state)
    if outcome in {"question", "error"} and candidate_patch != prior:
        raise BridgeError("a question/error provider call cannot alter the sealed candidate")
    if stage == "driver_plan" and candidate_patch:
        raise BridgeError("driver planning cannot modify the candidate worktree")
    if outcome == "question" and state["arm"] != "arm_c":
        raise BridgeError("only Arm C may emit a provider question")
    if outcome == "completed" and stage != "driver_plan":
        text = candidate_patch.decode("utf-8")
        if not text:
            raise BridgeError("completed candidate call produced no full-index patch")
        kind = "candidate_patch"
    else:
        text = provider_output["text"]
        kind = "plan" if stage == "driver_plan" and outcome == "completed" else (
            "question" if outcome == "question" else "error"
        )
    session_id = None
    if isinstance(ledger_call.get("extra"), dict):
        session_id = ledger_call["extra"].get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise BridgeError("provider ledger call has no fresh session identity")
    return {
        "schema": CALL_SCHEMA,
        "call_id": dispatch["call_id"],
        "task_id": state["task_id"],
        "arm": state["arm"],
        "stage": stage,
        "attempt": dispatch["attempt"],
        "backend": stage_spec.backend,
        "prompt_template": dispatch["prompt_template"],
        "prompt_sha256": dispatch["prompt_sha256"],
        "dispatch_receipt_sha256": dispatch_sha,
        "session_id": session_id,
        "outcome": outcome,
        "output": {"kind": kind, "text": text, "sha256": _sha(text.encode("utf-8"))},
        "ledger_call": ledger_call,
    }


def _acceptance(
    composition: PilotComposition,
    state: dict[str, Any],
    worktree: Path,
    call_dir: Path,
    candidate_patch: bytes,
) -> dict[str, Any]:
    before_files = _changed_files(worktree)
    (call_dir / "candidate.before.patch").write_bytes(candidate_patch)
    (call_dir / "candidate.before.files.json").write_bytes(canonical_json(before_files))
    env = dict(os.environ)
    env.update({"PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    process = subprocess.run(
        state["acceptance_command"], cwd=worktree, shell=True,
        capture_output=True, env=env,
    )
    stdout = process.stdout or b""
    stderr = process.stderr or b""
    (call_dir / "acceptance.stdout").write_bytes(stdout)
    (call_dir / "acceptance.stderr").write_bytes(stderr)
    after_patch = _patch(worktree)
    after_files = _changed_files(worktree)
    (call_dir / "candidate.after.patch").write_bytes(after_patch)
    (call_dir / "candidate.after.files.json").write_bytes(canonical_json(after_files))
    if after_patch != candidate_patch or after_files != before_files:
        raise BridgeError("acceptance command mutated the candidate; no receipt minted")
    tree = _tree(worktree)
    report = canonical_json({
        "exit_code": process.returncode,
        "stderr": stderr[:MAX_ACCEPTANCE_OUTPUT_BYTES].decode("utf-8", errors="replace"),
        "stderr_bytes": len(stderr),
        "stderr_sha256": _sha(stderr),
        "stderr_truncated": len(stderr) > MAX_ACCEPTANCE_OUTPUT_BYTES,
        "stdout": stdout[:MAX_ACCEPTANCE_OUTPUT_BYTES].decode("utf-8", errors="replace"),
        "stdout_bytes": len(stdout),
        "stdout_sha256": _sha(stdout),
        "stdout_truncated": len(stdout) > MAX_ACCEPTANCE_OUTPUT_BYTES,
    }).decode("utf-8").rstrip("\n")
    (call_dir / "acceptance-report.txt").write_bytes(report.encode("utf-8"))
    receipt = {
        "schema": ACCEPTANCE_SCHEMA,
        "receipt_sha256": "",
        "task_id": state["task_id"],
        "arm": state["arm"],
        "attempt": len(state["acceptance_attempts"]) + 1,
        "causal_call_id": state["calls"][-1]["call_id"],
        "base_commit": state["base_commit"],
        "command": state["acceptance_command"],
        "command_sha256": _sha(state["acceptance_command"].encode("utf-8")),
        "candidate_patch_sha256": _sha(candidate_patch),
        "candidate_tree_sha256": tree,
        "exit_code": process.returncode,
        "passed": process.returncode == 0,
        "report": report,
        "report_sha256": _sha(report.encode("utf-8")),
        "stdout_sha256": _sha(stdout),
        "stderr_sha256": _sha(stderr),
        "tool_versions": composition.acceptance_tool_versions,
        "recorded_at": _now(),
    }
    receipt["receipt_sha256"] = acceptance_receipt_hash(receipt)
    return receipt


def _simulate_fixture_result(
    *,
    response: dict[str, Any],
    composition: PilotComposition,
    state: dict[str, Any],
    stage_spec: Stage,
    dispatch: dict[str, Any],
    dispatch_raw: bytes,
    packet: Path,
    call_dir: Path,
    result_path: Path,
) -> None:
    """Interpret validated data only; never read or execute manifest adapter argv."""
    if response["fault"] == "before_result":
        raise BridgeError("fixture simulator stopped before producing a provider result")
    for raw, content in response["changes"].items():
        pure = PurePosixPath(raw.replace("\\", "/"))
        target = packet / Path(*pure.parts)
        if not _inside(target.resolve(), packet):
            raise BridgeError(f"fixture simulator change escaped packet: {raw!r}")
        if content is None:
            if target.exists():
                if not target.is_file() or target.is_symlink():
                    raise BridgeError(f"fixture simulator cannot delete non-file path: {raw!r}")
                target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="")
    backend = composition.backends[stage_spec.backend]
    outcome = response["outcome"]
    ledger_outcome = "error" if outcome == "error" else "partial" if outcome == "question" else "pass"
    ledger_call = {
        "ts": "2026-01-01T00:00:00Z",
        "account": backend.account,
        "model": backend.model_id,
        "tier": backend.tier,
        "task_id": state["task_id"],
        "phase": state["arm"],
        "outcome": ledger_outcome,
        "effort": backend.effort,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": 0.0,
        "latency_ms": 0.0,
        "trial": dispatch["attempt"],
        "note": f"{backend.cost_basis} data-only fixture simulator",
        "extra": {
            "backend_manifest_sha256": composition.sha256,
            "backend_surface": backend.surface,
            "cost_basis": backend.cost_basis,
            "dispatch_receipt_sha256": _sha(dispatch_raw),
            "prompt_template_sha256": dispatch["prompt_template"]["sha256"],
            "runtime_model_id": backend.model_id,
            "session_id": response["session_id"],
            "telemetry_complete": True,
            "tool_versions": composition.tool_versions,
        },
    }
    pilot_output = {"outcome": outcome, "text": response["text"]}
    raw_path = call_dir / "provider.raw.json"
    raw_path.write_bytes(canonical_json({"pilot_output": pilot_output}))
    result = {
        "schema": BACKEND_SCHEMA,
        "calls": [ledger_call],
        "pilot_output": pilot_output,
        "artifacts": [{
            "name": "provider_raw",
            "path": raw_path.name,
            "sha256": sha256_file(raw_path),
        }],
    }
    result_path.write_bytes(canonical_json(result))
    (call_dir / "adapter.stdout").write_bytes(b"")
    (call_dir / "adapter.stderr").write_bytes(b"")


def _call_once(
    composition: PilotComposition,
    state: dict[str, Any],
    repo: Path,
    session_dir: Path,
    scopes: list[tuple[str, bool]],
    bridge_id: str,
    worktree: Path,
    registry_git: Path,
    fixture_script: list[dict[str, Any]],
    fixture_script_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    ordinal = len(state["calls"]) + 1
    stage_spec = _stage(composition, state)
    if ordinal > len(fixture_script):
        raise BridgeError("fixture_script has no response for the next provider call")
    response = fixture_script[ordinal - 1]
    call_id = f"{_safe_id(state['task_id'])}-{state['arm']}-{ordinal:02d}-{state['state_sha256']}"
    call_dir = session_dir / "calls" / f"{ordinal:02d}-{state['next_stage']}"
    _verify_fixture_evidence(session_dir)
    if call_dir.exists():
        raise BridgeError("call evidence directory already exists; refusing overwrite")
    call_dir.mkdir(parents=True)
    packet = Path(tempfile.mkdtemp(prefix="tier-pilot-packet-", dir=_packet_temp_root()))
    prompt_path = call_dir / "prompt.txt"
    dispatch_path = call_dir / "dispatch.json"
    result_path = call_dir / "provider-result.json"
    call_path = call_dir / "call.json"
    acceptance_path = call_dir / "acceptance.json"
    custody_path = call_dir / "custody.json"
    journal_path = call_dir / "journal.jsonl"
    registered = False
    next_state: dict[str, Any] | None = None
    accepted_state: dict[str, Any] | None = None
    acceptance_receipt: dict[str, Any] | None = None
    error: Exception | None = None
    try:
        if not worktree.is_dir():
            raise BridgeError("isolated arm worktree is missing")
        if _patch(worktree) != _last_candidate(state):
            raise BridgeError("isolated arm worktree diverged from the sealed candidate lineage")
        _refuse_ignored_scope(worktree, scopes)
        packet.rmdir()
        baseline = _prepare_packet(worktree, packet, scopes)
        prompt_raw = render_next_prompt(composition, state)
        prompt_path.write_bytes(prompt_raw)
        dispatch = _dispatch(
            composition, state, stage_spec, call_id, prompt_raw,
            fixture_script_sha256,
        )
        dispatch_raw = canonical_json(dispatch)
        dispatch_path.write_bytes(dispatch_raw)
        _append_journal(journal_path, "PREPARED", call_id)
        _append_journal(journal_path, "DISPATCH_STARTED", call_id)
        _simulate_fixture_result(
            response=response, composition=composition, state=state,
            stage_spec=stage_spec, dispatch=dispatch, dispatch_raw=dispatch_raw,
            packet=packet, call_dir=call_dir, result_path=result_path,
        )
        if not result_path.is_file():
            raise BridgeError("fixture simulator produced no provider result")
        if prompt_path.read_bytes() != prompt_raw or dispatch_path.read_bytes() != dispatch_raw:
            raise BridgeError("provider adapter modified immutable prompt/dispatch bytes")
        ledger_call, provider_output = _provider_result(result_path, call_dir)
        provider_value = _read_object(result_path, "provider result")
        extra = ledger_call.get("extra")
        session_id = extra.get("session_id") if isinstance(extra, dict) else None
        if not isinstance(session_id, str) or not session_id:
            raise BridgeError("parsed provider result has no session identity to burn")
        _register_session(
            registry_git,
            session_id=session_id, run_id=bridge_id,
            task_id=state["task_id"], arm=state["arm"],
            dispatch_hash=_sha(dispatch_raw),
        )
        registered = True
        _, packet_violations = _sync_packet(packet, worktree, scopes, baseline)
        _refuse_ignored_scope(worktree, scopes)
        changed = _changed_files(worktree)
        violations = sorted(set(packet_violations + [
            path for path in changed if not _in_scope(path, scopes)
        ]))
        if violations:
            raise BridgeError(f"provider changed paths outside the frozen scope: {violations}")
        candidate_patch = _patch(worktree)
        call_receipt = _call_receipt(
            composition, state, stage_spec, dispatch, _sha(dispatch_raw),
            ledger_call, provider_output, candidate_patch,
        )
        call_path.write_bytes(canonical_json(call_receipt))
        next_state = record_pilot_call(composition, state, call_receipt)
        if next_state["next_stage"] == "acceptance":
            acceptance_receipt = _acceptance(
                composition, next_state, worktree, call_dir, candidate_patch
            )
            acceptance_path.write_bytes(canonical_json(acceptance_receipt))
            accepted_state = record_acceptance(composition, next_state, acceptance_receipt)
        provider_descriptor = {
            "schema": PROVIDER_EVIDENCE_SCHEMA,
            "execution_mode": EXECUTION_MODE,
            "executor_identity": FIXTURE_EXECUTOR_ID,
            "call_id": call_id,
            "dispatch_receipt_sha256": call_receipt["dispatch_receipt_sha256"],
            "provider_result": _artifact_ref(session_dir, result_path),
            "raw_artifacts": [
                {
                    "name": item["name"],
                    **_artifact_ref(session_dir, call_dir / item["path"]),
                }
                for item in provider_value["artifacts"]
            ],
        }
        (call_dir / "provider-evidence.json").write_bytes(canonical_json(provider_descriptor))
        if acceptance_receipt is not None:
            acceptance_descriptor = {
                "schema": ACCEPTANCE_EVIDENCE_SCHEMA,
                "execution_mode": EXECUTION_MODE,
                "executor_identity": FIXTURE_EXECUTOR_ID,
                "receipt_sha256": acceptance_receipt["receipt_sha256"],
                "receipt": _artifact_ref(session_dir, acceptance_path),
                "stdout": _artifact_ref(session_dir, call_dir / "acceptance.stdout"),
                "stderr": _artifact_ref(session_dir, call_dir / "acceptance.stderr"),
                "candidate_before": _artifact_ref(session_dir, call_dir / "candidate.before.patch"),
                "candidate_after": _artifact_ref(session_dir, call_dir / "candidate.after.patch"),
                "report": _artifact_ref(session_dir, call_dir / "acceptance-report.txt"),
            }
            (call_dir / "acceptance-evidence.json").write_bytes(
                canonical_json(acceptance_descriptor)
            )
        _append_journal(journal_path, "EVIDENCE_SEALED", call_id)
    except (
        BridgeError, CompositionError, ManifestError, RunError, OSError,
        ValueError, subprocess.SubprocessError,
    ) as exc:
        error = exc
    finally:
        try:
            shutil.rmtree(packet)
        except OSError as exc:
            error = error or BridgeError(f"failed to remove provider packet: {exc}")
        packet_removed = not packet.exists()
        custody = {
            "schema": "tier-bench/tier-pilot-call-custody@1",
            "call_id": call_id,
            "session_registered": registered,
            "packet_removed": packet_removed,
            "arm_worktree_preserved": worktree.is_dir(),
            "completed_at": _now(),
            "error": str(error) if error else None,
        }
        custody_path.write_bytes(canonical_json(custody))
        if not packet_removed or not worktree.is_dir():
            error = error or BridgeError("provider packet cleanup or arm lineage preservation failed")
    if error is not None:
        raise BridgeError(str(error)) from error
    assert next_state is not None
    state_path = session_dir / "state.jsonl"
    next_state = _append_state(state_path, composition, next_state)
    if accepted_state is not None:
        accepted_state = _append_state(state_path, composition, accepted_state)
        return accepted_state, acceptance_receipt
    return next_state, None


def _receipt(
    session_dir: Path, composition: PilotComposition, state: dict[str, Any],
    *, worktree_removed: bool, fixture_script_sha256: str,
) -> dict[str, Any]:
    _verify_fixture_evidence(session_dir)
    calls: list[dict[str, Any]] = []
    provider_receipts: list[dict[str, str]] = []
    acceptance_receipts: list[dict[str, str]] = []
    calls_dir = session_dir / "calls"
    if calls_dir.is_dir():
        for call_dir in sorted(path for path in calls_dir.iterdir() if path.is_dir()):
            artifacts = {}
            for path in sorted(item for item in call_dir.iterdir() if item.is_file()):
                artifacts[path.name] = {"path": path.name, "sha256": sha256_file(path)}
            calls.append({"directory": call_dir.name, "artifacts": artifacts})
            if (call_dir / "provider-evidence.json").is_file():
                provider_receipts.append(
                    _artifact_ref(session_dir, call_dir / "provider-evidence.json")
                )
            if (call_dir / "acceptance-evidence.json").is_file():
                acceptance_receipts.append(
                    _artifact_ref(session_dir, call_dir / "acceptance-evidence.json")
                )
    state_path = session_dir / "state.jsonl"
    value = {
        "schema": RECEIPT_SCHEMA,
        "execution_mode": EXECUTION_MODE,
        "executor_identity": FIXTURE_EXECUTOR_ID,
        "fixture_script_sha256": fixture_script_sha256,
        "task_id": state["task_id"],
        "arm": state["arm"],
        "base_commit": state["base_commit"],
        "composition_manifest_sha256": composition.sha256,
        "status": state["status"],
        "next_stage": state["next_stage"],
        "state_sequence": state["state_sequence"],
        "state_sha256": state["state_sha256"],
        "state_log": {"path": "state.jsonl", "sha256": sha256_file(state_path)},
        "calls": calls,
        "provider_receipts": provider_receipts,
        "acceptance_receipts": acceptance_receipts,
        "active_question_id": state["active_question_id"],
        "arm_worktree_removed": worktree_removed,
        "scientific_verdict_minted": False,
        "equivalence_claim_permitted": False,
        "noninferiority_claim_permitted": False,
    }
    (session_dir / "bridge-receipt.json").write_bytes(canonical_json(value))
    return value


def _drive(
    composition: PilotComposition,
    state: dict[str, Any],
    repo: Path,
    session_dir: Path,
    scopes: list[tuple[str, bool]],
    bridge_id: str,
    worktree: Path,
    registry_git: Path,
    fixture_script: list[dict[str, Any]],
    fixture_script_sha256: str,
) -> dict[str, Any]:
    lock = session_dir / "arm.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise BridgeError("arm bridge is locked or has ambiguous interrupted work") from exc
    os.close(descriptor)
    try:
        while state["status"] == "ACTIVE":
            state, _ = _call_once(
                composition, state, repo, session_dir, scopes, bridge_id,
                worktree, registry_git, fixture_script, fixture_script_sha256,
            )
        removed = False
        if state["status"] in {"COMPLETE", "FAILED"}:
            _verify_fixture_evidence(session_dir)
            process = _git(repo, "worktree", "remove", "--force", str(worktree), check=False)
            removed = process.returncode == 0 and not worktree.exists()
            if not removed:
                raise BridgeError("terminal arm could not remove its isolated worktree")
        return _receipt(
            session_dir, composition, state,
            worktree_removed=removed,
            fixture_script_sha256=fixture_script_sha256,
        )
    finally:
        lock.unlink(missing_ok=True)


def start_pilot_arm(**_: Any) -> dict[str, Any]:
    raise BridgeError(
        "pilot bridge production dispatch is activation-blocked: no ratified adapter "
        "identity/activation schema is merged; use fixture-only tests, not a live backend"
    )


def start_fixture_pilot_arm(
    *,
    repo: Path,
    evidence_repo: Path,
    composition_manifest: Path,
    task_id: str,
    task_tier: str,
    arm: str,
    task: str,
    files: list[str],
    acceptance_command: str,
    base_commit: str,
    output_dir: Path,
    fixture_script: list[dict[str, Any]],
) -> dict[str, Any]:
    fixture_script, fixture_script_sha256 = _fixture_script(fixture_script)
    repo = _repo_root(repo)
    evidence_repo = _repo_root(evidence_repo)
    target_git = _git_common_dir(repo)
    registry_git = _git_common_dir(evidence_repo)
    if evidence_repo == repo or target_git == registry_git:
        raise BridgeError("control/evidence repository must be separate from the target")
    if subprocess.run(
        ["git", "cat-file", "-e", f"{base_commit}^{{commit}}"], cwd=repo,
        capture_output=True,
    ).returncode:
        raise BridgeError("base_commit is not available in the target repository")
    composition_manifest = composition_manifest.resolve()
    if not _inside(composition_manifest, evidence_repo):
        raise BridgeError("composition manifest must live in the separate evidence repository")
    composition = load_pilot_composition(composition_manifest)
    scopes = _normalize_scope(repo, files)
    normalized_files = [path + ("/" if is_dir else "") for path, is_dir in scopes]
    bridge_id = f"{_safe_id(task_id)}-{arm}-{uuid.uuid4().hex[:12]}"
    session_dir = output_dir.resolve()
    if _inside(session_dir, repo):
        raise BridgeError("pilot evidence directory cannot modify the operator checkout")
    if not _inside(session_dir, evidence_repo):
        raise BridgeError("pilot evidence directory must live in the separate evidence repository")
    if _inside(session_dir, registry_git):
        raise BridgeError("pilot evidence directory cannot live under the evidence Git directory")
    if session_dir.exists() and any(session_dir.iterdir()):
        raise BridgeError("pilot evidence directory is not empty")
    session_dir.mkdir(parents=True, exist_ok=True)
    worktree = target_git / "tier-pilot-worktrees" / bridge_id
    _git(repo, "worktree", "add", "--detach", str(worktree), base_commit)
    state = new_pilot_arm_state(
        composition, task_id=task_id, task_tier=task_tier, arm=arm,
        task=task, files=normalized_files, acceptance_command=acceptance_command,
        base_commit=base_commit,
    )
    state_path = session_dir / "state.jsonl"
    state = _append_state(state_path, composition, state)
    session = {
        "schema": SESSION_SCHEMA,
        "bridge_id": bridge_id,
        "repo": str(repo),
        "evidence_repo": str(evidence_repo),
        "arm_worktree": str(worktree),
        "composition_manifest": str(composition_manifest),
        "composition_manifest_sha256": composition.sha256,
        "fixture_script_sha256": fixture_script_sha256,
        "task_id": task_id,
        "arm": arm,
        "base_commit": base_commit,
        "files": normalized_files,
        "created_at": _now(),
    }
    (session_dir / "bridge-session.json").write_bytes(canonical_json(session))
    return _drive(
        composition, state, repo, session_dir, scopes, bridge_id,
        worktree, registry_git, fixture_script, fixture_script_sha256,
    )


def _load_session(session_dir: Path) -> tuple[
    dict[str, Any], PilotComposition, Path, Path, list[tuple[str, bool]], dict[str, Any]
]:
    session_dir = session_dir.resolve()
    session = _read_object(session_dir / "bridge-session.json", "bridge session")
    required = {
        "schema", "bridge_id", "repo", "evidence_repo", "arm_worktree", "composition_manifest",
        "composition_manifest_sha256", "task_id", "arm", "base_commit", "files",
        "fixture_script_sha256", "created_at",
    }
    if set(session) != required or session.get("schema") != SESSION_SCHEMA:
        raise BridgeError("bridge session fields/schema are invalid")
    repo = _repo_root(Path(session["repo"]))
    evidence_repo = _repo_root(Path(session["evidence_repo"]))
    if (
        repo == evidence_repo
        or _git_common_dir(repo) == _git_common_dir(evidence_repo)
        or not _inside(session_dir, evidence_repo)
    ):
        raise BridgeError("bridge session lost separate control/evidence custody")
    composition_path = Path(session["composition_manifest"]).resolve()
    if not _inside(composition_path, evidence_repo):
        raise BridgeError("composition manifest escaped the separate evidence repository")
    composition = load_pilot_composition(composition_path)
    if composition.sha256 != session["composition_manifest_sha256"]:
        raise BridgeError("composition manifest drifted after bridge start")
    scopes = _normalize_scope(repo, session["files"])
    state = read_state(composition, session_dir / "state.jsonl")
    for key in ("task_id", "arm", "base_commit", "files"):
        if state[key] != session[key]:
            raise BridgeError(f"bridge session {key} contradicts the sealed state")
    worktree = Path(session["arm_worktree"]).resolve()
    expected_worktree = (
        _git_common_dir(repo) / "tier-pilot-worktrees" / session["bridge_id"]
    ).resolve()
    if worktree != expected_worktree:
        raise BridgeError("arm worktree path contradicts the bridge-owned lineage")
    if state["status"] == "WAITING_OPERATOR":
        if not worktree.is_dir() or _patch(worktree) != _last_candidate(state):
            raise BridgeError("paused arm worktree does not match its sealed candidate lineage")
    return session, composition, repo, evidence_repo, scopes, state


def answer_and_resume_fixture_pilot_arm(
    session_dir: Path,
    *,
    question_id: str,
    answer: str,
    intervention_id: str,
) -> dict[str, Any]:
    raise BridgeError(
        "fixture Arm-C resume is activation-blocked: freehand answers and intervention "
        "identifiers cannot authorize dispatch; a canonical globally closed clarification "
        "interval is not implemented"
    )


def decline_pilot_arm(
    session_dir: Path,
    *,
    question_id: str,
    reason: str,
    intervention_id: str,
) -> dict[str, Any]:
    raise BridgeError(
        "fixture Arm-C decline is activation-blocked until canonical global intervention "
        "closure and locked evidence replay are implemented"
    )
