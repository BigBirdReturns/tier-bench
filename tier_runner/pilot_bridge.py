from __future__ import annotations

from dataclasses import dataclass
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
from .events import InterventionError, validate_events
from .manifest import ManifestError, sha256_file
from .pilot import PilotError, validate_plan
from .pilot_activation import (
    EXECUTOR_IDENTITY,
    ActivationError,
    PilotActivation,
    load_official_activation,
)
from .pilot_adapter import PilotAdapterError, run_activated_adapter
from .pilot_composition import (
    ACCEPTANCE_SCHEMA,
    CALL_SCHEMA,
    CompositionError,
    acceptance_receipt_hash,
    answer_operator_question,
    canonical_json,
    decline_operator_question,
    new_pilot_arm_state,
    read_state,
    record_acceptance,
    record_pilot_call,
    render_next_prompt,
    write_state,
)
from .pilot_manifest import PilotComposition, Stage, load_pilot_composition


SESSION_SCHEMA = "tier-bench/tier-pilot-bridge-session@1"
RECEIPT_SCHEMA = "tier-bench/tier-pilot-fixture-bridge-receipt@2"
DISPATCH_SCHEMA = "tier-bench/tier-pilot-fixture-dispatch-receipt@1"
PROVIDER_EVIDENCE_SCHEMA = "tier-bench/tier-pilot-fixture-provider-evidence@1"
ACCEPTANCE_EVIDENCE_SCHEMA = "tier-bench/tier-pilot-fixture-acceptance-evidence@1"
EXECUTION_MODE = "fixture"
FIXTURE_EXECUTOR_ID = "tier-bench/in-process-data-fixture@1"
PRODUCTION_SESSION_SCHEMA = "tier-bench/tier-pilot-production-bridge-session@1"
PRODUCTION_RECEIPT_SCHEMA = "tier-bench/tier-pilot-production-bridge-receipt@2"
PRODUCTION_DISPATCH_SCHEMA = "tier-bench/tier-pilot-dispatch-receipt@1"
PRODUCTION_PROVIDER_EVIDENCE_SCHEMA = (
    "tier-bench/tier-pilot-production-provider-evidence@1"
)
PRODUCTION_ACCEPTANCE_EVIDENCE_SCHEMA = (
    "tier-bench/tier-pilot-production-acceptance-evidence@1"
)
QUESTION_ENVELOPE_SCHEMA = "tier-bench/tier-pilot-operator-question@1"
QUESTION_CATEGORIES = {"interpretation", "policy", "authorization"}
MAX_QUESTION_BYTES = 512
MAX_ACCEPTANCE_OUTPUT_BYTES = 8192
FIXTURE_RESPONSE_FIELDS = {"outcome", "text", "session_id", "changes", "fault"}
PROVIDER_OUTPUT_FIELDS = {"outcome", "text"}
PROVIDER_RESULT_FIELDS = {"schema", "calls", "pilot_output", "artifacts"}
RECOVERY_SCHEMA = "tier-bench/tier-pilot-recovery-event@1"
RECOVERY_ACTIONS = {
    "STALE_LOCK_CLEARED",
    "PRE_DISPATCH_ARCHIVED",
    "SEALED_STATE_REPLAYED",
    "QUESTION_RECEIPT_RECOVERED",
    "AMBIGUOUS_DISPATCH_FAIL_STOPPED",
}
RECOVERY_FIELDS = {
    "schema", "sequence", "action", "call_directory", "evidence_sha256",
    "previous_event_sha256", "recorded_at", "event_sha256",
}
DRIVE_LOCK_SCHEMA = "tier-bench/tier-pilot-drive-lock@1"
ABORT_SCHEMA = "tier-bench/tier-pilot-bridge-abort@1"
ABORT_FIELDS = {
    "schema", "reason", "call_directory", "evidence_sha256",
    "incoming_state_sha256", "redispatch_permitted", "arm_worktree_removed",
    "recorded_at",
}


class BridgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class _Execution:
    mode: str
    activation: PilotActivation | None
    fixture_script: list[dict[str, Any]] | None
    fixture_script_sha256: str | None

    @property
    def production(self) -> bool:
        return self.mode == "production"


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


def _write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def _directory_sha256(path: Path) -> str:
    items = sorted(path.rglob("*"))
    if any(item.is_symlink() for item in items):
        raise BridgeError("recovery evidence cannot contain symbolic links")
    rows = [
        {"path": item.relative_to(path).as_posix(), "sha256": sha256_file(item)}
        for item in items if item.is_file()
    ]
    return _sha(canonical_json(rows))


def _read_recovery_log(session_dir: Path) -> list[dict[str, Any]]:
    path = session_dir / "recovery.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for sequence, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BridgeError(f"recovery row {sequence} is invalid JSON") from exc
        if not isinstance(row, dict) or set(row) != RECOVERY_FIELDS:
            raise BridgeError(f"recovery row {sequence} fields are invalid")
        if (
            row.get("schema") != RECOVERY_SCHEMA
            or row.get("sequence") != sequence
            or row.get("action") not in RECOVERY_ACTIONS
            or not isinstance(row.get("call_directory"), str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+", row["call_directory"])
            or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("evidence_sha256", "")))
            or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("event_sha256", "")))
        ):
            raise BridgeError(f"recovery row {sequence} identity is invalid")
        try:
            recorded_at = datetime.fromisoformat(
                str(row.get("recorded_at", "")).replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise BridgeError(f"recovery row {sequence} timestamp is invalid") from exc
        if recorded_at.tzinfo is None:
            raise BridgeError(f"recovery row {sequence} timestamp is invalid")
        previous = rows[-1]["event_sha256"] if rows else None
        if row.get("previous_event_sha256") != previous:
            raise BridgeError(f"recovery row {sequence} chain is invalid")
        claimed = row.get("event_sha256")
        unsigned = dict(row)
        del unsigned["event_sha256"]
        if claimed != _sha(canonical_json(unsigned)):
            raise BridgeError(f"recovery row {sequence} hash is invalid")
        rows.append(row)
    identities = [
        (row["action"], row["call_directory"], row["evidence_sha256"])
        for row in rows
    ]
    if len(identities) != len(set(identities)):
        raise BridgeError("recovery log repeats one write-ahead action")
    single_use = [
        (row["action"], row["call_directory"])
        for row in rows if row["action"] != "STALE_LOCK_CLEARED"
    ]
    if len(single_use) != len(set(single_use)):
        raise BridgeError("recovery log forks one single-use action")
    return rows


def _ensure_recovery_event(
    session_dir: Path, action: str, call_directory: str, evidence_sha256: str
) -> dict[str, Any]:
    if (
        action not in RECOVERY_ACTIONS
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", call_directory)
        or not re.fullmatch(r"[0-9a-f]{64}", evidence_sha256)
    ):
        raise BridgeError("recovery event inputs are invalid")
    rows = _read_recovery_log(session_dir)
    existing = [
        row for row in rows
        if row["action"] == action
        and row["call_directory"] == call_directory
        and row["evidence_sha256"] == evidence_sha256
    ]
    if existing:
        if len(existing) != 1:
            raise BridgeError("recovery event contradicts its write-ahead evidence")
        return existing[0]
    conflicts = [
        row for row in rows
        if row["action"] == action and row["call_directory"] == call_directory
    ]
    if conflicts and action != "STALE_LOCK_CLEARED":
        raise BridgeError("recovery event contradicts its write-ahead evidence")
    row = {
        "schema": RECOVERY_SCHEMA,
        "sequence": len(rows),
        "action": action,
        "call_directory": call_directory,
        "evidence_sha256": evidence_sha256,
        "previous_event_sha256": rows[-1]["event_sha256"] if rows else None,
        "recorded_at": _now(),
    }
    row["event_sha256"] = _sha(canonical_json(row))
    with (session_dir / "recovery.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json(row).decode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    _read_recovery_log(session_dir)
    return row


def _question_receipt_path(session_dir: Path, index: int, question_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", question_id):
        raise BridgeError("question receipt has an unsafe question ID")
    return session_dir / "question-receipts" / f"{index:02d}-{question_id}.json"


def _seal_question_receipts(
    session_dir: Path,
    state: dict[str, Any],
    *,
    recover_missing: bool,
    record_recovery: bool = True,
) -> list[Path]:
    expected: list[Path] = []
    for index, receipt in enumerate(state["question_receipts"], 1):
        path = _question_receipt_path(session_dir, index, receipt["question_id"])
        raw = canonical_json(receipt)
        if not path.exists():
            if not recover_missing:
                raise BridgeError("state question receipt is missing its durable artifact")
            if record_recovery:
                _ensure_recovery_event(
                    session_dir, "QUESTION_RECEIPT_RECOVERED", path.name, _sha(raw)
                )
            _write_new(path, raw)
        elif path.read_bytes() != raw:
            raise BridgeError("durable question receipt contradicts replayed state")
        expected.append(path)
    directory = session_dir / "question-receipts"
    actual = sorted(path for path in directory.glob("*.json")) if directory.is_dir() else []
    if actual != expected:
        raise BridgeError("question receipt artifacts are incomplete, duplicated, or extra")
    return expected


def _closed_intervention(
    intervention_log: Path,
    state: dict[str, Any],
    *,
    question_id: str,
) -> tuple[str, str]:
    if (
        state.get("arm") != "arm_c"
        or state.get("status") != "WAITING_OPERATOR"
        or question_id != state.get("active_question_id")
    ):
        raise BridgeError("operator response does not name the active Arm-C question")
    try:
        rows = validate_events(intervention_log.resolve(), require_closed=True)
    except InterventionError as exc:
        raise BridgeError(f"global intervention log is invalid: {exc}") from exc
    pairs: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        pairs.setdefault(row["intervention_id"], []).append(row)
    matches = [
        (intervention_id, pair)
        for intervention_id, pair in pairs.items()
        if len(pair) == 2
        and all(
            row["task_id"] == state["task_id"]
            and row["arm"] == "arm_c"
            and row["category"] == "clarification"
            and row["reference_id"] == question_id
            for row in pair
        )
    ]
    if len(matches) != 1:
        raise BridgeError(
            "operator response requires exactly one globally closed clarification interval"
        )
    intervention_id, pair = matches[0]
    questions = [
        item for item in state["questions"] if item["question_id"] == question_id
    ]
    if len(questions) != 1:
        raise BridgeError("active Arm-C question is not unique in sealed state")
    question = questions[0]
    asked_at = datetime.fromisoformat(question["asked_at"].replace("Z", "+00:00"))
    started_at = datetime.fromisoformat(pair[0]["ts"].replace("Z", "+00:00"))
    stopped_at = datetime.fromisoformat(pair[1]["ts"].replace("Z", "+00:00"))
    if started_at < asked_at or stopped_at < started_at:
        raise BridgeError("clarification interval does not follow the sealed question")
    if stopped_at > datetime.now(timezone.utc):
        raise BridgeError("clarification interval ends in the future")
    return intervention_id, pair[1]["ts"]


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


def _provider_result(
    path: Path, call_dir: Path, *, production: bool = False
) -> tuple[dict[str, Any], dict[str, Any]]:
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
        label = "production" if production else "fixture"
        raise BridgeError(f"{label} provider_raw must be an exact JSON output witness") from exc
    if production:
        encoded = raw.get("result") if isinstance(raw, dict) else None
        if not isinstance(encoded, str):
            raise BridgeError("production provider_raw has no exact result string")
        try:
            opened = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise BridgeError("production provider_raw result is invalid JSON") from exc
        if (
            opened != output
            or encoded != json.dumps(output, sort_keys=True, separators=(",", ":"))
        ):
            raise BridgeError("production provider_raw does not open exact pilot_output bytes")
    elif raw != {"pilot_output": output}:
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


def _verify_production_evidence(
    session_dir: Path, activation: PilotActivation
) -> None:
    evidence_root = activation.repository
    calls_dir = session_dir / "calls"
    if not calls_dir.is_dir():
        return
    for call_dir in sorted(path for path in calls_dir.iterdir() if path.is_dir()):
        dispatch_path = call_dir / "dispatch.json"
        dispatch = _read_object(dispatch_path, "production dispatch")
        call_id = dispatch.get("call_id")
        if dispatch.get("schema") != PRODUCTION_DISPATCH_SCHEMA or not isinstance(
            call_id, str
        ) or not call_id:
            raise BridgeError(f"prior production call {call_dir.name} dispatch drifted")
        journal = _read_journal(call_dir / "journal.jsonl", call_id)
        if [row["event"] for row in journal] != [
            "PREPARED", "DISPATCH_STARTED", "EVIDENCE_SEALED"
        ]:
            raise BridgeError(f"prior production call {call_dir.name} is not durably sealed")
        provider = _read_object(
            call_dir / "provider-evidence.json", "production provider evidence"
        )
        fields = {
            "schema", "executor_identity", "activation_commit", "activation_sha256",
            "call_id", "dispatch_receipt_sha256", "provider_result", "raw_artifacts",
        }
        if (
            set(provider) != fields
            or provider.get("schema") != PRODUCTION_PROVIDER_EVIDENCE_SCHEMA
            or provider.get("executor_identity") != EXECUTOR_IDENTITY
            or provider.get("activation_commit") != activation.commit
            or provider.get("activation_sha256") != activation.sha256
            or provider.get("call_id") != call_id
            or provider.get("dispatch_receipt_sha256") != _sha(dispatch_path.read_bytes())
        ):
            raise BridgeError(f"prior production call {call_dir.name} provider custody drifted")
        result_path, _ = _open_fixture_ref(
            evidence_root, provider.get("provider_result"), "production provider result"
        )
        try:
            _provider_result(result_path, call_dir, production=True)
        except RunError as exc:
            raise BridgeError(f"prior production provider evidence is invalid: {exc}") from exc
        result = _read_object(result_path, "production provider result")
        expected_raw = [
            (item["name"], (call_dir / item["path"]).resolve(), item["sha256"])
            for item in result["artifacts"]
        ]
        raws = provider.get("raw_artifacts")
        if not isinstance(raws, list):
            raise BridgeError("production raw_artifacts must be an array")
        opened_raw: list[tuple[str, Path, str]] = []
        for index, raw in enumerate(raws):
            if not isinstance(raw, dict) or set(raw) != {"name", "path", "sha256"}:
                raise BridgeError(f"production raw artifact {index} fields are invalid")
            opened, digest = _open_fixture_ref(
                evidence_root, {"path": raw["path"], "sha256": raw["sha256"]},
                f"production raw artifact {index}",
            )
            opened_raw.append((raw["name"], opened, digest))
        if opened_raw != expected_raw:
            raise BridgeError("production raw artifact custody is not an exact ordered match")

        acceptance_path = call_dir / "acceptance-evidence.json"
        if not acceptance_path.exists():
            continue
        acceptance = _read_object(acceptance_path, "production acceptance evidence")
        acceptance_fields = {
            "schema", "executor_identity", "activation_commit", "activation_sha256",
            "receipt_sha256", "receipt", "stdout", "stderr", "candidate_before",
            "candidate_after", "report",
        }
        if (
            set(acceptance) != acceptance_fields
            or acceptance.get("schema") != PRODUCTION_ACCEPTANCE_EVIDENCE_SCHEMA
            or acceptance.get("executor_identity") != EXECUTOR_IDENTITY
            or acceptance.get("activation_commit") != activation.commit
            or acceptance.get("activation_sha256") != activation.sha256
        ):
            raise BridgeError(f"prior production call {call_dir.name} acceptance custody drifted")
        opened = {
            name: _open_fixture_ref(
                evidence_root, acceptance.get(name), f"production acceptance {name}"
            )
            for name in (
                "receipt", "stdout", "stderr", "candidate_before", "candidate_after",
                "report",
            )
        }
        if opened["candidate_before"][0] == opened["candidate_after"][0]:
            raise BridgeError("production acceptance before/after snapshots alias one artifact")
        if opened["candidate_before"][0].read_bytes() != opened["candidate_after"][0].read_bytes():
            raise BridgeError("production acceptance candidate changed during execution")
        receipt = _read_object(opened["receipt"][0], "production acceptance receipt")
        if receipt.get("receipt_sha256") != acceptance.get("receipt_sha256"):
            raise BridgeError("production acceptance receipt identity drifted")
        if opened["report"][0].read_bytes() != receipt.get("report", "").encode("utf-8"):
            raise BridgeError("production acceptance raw report drifted")


def _verify_execution_evidence(session_dir: Path, execution: _Execution) -> None:
    if execution.production:
        if execution.activation is None:
            raise BridgeError("production execution has no re-derived activation")
        _verify_production_evidence(session_dir, execution.activation)
    else:
        _verify_fixture_evidence(session_dir)


def _dispatch(
    composition: PilotComposition,
    state: dict[str, Any],
    stage_spec: Stage,
    call_id: str,
    prompt_raw: bytes,
    execution: _Execution,
) -> dict[str, Any]:
    attempt = 1 + sum(call["stage"] == state["next_stage"] for call in state["calls"])
    template = composition.templates[stage_spec.prompt_template]
    value = {
        "schema": PRODUCTION_DISPATCH_SCHEMA if execution.production else DISPATCH_SCHEMA,
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
    if not execution.production:
        value.update({
            "execution_mode": EXECUTION_MODE,
            "executor_identity": FIXTURE_EXECUTOR_ID,
            "fixture_script_sha256": execution.fixture_script_sha256,
        })
    return value


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
    execution: _Execution,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    ordinal = len(state["calls"]) + 1
    stage_spec = _stage(composition, state)
    response: dict[str, Any] | None = None
    if not execution.production:
        if execution.fixture_script is None or ordinal > len(execution.fixture_script):
            raise BridgeError("fixture_script has no response for the next provider call")
        response = execution.fixture_script[ordinal - 1]
    call_id = f"{_safe_id(state['task_id'])}-{state['arm']}-{ordinal:02d}-{state['state_sha256']}"
    call_dir = session_dir / "calls" / f"{ordinal:02d}-{state['next_stage']}"
    _verify_execution_evidence(session_dir, execution)
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
            composition, state, stage_spec, call_id, prompt_raw, execution,
        )
        dispatch_raw = canonical_json(dispatch)
        dispatch_path.write_bytes(dispatch_raw)
        _append_journal(journal_path, "PREPARED", call_id)
        _append_journal(journal_path, "DISPATCH_STARTED", call_id)
        if execution.production:
            if execution.activation is None:
                raise BridgeError("production call has no re-derived activation")
            run_activated_adapter(
                execution.activation,
                backend_name=stage_spec.backend,
                dispatch_path=dispatch_path,
                prompt_path=prompt_path,
                result_path=result_path,
                worktree=packet,
            )
        else:
            assert response is not None
            _simulate_fixture_result(
                response=response, composition=composition, state=state,
                stage_spec=stage_spec, dispatch=dispatch, dispatch_raw=dispatch_raw,
                packet=packet, call_dir=call_dir, result_path=result_path,
            )
        if not result_path.is_file():
            raise BridgeError("fixture simulator produced no provider result")
        if prompt_path.read_bytes() != prompt_raw or dispatch_path.read_bytes() != dispatch_raw:
            raise BridgeError("provider adapter modified immutable prompt/dispatch bytes")
        ledger_call, provider_output = _provider_result(
            result_path, call_dir, production=execution.production
        )
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
            "schema": (
                PRODUCTION_PROVIDER_EVIDENCE_SCHEMA
                if execution.production else PROVIDER_EVIDENCE_SCHEMA
            ),
            "executor_identity": (
                EXECUTOR_IDENTITY if execution.production else FIXTURE_EXECUTOR_ID
            ),
            "call_id": call_id,
            "dispatch_receipt_sha256": call_receipt["dispatch_receipt_sha256"],
            "provider_result": _artifact_ref(
                execution.activation.repository if execution.production else session_dir,
                result_path,
            ),
            "raw_artifacts": [
                {
                    "name": item["name"],
                    **_artifact_ref(
                        execution.activation.repository if execution.production else session_dir,
                        call_dir / item["path"],
                    ),
                }
                for item in provider_value["artifacts"]
            ],
        }
        if execution.production:
            assert execution.activation is not None
            provider_descriptor.update({
                "activation_commit": execution.activation.commit,
                "activation_sha256": execution.activation.sha256,
            })
        else:
            provider_descriptor["execution_mode"] = EXECUTION_MODE
        (call_dir / "provider-evidence.json").write_bytes(canonical_json(provider_descriptor))
        if acceptance_receipt is not None:
            acceptance_descriptor = {
                "schema": (
                    PRODUCTION_ACCEPTANCE_EVIDENCE_SCHEMA
                    if execution.production else ACCEPTANCE_EVIDENCE_SCHEMA
                ),
                "executor_identity": (
                    EXECUTOR_IDENTITY if execution.production else FIXTURE_EXECUTOR_ID
                ),
                "receipt_sha256": acceptance_receipt["receipt_sha256"],
                "receipt": _artifact_ref(
                    execution.activation.repository if execution.production else session_dir,
                    acceptance_path,
                ),
                "stdout": _artifact_ref(
                    execution.activation.repository if execution.production else session_dir,
                    call_dir / "acceptance.stdout",
                ),
                "stderr": _artifact_ref(
                    execution.activation.repository if execution.production else session_dir,
                    call_dir / "acceptance.stderr",
                ),
                "candidate_before": _artifact_ref(
                    execution.activation.repository if execution.production else session_dir,
                    call_dir / "candidate.before.patch",
                ),
                "candidate_after": _artifact_ref(
                    execution.activation.repository if execution.production else session_dir,
                    call_dir / "candidate.after.patch",
                ),
                "report": _artifact_ref(
                    execution.activation.repository if execution.production else session_dir,
                    call_dir / "acceptance-report.txt",
                ),
            }
            if execution.production:
                assert execution.activation is not None
                acceptance_descriptor.update({
                    "activation_commit": execution.activation.commit,
                    "activation_sha256": execution.activation.sha256,
                })
            else:
                acceptance_descriptor["execution_mode"] = EXECUTION_MODE
            (call_dir / "acceptance-evidence.json").write_bytes(
                canonical_json(acceptance_descriptor)
            )
    except (
        ActivationError, BridgeError, CompositionError, ManifestError, PilotAdapterError,
        PilotError, RunError, OSError,
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
    _append_journal(journal_path, "EVIDENCE_SEALED", call_id)
    assert next_state is not None
    state_path = session_dir / "state.jsonl"
    next_state = _append_state(state_path, composition, next_state)
    if accepted_state is not None:
        accepted_state = _append_state(state_path, composition, accepted_state)
        return accepted_state, acceptance_receipt
    return next_state, None


def _receipt(
    session_dir: Path, composition: PilotComposition, state: dict[str, Any],
    *, worktree_removed: bool, execution: _Execution,
) -> dict[str, Any]:
    _verify_execution_evidence(session_dir, execution)
    artifact_root = (
        execution.activation.repository
        if execution.production and execution.activation is not None
        else session_dir
    )
    calls: list[dict[str, Any]] = []
    provider_receipts: list[dict[str, str]] = []
    acceptance_receipts: list[dict[str, str]] = []
    question_receipts = [
        _artifact_ref(artifact_root, path)
        for path in _seal_question_receipts(
            session_dir, state, recover_missing=False
        )
    ]
    recovery_path = session_dir / "recovery.jsonl"
    recovery_log = None
    if recovery_path.is_file():
        _read_recovery_log(session_dir)
        recovery_log = _artifact_ref(artifact_root, recovery_path)
    calls_dir = session_dir / "calls"
    if calls_dir.is_dir():
        for call_dir in sorted(path for path in calls_dir.iterdir() if path.is_dir()):
            artifacts = {}
            for path in sorted(item for item in call_dir.iterdir() if item.is_file()):
                artifacts[path.name] = {"path": path.name, "sha256": sha256_file(path)}
            calls.append({"directory": call_dir.name, "artifacts": artifacts})
            if (call_dir / "provider-evidence.json").is_file():
                provider_receipts.append(
                    _artifact_ref(artifact_root, call_dir / "provider-evidence.json")
                )
            if (call_dir / "acceptance-evidence.json").is_file():
                acceptance_receipts.append(
                    _artifact_ref(artifact_root, call_dir / "acceptance-evidence.json")
                )
    state_path = session_dir / "state.jsonl"
    value = {
        "schema": PRODUCTION_RECEIPT_SCHEMA if execution.production else RECEIPT_SCHEMA,
        "executor_identity": EXECUTOR_IDENTITY if execution.production else FIXTURE_EXECUTOR_ID,
        "task_id": state["task_id"],
        "arm": state["arm"],
        "base_commit": state["base_commit"],
        "composition_manifest_sha256": composition.sha256,
        "status": state["status"],
        "state_sequence": state["state_sequence"],
        "state_sha256": state["state_sha256"],
        "state_log": _artifact_ref(artifact_root, state_path),
        "provider_receipts": provider_receipts,
        "acceptance_receipts": acceptance_receipts,
        "question_receipts": question_receipts,
        "recovery_log": recovery_log,
        "arm_worktree_removed": worktree_removed,
        "scientific_verdict_minted": False,
        "equivalence_claim_permitted": False,
        "noninferiority_claim_permitted": False,
    }
    if execution.production:
        if execution.activation is None:
            raise BridgeError("production receipt has no re-derived activation")
        value.update({
            "activation_commit": execution.activation.commit,
            "activation_sha256": execution.activation.sha256,
        })
    else:
        value.update({
            "execution_mode": EXECUTION_MODE,
            "fixture_script_sha256": execution.fixture_script_sha256,
            "next_stage": state["next_stage"],
            "calls": calls,
            "active_question_id": state["active_question_id"],
        })
    (session_dir / "bridge-receipt.json").write_bytes(canonical_json(value))
    return value


def _acquire_drive_lock(session_dir: Path, bridge_id: str) -> Path:
    lock = session_dir / "arm.lock"
    if (session_dir / "bridge-abort.json").exists():
        raise BridgeError("arm bridge is permanently fail-stopped")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise BridgeError("arm bridge is locked or has ambiguous interrupted work") from exc
    lock_raw = canonical_json({
        "schema": DRIVE_LOCK_SCHEMA,
        "bridge_id": bridge_id,
        "pid": os.getpid(),
        "created_at": _now(),
    })
    try:
        written = 0
        while written < len(lock_raw):
            count = os.write(descriptor, lock_raw[written:])
            if count <= 0:
                raise OSError("drive lock write made no progress")
            written += count
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        lock.unlink(missing_ok=True)
        raise
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
    return lock


def _drive(
    composition: PilotComposition,
    state: dict[str, Any],
    repo: Path,
    session_dir: Path,
    scopes: list[tuple[str, bool]],
    bridge_id: str,
    worktree: Path,
    registry_git: Path,
    execution: _Execution,
    *,
    lock_owned: bool = False,
) -> dict[str, Any]:
    lock = session_dir / "arm.lock" if lock_owned else _acquire_drive_lock(
        session_dir, bridge_id
    )
    if lock_owned:
        value = _read_object(lock, "owned arm drive lock")
        if (
            set(value) != {"schema", "bridge_id", "pid", "created_at"}
            or value.get("schema") != DRIVE_LOCK_SCHEMA
            or value.get("bridge_id") != bridge_id
            or value.get("pid") != os.getpid()
        ):
            raise BridgeError("caller does not own the arm drive lock")
    try:
        while state["status"] == "ACTIVE":
            state, _ = _call_once(
                composition, state, repo, session_dir, scopes, bridge_id,
                worktree, registry_git, execution,
            )
        removed = False
        if state["status"] in {"COMPLETE", "FAILED"}:
            _verify_execution_evidence(session_dir, execution)
            process = _git(repo, "worktree", "remove", "--force", str(worktree), check=False)
            removed = process.returncode == 0 and not worktree.exists()
            if not removed:
                raise BridgeError("terminal arm could not remove its isolated worktree")
        return _receipt(
            session_dir, composition, state,
            worktree_removed=removed, execution=execution,
        )
    finally:
        lock.unlink(missing_ok=True)


def _production_authorities(
    evidence_repo: Path,
    *,
    activation_commit: str,
    activation_path: str,
    plan_path: str,
    authorization_path: str,
) -> tuple[PilotActivation, dict[str, Any], str, str, Path]:
    evidence_repo = _repo_root(evidence_repo)
    evidence_git = _git_common_dir(evidence_repo)

    def committed_blob(path: str, label: str) -> bytes:
        if not isinstance(path, str) or not path:
            raise BridgeError(f"{label} path is not a canonical committed path")
        pure = PurePosixPath(path)
        if (
            path != pure.as_posix()
            or pure.is_absolute()
            or ".." in pure.parts
            or "." in pure.parts
            or pure.parts[0] == ".git"
        ):
            raise BridgeError(f"{label} path is not a canonical committed path")
        process = subprocess.run(
            ["git", "show", f"{activation_commit}:{path}"],
            cwd=evidence_repo,
            capture_output=True,
        )
        if process.returncode:
            raise BridgeError(f"{label} does not exist at the authenticated authority commit")
        return process.stdout

    try:
        activation = load_official_activation(
            evidence_repo, activation_commit, activation_path
        )
        plan_raw = committed_blob(plan_path, "pilot plan")
        plan = json.loads(plan_raw)
        plan_errors = validate_plan(plan)
        if plan_errors:
            raise BridgeError("invalid committed pilot plan:\n- " + "\n- ".join(plan_errors))
        authorization_raw = committed_blob(authorization_path, "operator authorization")
        authorization = json.loads(authorization_raw)
    except (ActivationError, ManifestError, PilotError, OSError) as exc:
        raise BridgeError(f"cannot derive production authority: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise BridgeError("operator authorization is invalid JSON") from exc
    if plan["backend_manifest_sha256"] != activation.composition.sha256:
        raise BridgeError("pilot plan backend manifest differs from the official activation")
    authorization_fields = {
        "schema", "pilot_id", "plan_sha256", "backend_manifest_sha256",
        "protocol_commit", "authority", "authorized", "ratified_at",
    }
    if not isinstance(authorization, dict) or set(authorization) != authorization_fields:
        raise BridgeError("operator authorization fields are invalid")
    expected_authorization = {
        "schema": "tier-bench/tier-pilot-authorization@1",
        "pilot_id": plan["pilot_id"],
        "plan_sha256": _sha(plan_raw),
        "backend_manifest_sha256": plan["backend_manifest_sha256"],
        "protocol_commit": plan["protocol_commit"],
        "authority": "operator",
        "authorized": True,
    }
    for key, expected in expected_authorization.items():
        if authorization.get(key) != expected:
            raise BridgeError(f"operator authorization {key} does not ratify exact plan bytes")
    try:
        ratified_at = datetime.fromisoformat(
            str(authorization.get("ratified_at", "")).replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise BridgeError("operator authorization ratified_at is invalid") from exc
    if ratified_at.tzinfo is None or ratified_at > datetime.now(timezone.utc):
        raise BridgeError("operator authorization ratified_at is invalid")
    intervention_log = (evidence_repo / plan["intervention_log_path"]).resolve()
    if not _inside(intervention_log, evidence_repo) or _inside(
        intervention_log, evidence_git
    ):
        raise BridgeError("frozen intervention log path escapes evidence custody")
    return activation, plan, _sha(plan_raw), _sha(authorization_raw), intervention_log


def _production_task(plan: dict[str, Any], task_id: str, arm: str) -> dict[str, Any]:
    tasks = [task for task in plan["tasks"] if task["task_id"] == task_id]
    if len(tasks) != 1:
        raise BridgeError("production task is not unique in the frozen plan")
    coordinates = [
        row for row in plan["schedule"]
        if row["task_id"] == task_id and row["arm"] == arm
    ]
    if len(coordinates) != 1:
        raise BridgeError("production task/arm is not unique in the frozen schedule")
    return tasks[0]


def _authenticate_target_repository(
    repo: Path, plan: dict[str, Any], base_commit: str
) -> None:
    actual_remote = _git(repo, "remote", "get-url", "origin", check=False)
    if actual_remote.returncode or actual_remote.stdout.strip() != plan["target_remote"]:
        raise BridgeError("target repository origin differs from the frozen pilot plan")
    remote_ref = f"refs/heads/{plan['default_branch']}"
    query = subprocess.run(
        ["git", "ls-remote", "--exit-code", plan["target_remote"], remote_ref],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    rows = [line.split() for line in query.stdout.splitlines() if line.strip()]
    if query.returncode or len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != remote_ref:
        raise BridgeError("cannot authenticate the target default branch")
    remote_head = rows[0][0]
    if not re.fullmatch(r"[0-9a-f]{40}", remote_head):
        raise BridgeError("target default branch returned an invalid commit")
    fetch = subprocess.run(
        ["git", "fetch", "--no-tags", "--quiet", plan["target_remote"], remote_head],
        cwd=repo,
        capture_output=True,
    )
    if fetch.returncode:
        raise BridgeError("authenticated target default-branch commit did not open")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base_commit, remote_head],
        cwd=repo,
        capture_output=True,
    )
    if ancestor.returncode:
        raise BridgeError("frozen task base is not on the authenticated target default branch")


def start_pilot_arm(
    *,
    repo: Path,
    evidence_repo: Path,
    activation_commit: str,
    activation_path: str,
    plan_path: str,
    authorization_path: str,
    task_id: str,
    arm: str,
    output_dir: Path,
) -> dict[str, Any]:
    """Start one activated arm using only task bytes frozen in the pilot plan."""
    repo = _repo_root(repo)
    evidence_repo = _repo_root(evidence_repo)
    target_git = _git_common_dir(repo)
    registry_git = _git_common_dir(evidence_repo)
    if evidence_repo == repo or target_git == registry_git:
        raise BridgeError("control/evidence repository must be separate from the target")
    activation, plan, plan_sha256, authorization_sha256, _ = _production_authorities(
        evidence_repo,
        activation_commit=activation_commit,
        activation_path=activation_path,
        plan_path=plan_path,
        authorization_path=authorization_path,
    )
    task = _production_task(plan, task_id, arm)
    base_commit = task["base_commit"]
    if subprocess.run(
        ["git", "cat-file", "-e", f"{base_commit}^{{commit}}"], cwd=repo,
        capture_output=True,
    ).returncode:
        raise BridgeError("frozen base_commit is not available in the target repository")
    _authenticate_target_repository(repo, plan, base_commit)
    scopes = _normalize_scope(repo, task["files"])
    normalized_files = [path + ("/" if is_dir else "") for path, is_dir in scopes]
    if normalized_files != task["files"]:
        raise BridgeError("frozen plan file scopes are not canonically normalized")
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
        activation.composition,
        task_id=task_id,
        task_tier="pilot",
        arm=arm,
        task=task["task"],
        files=normalized_files,
        acceptance_command=task["acceptance_command"],
        base_commit=base_commit,
    )
    state = _append_state(session_dir / "state.jsonl", activation.composition, state)
    session = {
        "schema": PRODUCTION_SESSION_SCHEMA,
        "bridge_id": bridge_id,
        "repo": str(repo),
        "evidence_repo": str(evidence_repo),
        "arm_worktree": str(worktree),
        "activation_commit": activation.commit,
        "activation_path": activation.path,
        "activation_sha256": activation.sha256,
        "plan_path": plan_path,
        "plan_sha256": plan_sha256,
        "authorization_path": authorization_path,
        "authorization_sha256": authorization_sha256,
        "task_id": task_id,
        "arm": arm,
        "base_commit": base_commit,
        "files": normalized_files,
        "created_at": _now(),
    }
    (session_dir / "bridge-session.json").write_bytes(canonical_json(session))
    execution = _Execution(
        mode="production", activation=activation, fixture_script=None,
        fixture_script_sha256=None,
    )
    return _drive(
        activation.composition, state, repo, session_dir, scopes, bridge_id,
        worktree, registry_git, execution,
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
    execution = _Execution(
        mode="fixture", activation=None, fixture_script=fixture_script,
        fixture_script_sha256=fixture_script_sha256,
    )
    return _drive(
        composition, state, repo, session_dir, scopes, bridge_id,
        worktree, registry_git, execution,
    )


def _load_session(
    session_dir: Path, *, recover_missing_question_receipts: bool = False,
    allow_unreplayed_worktree: bool = False, verify_question_receipts: bool = True,
) -> tuple[
    dict[str, Any], PilotComposition, Path, Path, list[tuple[str, bool]], dict[str, Any]
]:
    session_dir = session_dir.resolve()
    if (session_dir / "bridge-abort.json").exists():
        raise BridgeError("bridge session is permanently fail-stopped")
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
    if state["status"] in {"ACTIVE", "WAITING_OPERATOR"} and not allow_unreplayed_worktree:
        if not worktree.is_dir() or _patch(worktree) != _last_candidate(state):
            raise BridgeError("active arm worktree does not match its sealed candidate lineage")
    if verify_question_receipts:
        _seal_question_receipts(
            session_dir, state,
            recover_missing=recover_missing_question_receipts,
        )
    return session, composition, repo, evidence_repo, scopes, state


def _load_production_session(
    session_dir: Path,
    *,
    recover_missing_question_receipts: bool = False,
    allow_unreplayed_worktree: bool = False,
    verify_question_receipts: bool = True,
    allow_abort: bool = False,
) -> tuple[
    dict[str, Any], PilotActivation, dict[str, Any], Path, Path,
    list[tuple[str, bool]], dict[str, Any], Path,
]:
    session_dir = session_dir.resolve()
    if (session_dir / "bridge-abort.json").exists() and not allow_abort:
        raise BridgeError("bridge session is permanently fail-stopped")
    session = _read_object(session_dir / "bridge-session.json", "production bridge session")
    required = {
        "schema", "bridge_id", "repo", "evidence_repo", "arm_worktree",
        "activation_commit", "activation_path", "activation_sha256", "plan_path",
        "plan_sha256", "authorization_path", "authorization_sha256", "task_id",
        "arm", "base_commit", "files", "created_at",
    }
    if set(session) != required or session.get("schema") != PRODUCTION_SESSION_SCHEMA:
        raise BridgeError("production bridge session fields/schema are invalid")
    repo = _repo_root(Path(session["repo"]))
    evidence_repo = _repo_root(Path(session["evidence_repo"]))
    if (
        repo == evidence_repo
        or _git_common_dir(repo) == _git_common_dir(evidence_repo)
        or not _inside(session_dir, evidence_repo)
    ):
        raise BridgeError("production session lost separate control/evidence custody")
    (
        activation, plan, plan_sha256, authorization_sha256, intervention_log,
    ) = _production_authorities(
        evidence_repo,
        activation_commit=session["activation_commit"],
        activation_path=session["activation_path"],
        plan_path=session["plan_path"],
        authorization_path=session["authorization_path"],
    )
    if activation.sha256 != session["activation_sha256"]:
        raise BridgeError("official activation bytes drifted after bridge start")
    if plan_sha256 != session["plan_sha256"]:
        raise BridgeError("frozen pilot plan bytes drifted after bridge start")
    if authorization_sha256 != session["authorization_sha256"]:
        raise BridgeError("operator authorization bytes drifted after bridge start")
    task = _production_task(plan, session["task_id"], session["arm"])
    _authenticate_target_repository(repo, plan, task["base_commit"])
    expected = {
        "base_commit": task["base_commit"],
        "files": task["files"],
    }
    for key, value in expected.items():
        if session.get(key) != value:
            raise BridgeError(f"production session {key} contradicts the frozen plan")
    scopes = _normalize_scope(repo, task["files"])
    state = read_state(activation.composition, session_dir / "state.jsonl")
    state_bindings = {
        "task_id": session["task_id"],
        "arm": session["arm"],
        "base_commit": task["base_commit"],
        "files": task["files"],
        "task": task["task"],
        "acceptance_command": task["acceptance_command"],
    }
    for key, value in state_bindings.items():
        if state.get(key) != value:
            raise BridgeError(f"production state {key} contradicts the frozen plan")
    worktree = Path(session["arm_worktree"]).resolve()
    expected_worktree = (
        _git_common_dir(repo) / "tier-pilot-worktrees" / session["bridge_id"]
    ).resolve()
    if worktree != expected_worktree:
        raise BridgeError("arm worktree path contradicts the production bridge lineage")
    if state["status"] in {"ACTIVE", "WAITING_OPERATOR"} and not allow_unreplayed_worktree:
        if not worktree.is_dir() or _patch(worktree) != _last_candidate(state):
            raise BridgeError("active production worktree differs from sealed candidate lineage")
    if verify_question_receipts:
        _seal_question_receipts(
            session_dir, state,
            recover_missing=recover_missing_question_receipts,
        )
    return (
        session, activation, plan, repo, evidence_repo, scopes, state,
        intervention_log,
    )


def _session_fixture_script(
    session: dict[str, Any], fixture_script: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], str]:
    script, digest = _fixture_script(fixture_script)
    if digest != session["fixture_script_sha256"]:
        raise BridgeError("fixture script differs from the bytes frozen at bridge start")
    return script, digest


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _clear_stale_lock(session_dir: Path, bridge_id: str) -> None:
    lock = session_dir / "arm.lock"
    if not lock.exists():
        return
    raw = lock.read_bytes()
    value = _read_object(lock, "arm drive lock")
    if (
        set(value) != {"schema", "bridge_id", "pid", "created_at"}
        or value.get("schema") != DRIVE_LOCK_SCHEMA
        or value.get("bridge_id") != bridge_id
        or not isinstance(value.get("pid"), int)
        or value["pid"] <= 0
    ):
        raise BridgeError("arm drive lock cannot be authenticated for recovery")
    try:
        created_at = datetime.fromisoformat(
            str(value.get("created_at", "")).replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise BridgeError("arm drive lock timestamp is invalid") from exc
    if created_at.tzinfo is None:
        raise BridgeError("arm drive lock timestamp is invalid")
    if _pid_alive(value["pid"]):
        raise BridgeError("arm drive lock belongs to a live process; recovery refused")
    if lock.read_bytes() != raw:
        raise BridgeError("arm drive lock changed during recovery authentication")
    _ensure_recovery_event(session_dir, "STALE_LOCK_CLEARED", "arm.lock", _sha(raw))
    lock.unlink()


def _abort_ambiguous_call(
    session_dir: Path,
    repo: Path,
    worktree: Path,
    state: dict[str, Any],
    call_dir: Path,
) -> dict[str, Any]:
    evidence_sha256 = _directory_sha256(call_dir)
    _ensure_recovery_event(
        session_dir,
        "AMBIGUOUS_DISPATCH_FAIL_STOPPED",
        call_dir.name,
        evidence_sha256,
    )
    if worktree.exists():
        process = _git(repo, "worktree", "remove", "--force", str(worktree), check=False)
        removed = process.returncode == 0 and not worktree.exists()
    else:
        removed = True
    if not removed:
        raise BridgeError("ambiguous dispatch was fail-stopped but worktree cleanup failed")
    abort = {
        "schema": ABORT_SCHEMA,
        "reason": "AMBIGUOUS_DISPATCH",
        "call_directory": call_dir.name,
        "evidence_sha256": evidence_sha256,
        "incoming_state_sha256": state["state_sha256"],
        "redispatch_permitted": False,
        "arm_worktree_removed": removed,
        "recorded_at": _now(),
    }
    path = session_dir / "bridge-abort.json"
    _write_new(path, canonical_json(abort))
    return abort


def _read_abort(path: Path) -> dict[str, Any]:
    abort = _read_object(path, "bridge abort receipt")
    if (
        set(abort) != ABORT_FIELDS
        or abort.get("schema") != ABORT_SCHEMA
        or abort.get("reason") != "AMBIGUOUS_DISPATCH"
        or abort.get("redispatch_permitted") is not False
        or abort.get("arm_worktree_removed") is not True
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", str(abort.get("call_directory", "")))
        or not re.fullmatch(r"[0-9a-f]{64}", str(abort.get("evidence_sha256", "")))
        or not re.fullmatch(r"[0-9a-f]{64}", str(abort.get("incoming_state_sha256", "")))
    ):
        raise BridgeError("bridge abort receipt fields/schema are invalid")
    try:
        recorded_at = datetime.fromisoformat(
            str(abort.get("recorded_at", "")).replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise BridgeError("bridge abort receipt timestamp is invalid") from exc
    if recorded_at.tzinfo is None:
        raise BridgeError("bridge abort receipt timestamp is invalid")
    return abort


def _verify_pre_dispatch_archives(session_dir: Path) -> None:
    rows = _read_recovery_log(session_dir)
    events = {
        row["call_directory"]: row
        for row in rows if row["action"] == "PRE_DISPATCH_ARCHIVED"
    }
    archive_root = session_dir / "recovered"
    archives = (
        sorted(path for path in archive_root.iterdir() if path.is_dir())
        if archive_root.is_dir() else []
    )
    expected_names = {f"pre-dispatch-{name}" for name in events}
    if {path.name for path in archives} - expected_names:
        raise BridgeError("pre-dispatch recovery archive has no write-ahead event")
    for call_name, row in events.items():
        call_dir = session_dir / "calls" / call_name
        archive = archive_root / f"pre-dispatch-{call_name}"
        if archive.exists():
            evidence = archive
        elif call_dir.exists():
            evidence = call_dir
        else:
            raise BridgeError("pre-dispatch recovery event has no exact evidence location")
        if _directory_sha256(evidence) != row["evidence_sha256"]:
            raise BridgeError("pre-dispatch recovery evidence changed after write-ahead")


def _recover_sealed_calls(
    session_dir: Path,
    composition: PilotComposition,
    state: dict[str, Any],
    execution: _Execution,
) -> dict[str, Any]:
    _verify_execution_evidence(session_dir, execution)
    state_path = session_dir / "state.jsonl"
    for call_dir in sorted(
        path for path in (session_dir / "calls").iterdir() if path.is_dir()
    ):
        call = _read_object(call_dir / "call.json", "sealed recovery call")
        matching_calls = [item for item in state["calls"] if item["call_id"] == call["call_id"]]
        evidence_sha256 = _directory_sha256(call_dir)
        if not matching_calls:
            _ensure_recovery_event(
                session_dir, "SEALED_STATE_REPLAYED", call_dir.name, evidence_sha256
            )
            state = _append_state(
                state_path, composition, record_pilot_call(composition, state, call)
            )
        elif matching_calls != [call]:
            raise BridgeError("sealed recovery call contradicts replayed state")
        acceptance_path = call_dir / "acceptance.json"
        matching_acceptance = [
            item for item in state["acceptance_attempts"]
            if item["causal_call_id"] == call["call_id"]
        ]
        if acceptance_path.is_file():
            acceptance = _read_object(acceptance_path, "sealed recovery acceptance")
            if not matching_acceptance:
                _ensure_recovery_event(
                    session_dir, "SEALED_STATE_REPLAYED", call_dir.name, evidence_sha256
                )
                state = _append_state(
                    state_path,
                    composition,
                    record_acceptance(composition, state, acceptance),
                )
            elif matching_acceptance != [acceptance]:
                raise BridgeError("sealed recovery acceptance contradicts replayed state")
        elif state["next_stage"] == "acceptance" and state["calls"][-1]["call_id"] == call["call_id"]:
            raise BridgeError("sealed candidate call is missing immutable acceptance evidence")
    return state


def recover_fixture_pilot_arm(
    session_dir: Path,
    *,
    fixture_script: list[dict[str, Any]],
) -> dict[str, Any]:
    session_dir = session_dir.resolve()
    abort_path = session_dir / "bridge-abort.json"
    if abort_path.exists():
        rows = _read_recovery_log(session_dir)
        abort = _read_abort(abort_path)
        matches = [
            row for row in rows
            if row["action"] == "AMBIGUOUS_DISPATCH_FAIL_STOPPED"
            and row["call_directory"] == abort["call_directory"]
            and row["evidence_sha256"] == abort["evidence_sha256"]
        ]
        if len(matches) != 1:
            raise BridgeError("bridge abort receipt lacks one exact recovery event")
        return abort
    session, composition, repo, evidence_repo, scopes, state = _load_session(
        session_dir,
        allow_unreplayed_worktree=True,
        verify_question_receipts=False,
    )
    script, script_sha256 = _session_fixture_script(session, fixture_script)
    execution = _Execution(
        mode="fixture", activation=None, fixture_script=script,
        fixture_script_sha256=script_sha256,
    )
    _clear_stale_lock(session_dir, session["bridge_id"])
    lock = _acquire_drive_lock(session_dir, session["bridge_id"])
    try:
        session, composition, repo, evidence_repo, scopes, state = _load_session(
            session_dir,
            allow_unreplayed_worktree=True,
            verify_question_receipts=False,
        )
        script, script_sha256 = _session_fixture_script(session, fixture_script)
        execution = _Execution(
            mode="fixture", activation=None, fixture_script=script,
            fixture_script_sha256=script_sha256,
        )
        _seal_question_receipts(session_dir, state, recover_missing=True)
        _verify_pre_dispatch_archives(session_dir)
        worktree = Path(session["arm_worktree"]).resolve()
        calls_dir = session_dir / "calls"
        call_dirs = sorted(path for path in calls_dir.iterdir() if path.is_dir())
        incomplete: list[tuple[Path, list[str], str | None]] = []
        for call_dir in call_dirs:
            dispatch_path = call_dir / "dispatch.json"
            journal_path = call_dir / "journal.jsonl"
            dispatch_call_id: str | None = None
            if not journal_path.exists() and not dispatch_path.exists():
                journal = []
            else:
                try:
                    dispatch = _read_object(dispatch_path, "recovery dispatch")
                    call_id = dispatch.get("call_id")
                    if not isinstance(call_id, str) or not call_id:
                        raise BridgeError("recovery dispatch has no call identity")
                    dispatch_call_id = call_id
                    journal = _read_journal(journal_path, call_id)
                except (BridgeError, OSError):
                    return _abort_ambiguous_call(
                        session_dir, repo, worktree, state, call_dir
                    )
            events = [row["event"] for row in journal]
            if events != ["PREPARED", "DISPATCH_STARTED", "EVIDENCE_SEALED"]:
                incomplete.append((call_dir, events, dispatch_call_id))
        if len(incomplete) > 1 or (incomplete and incomplete[0][0] != call_dirs[-1]):
            raise BridgeError("recovery found multiple or non-terminal incomplete calls")
        if incomplete:
            call_dir, events, dispatch_call_id = incomplete[0]
            if events in ([], ["PREPARED"]):
                allowed = {
                    "prompt.txt", "dispatch.json", "journal.jsonl", "custody.json",
                }
                if any(
                    not path.is_file() or path.name not in allowed
                    for path in call_dir.iterdir()
                ):
                    return _abort_ambiguous_call(
                        session_dir, repo, worktree, state, call_dir
                    )
                custody_path = call_dir / "custody.json"
                if not custody_path.is_file():
                    return _abort_ambiguous_call(
                        session_dir, repo, worktree, state, call_dir
                    )
                custody = _read_object(custody_path, "pre-dispatch custody")
                if (
                    set(custody) != {
                        "schema", "call_id", "session_registered", "packet_removed",
                        "arm_worktree_preserved", "completed_at", "error",
                    }
                    or custody.get("schema") != "tier-bench/tier-pilot-call-custody@1"
                    or custody.get("session_registered") is not False
                    or custody.get("packet_removed") is not True
                    or custody.get("arm_worktree_preserved") is not True
                    or not isinstance(custody.get("call_id"), str)
                    or not custody["call_id"]
                    or (
                        dispatch_call_id is not None
                        and custody["call_id"] != dispatch_call_id
                    )
                    or not (
                        custody.get("error") is None
                        or isinstance(custody.get("error"), str)
                    )
                ):
                    return _abort_ambiguous_call(
                        session_dir, repo, worktree, state, call_dir
                    )
                digest = _directory_sha256(call_dir)
                archive = session_dir / "recovered" / f"pre-dispatch-{call_dir.name}"
                archive.parent.mkdir(parents=True, exist_ok=True)
                _ensure_recovery_event(
                    session_dir, "PRE_DISPATCH_ARCHIVED", call_dir.name, digest
                )
                if archive.exists():
                    raise BridgeError("pre-dispatch recovery has two evidence locations")
                call_dir.replace(archive)
            else:
                return _abort_ambiguous_call(
                    session_dir, repo, worktree, state, call_dir
                )
        state = _recover_sealed_calls(session_dir, composition, state, execution)
        _seal_question_receipts(session_dir, state, recover_missing=True)
        _verify_pre_dispatch_archives(session_dir)
        if state["status"] in {"COMPLETE", "FAILED"} and not worktree.exists():
            return _receipt(
                session_dir, composition, state,
                worktree_removed=True, execution=execution,
            )
        if not worktree.is_dir() or _patch(worktree) != _last_candidate(state):
            raise BridgeError(
                "recovered arm worktree does not match the replayed state lineage"
            )
        registry_git = _git_common_dir(evidence_repo)
        return _drive(
            composition, state, repo, session_dir, scopes, session["bridge_id"],
            worktree, registry_git, execution, lock_owned=True,
        )
    finally:
        lock.unlink(missing_ok=True)


def recover_pilot_arm(session_dir: Path) -> dict[str, Any]:
    """Recover an activated arm without accepting activation or adapter authority."""
    session_dir = session_dir.resolve()
    abort_path = session_dir / "bridge-abort.json"
    if abort_path.exists():
        _load_production_session(
            session_dir,
            allow_unreplayed_worktree=True,
            verify_question_receipts=False,
            allow_abort=True,
        )
        rows = _read_recovery_log(session_dir)
        abort = _read_abort(abort_path)
        matches = [
            row for row in rows
            if row["action"] == "AMBIGUOUS_DISPATCH_FAIL_STOPPED"
            and row["call_directory"] == abort["call_directory"]
            and row["evidence_sha256"] == abort["evidence_sha256"]
        ]
        if len(matches) != 1:
            raise BridgeError("bridge abort receipt lacks one exact recovery event")
        return abort
    (
        session, activation, _, repo, evidence_repo, scopes, state, _,
    ) = _load_production_session(
        session_dir,
        allow_unreplayed_worktree=True,
        verify_question_receipts=False,
    )
    execution = _Execution(
        mode="production", activation=activation, fixture_script=None,
        fixture_script_sha256=None,
    )
    _clear_stale_lock(session_dir, session["bridge_id"])
    lock = _acquire_drive_lock(session_dir, session["bridge_id"])
    try:
        (
            session, activation, _, repo, evidence_repo, scopes, state, _,
        ) = _load_production_session(
            session_dir,
            allow_unreplayed_worktree=True,
            verify_question_receipts=False,
        )
        execution = _Execution(
            mode="production", activation=activation, fixture_script=None,
            fixture_script_sha256=None,
        )
        _seal_question_receipts(session_dir, state, recover_missing=True)
        _verify_pre_dispatch_archives(session_dir)
        worktree = Path(session["arm_worktree"]).resolve()
        calls_dir = session_dir / "calls"
        call_dirs = sorted(path for path in calls_dir.iterdir() if path.is_dir())
        incomplete: list[tuple[Path, list[str], str | None]] = []
        for call_dir in call_dirs:
            dispatch_path = call_dir / "dispatch.json"
            journal_path = call_dir / "journal.jsonl"
            dispatch_call_id: str | None = None
            if not journal_path.exists() and not dispatch_path.exists():
                journal = []
            else:
                try:
                    dispatch = _read_object(dispatch_path, "recovery dispatch")
                    call_id = dispatch.get("call_id")
                    if not isinstance(call_id, str) or not call_id:
                        raise BridgeError("recovery dispatch has no call identity")
                    dispatch_call_id = call_id
                    journal = _read_journal(journal_path, call_id)
                except (BridgeError, OSError):
                    return _abort_ambiguous_call(
                        session_dir, repo, worktree, state, call_dir
                    )
            events = [row["event"] for row in journal]
            if events != ["PREPARED", "DISPATCH_STARTED", "EVIDENCE_SEALED"]:
                incomplete.append((call_dir, events, dispatch_call_id))
        if len(incomplete) > 1 or (incomplete and incomplete[0][0] != call_dirs[-1]):
            raise BridgeError("recovery found multiple or non-terminal incomplete calls")
        if incomplete:
            call_dir, events, dispatch_call_id = incomplete[0]
            if events in ([], ["PREPARED"]):
                allowed = {
                    "prompt.txt", "dispatch.json", "journal.jsonl", "custody.json",
                }
                if any(
                    not path.is_file() or path.name not in allowed
                    for path in call_dir.iterdir()
                ):
                    return _abort_ambiguous_call(
                        session_dir, repo, worktree, state, call_dir
                    )
                custody_path = call_dir / "custody.json"
                if not custody_path.is_file():
                    return _abort_ambiguous_call(
                        session_dir, repo, worktree, state, call_dir
                    )
                custody = _read_object(custody_path, "pre-dispatch custody")
                if (
                    set(custody) != {
                        "schema", "call_id", "session_registered", "packet_removed",
                        "arm_worktree_preserved", "completed_at", "error",
                    }
                    or custody.get("schema") != "tier-bench/tier-pilot-call-custody@1"
                    or custody.get("session_registered") is not False
                    or custody.get("packet_removed") is not True
                    or custody.get("arm_worktree_preserved") is not True
                    or not isinstance(custody.get("call_id"), str)
                    or not custody["call_id"]
                    or (
                        dispatch_call_id is not None
                        and custody["call_id"] != dispatch_call_id
                    )
                    or not (
                        custody.get("error") is None
                        or isinstance(custody.get("error"), str)
                    )
                ):
                    return _abort_ambiguous_call(
                        session_dir, repo, worktree, state, call_dir
                    )
                digest = _directory_sha256(call_dir)
                archive = session_dir / "recovered" / f"pre-dispatch-{call_dir.name}"
                archive.parent.mkdir(parents=True, exist_ok=True)
                _ensure_recovery_event(
                    session_dir, "PRE_DISPATCH_ARCHIVED", call_dir.name, digest
                )
                if archive.exists():
                    raise BridgeError("pre-dispatch recovery has two evidence locations")
                call_dir.replace(archive)
            else:
                return _abort_ambiguous_call(
                    session_dir, repo, worktree, state, call_dir
                )
        state = _recover_sealed_calls(
            session_dir, activation.composition, state, execution
        )
        _seal_question_receipts(session_dir, state, recover_missing=True)
        _verify_pre_dispatch_archives(session_dir)
        if state["status"] in {"COMPLETE", "FAILED"} and not worktree.exists():
            return _receipt(
                session_dir, activation.composition, state,
                worktree_removed=True, execution=execution,
            )
        if not worktree.is_dir() or _patch(worktree) != _last_candidate(state):
            raise BridgeError(
                "recovered arm worktree does not match the replayed state lineage"
            )
        return _drive(
            activation.composition, state, repo, session_dir, scopes,
            session["bridge_id"], worktree, _git_common_dir(evidence_repo),
            execution, lock_owned=True,
        )
    finally:
        lock.unlink(missing_ok=True)


def answer_and_resume_fixture_pilot_arm(
    session_dir: Path,
    *,
    question_id: str,
    answer: str,
    intervention_log: Path,
    fixture_script: list[dict[str, Any]],
) -> dict[str, Any]:
    session_dir = session_dir.resolve()
    session, composition, repo, evidence_repo, scopes, state = _load_session(session_dir)
    script, script_sha256 = _session_fixture_script(session, fixture_script)
    execution = _Execution(
        mode="fixture", activation=None, fixture_script=script,
        fixture_script_sha256=script_sha256,
    )
    lock = _acquire_drive_lock(session_dir.resolve(), session["bridge_id"])
    try:
        session, composition, repo, evidence_repo, scopes, state = _load_session(
            session_dir
        )
        _verify_fixture_evidence(session_dir.resolve())
        _read_recovery_log(session_dir.resolve())
        intervention_id, answered_at = _closed_intervention(
            intervention_log, state, question_id=question_id
        )
        resumed = answer_operator_question(
            composition, state, question_id=question_id, answer=answer,
            intervention_id=intervention_id, answered_at=answered_at,
        )
        resumed = _append_state(session_dir / "state.jsonl", composition, resumed)
        _seal_question_receipts(
            session_dir.resolve(), resumed, recover_missing=True, record_recovery=False
        )
        return _drive(
            composition, resumed, repo, session_dir.resolve(), scopes,
            session["bridge_id"], Path(session["arm_worktree"]).resolve(),
            _git_common_dir(evidence_repo), execution, lock_owned=True,
        )
    finally:
        lock.unlink(missing_ok=True)


def answer_and_resume_pilot_arm(
    session_dir: Path,
    *,
    question_id: str,
    answer: str,
) -> dict[str, Any]:
    session_dir = session_dir.resolve()
    (
        session, activation, _, repo, evidence_repo, scopes, state,
        intervention_log,
    ) = _load_production_session(session_dir)
    execution = _Execution(
        mode="production", activation=activation, fixture_script=None,
        fixture_script_sha256=None,
    )
    lock = _acquire_drive_lock(session_dir, session["bridge_id"])
    try:
        (
            session, activation, _, repo, evidence_repo, scopes, state,
            intervention_log,
        ) = _load_production_session(session_dir)
        execution = _Execution(
            mode="production", activation=activation, fixture_script=None,
            fixture_script_sha256=None,
        )
        _verify_production_evidence(session_dir, activation)
        _read_recovery_log(session_dir)
        intervention_id, answered_at = _closed_intervention(
            intervention_log, state, question_id=question_id
        )
        resumed = answer_operator_question(
            activation.composition, state, question_id=question_id, answer=answer,
            intervention_id=intervention_id, answered_at=answered_at,
        )
        resumed = _append_state(
            session_dir / "state.jsonl", activation.composition, resumed
        )
        _seal_question_receipts(
            session_dir, resumed, recover_missing=True, record_recovery=False
        )
        return _drive(
            activation.composition, resumed, repo, session_dir, scopes,
            session["bridge_id"], Path(session["arm_worktree"]).resolve(),
            _git_common_dir(evidence_repo), execution, lock_owned=True,
        )
    finally:
        lock.unlink(missing_ok=True)


def decline_pilot_arm(
    session_dir: Path,
    *,
    question_id: str,
    reason: str,
) -> dict[str, Any]:
    session_dir = session_dir.resolve()
    (
        session, activation, _, repo, evidence_repo, scopes, state,
        intervention_log,
    ) = _load_production_session(session_dir)
    execution = _Execution(
        mode="production", activation=activation, fixture_script=None,
        fixture_script_sha256=None,
    )
    lock = _acquire_drive_lock(session_dir, session["bridge_id"])
    try:
        (
            session, activation, _, repo, evidence_repo, scopes, state,
            intervention_log,
        ) = _load_production_session(session_dir)
        execution = _Execution(
            mode="production", activation=activation, fixture_script=None,
            fixture_script_sha256=None,
        )
        _verify_production_evidence(session_dir, activation)
        _read_recovery_log(session_dir)
        intervention_id, answered_at = _closed_intervention(
            intervention_log, state, question_id=question_id
        )
        declined = decline_operator_question(
            activation.composition, state, question_id=question_id, reason=reason,
            intervention_id=intervention_id, answered_at=answered_at,
        )
        declined = _append_state(
            session_dir / "state.jsonl", activation.composition, declined
        )
        _seal_question_receipts(
            session_dir, declined, recover_missing=True, record_recovery=False
        )
        return _drive(
            activation.composition, declined, repo, session_dir, scopes,
            session["bridge_id"], Path(session["arm_worktree"]).resolve(),
            _git_common_dir(evidence_repo), execution, lock_owned=True,
        )
    finally:
        lock.unlink(missing_ok=True)


def decline_fixture_pilot_arm(
    session_dir: Path,
    *,
    question_id: str,
    reason: str,
    intervention_log: Path,
    fixture_script: list[dict[str, Any]],
) -> dict[str, Any]:
    session_dir = session_dir.resolve()
    session, composition, repo, evidence_repo, scopes, state = _load_session(session_dir)
    script, script_sha256 = _session_fixture_script(session, fixture_script)
    execution = _Execution(
        mode="fixture", activation=None, fixture_script=script,
        fixture_script_sha256=script_sha256,
    )
    lock = _acquire_drive_lock(session_dir.resolve(), session["bridge_id"])
    try:
        session, composition, repo, evidence_repo, scopes, state = _load_session(
            session_dir
        )
        _verify_fixture_evidence(session_dir.resolve())
        _read_recovery_log(session_dir.resolve())
        intervention_id, answered_at = _closed_intervention(
            intervention_log, state, question_id=question_id
        )
        declined = decline_operator_question(
            composition, state, question_id=question_id, reason=reason,
            intervention_id=intervention_id, answered_at=answered_at,
        )
        declined = _append_state(session_dir / "state.jsonl", composition, declined)
        _seal_question_receipts(
            session_dir.resolve(), declined, recover_missing=True,
            record_recovery=False,
        )
        return _drive(
            composition, declined, repo, session_dir.resolve(), scopes,
            session["bridge_id"], Path(session["arm_worktree"]).resolve(),
            _git_common_dir(evidence_repo), execution, lock_owned=True,
        )
    finally:
        lock.unlink(missing_ok=True)
