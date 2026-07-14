from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import math
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any

from .core import CALL_FIELDS
from .events import InterventionError, validate_events
from .manifest import ManifestError
from .pilot_composition import CompositionError, read_state
from .pilot_manifest import PilotComposition, load_pilot_composition


PLAN_SCHEMA = "tier-bench/tier-pilot-plan@1"
EVIDENCE_SCHEMA = "tier-bench/tier-pilot-evidence@1"
CLOSEOUT_SCHEMA = "tier-bench/tier-pilot-closeout@1"
PROTOCOL_V13_COMMIT = "076fd1e3d97c22f7c33933c5dee4ff897d7ba4e6"
ARMS = ("arm_a", "arm_b", "arm_c")
ARM_CODES = {"A": "arm_a", "B": "arm_b", "C": "arm_c"}
BASE_ORDERS = ("ABC", "BCA", "CAB")
# The protocol says "the six permutations" but does not enumerate them.  This
# lexicographic enumeration is a GATED proposal and must be ratified before task
# disclosure.  Keeping it explicit here prevents runtime/library ordering drift.
RESIDUAL_ORDERS = ("ABC", "ACB", "BAC", "BCA", "CAB", "CBA")
FOLLOW_UP_DAYS = 14
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
COST_BASES = {"real-billed", "shadow-estimated", "subscription-derived"}
FINAL_STATES = {"ACCEPTED", "REJECTED", "ERROR"}
MANIFEST_SCHEMA = "tier-bench/pilot-backends@2"
ARM_STATE_SCHEMA = "tier-bench/pilot-arm-state@1"
CALL_RECEIPT_SCHEMA = "tier-bench/pilot-call-receipt@1"
ARM_SEAL_SCHEMA = "tier-bench/pilot-arm-seal@1"
QUESTION_RECEIPT_SCHEMA = "tier-bench/tier-pilot-question-receipt@1"
DISPATCH_RECEIPT_SCHEMA = "tier-bench/tier-pilot-dispatch-receipt@1"
AUDIT_PROFILE_SCHEMA = "tier-bench/tier-pilot-audit-normalization-profile@1"
AUDIT_NORMALIZED_SCHEMA = "tier-bench/tier-pilot-normalized-arm@1"
AUDIT_NORMALIZATION_ALGORITHM = "builtin-terminal-state-projection@1"
CALL_STAGES = {"driver_plan", "hands", "repair", "escalation", "hands_resume"}
VOID_REASONS = {
    "cross_arm_exposure",
    "intervention_log_invalid",
    "ledger_incomplete",
    "manifest_drift",
    "metric_changed",
    "missing_telemetry",
    "schedule_deviation",
    "task_definition_changed",
    "unblinded_audit",
    "untracked_operator_work",
    "other_protocol_fault",
}


class PilotError(ValueError):
    pass


def audit_normalized_payload(
    pilot_id: str,
    task_id: str,
    opaque_label: str,
    profile_sha256: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    """Built-in, non-executable audit normalization for a replayed terminal arm."""
    attempts = state.get("acceptance_attempts")
    if not isinstance(attempts, list) or not attempts:
        raise PilotError("terminal audit source has no sealed acceptance receipt")
    receipt = attempts[-1]
    receipt_fields = {
        "candidate_patch_sha256", "candidate_tree_sha256", "passed", "report",
        "report_sha256", "stdout_sha256", "stderr_sha256", "receipt_sha256",
        "causal_call_id",
    }
    if not isinstance(receipt, dict) or not receipt_fields <= set(receipt):
        raise PilotError("terminal audit source acceptance receipt is incomplete")
    calls = state.get("calls")
    candidates = [
        call for call in calls if isinstance(call, dict)
        and call.get("call_id") == receipt["causal_call_id"]
    ] if isinstance(calls, list) else []
    if len(candidates) != 1:
        raise PilotError("terminal audit source lacks its causal candidate call")
    output = candidates[0].get("output")
    if not isinstance(output, dict) or set(output) != {"kind", "text", "sha256"}:
        raise PilotError("terminal audit source candidate output is invalid")
    return {
        "schema": AUDIT_NORMALIZED_SCHEMA,
        "pilot_id": pilot_id,
        "task_id": task_id,
        "opaque_label": opaque_label,
        "profile_sha256": profile_sha256,
        "terminal_status": state.get("status"),
        "output": output,
        "acceptance": {
            "receipt_sha256": receipt["receipt_sha256"],
            "candidate_tree_sha256": receipt["candidate_tree_sha256"],
            "passed": receipt["passed"],
            "report": receipt["report"],
            "report_sha256": receipt["report_sha256"],
        },
    }


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _is_hex(value: Any, pattern: re.Pattern[str]) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _timestamp(value: Any, label: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str):
        errors.append(f"{label} must be an ISO-8601 string")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{label} must be an ISO-8601 timestamp")
        return None
    if parsed.tzinfo is None:
        errors.append(f"{label} must include a timezone")
        return None
    return parsed.astimezone(timezone.utc)


def _safe_relative(value: Any, label: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or not value:
        errors.append(f"{label} must be a non-empty relative path")
        return None
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized.rstrip("/"))
    if (
        path.is_absolute()
        or not path.parts
        or ".." in path.parts
        or re.match(r"^[A-Za-z]:", normalized)
        or normalized.startswith("//")
    ):
        errors.append(f"{label} must stay under the pilot root")
        return None
    if path.parts[0].lower() == ".git":
        errors.append(f"{label} cannot enter .git")
        return None
    return path.as_posix() + ("/" if normalized.endswith("/") else "")


def _exact_fields(value: Any, fields: set[str], label: str, errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return False
    missing = fields - set(value)
    unknown = set(value) - fields
    if missing or unknown:
        errors.append(
            f"{label} fields mismatch; missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
        return False
    return True


def _task_rows(plan: dict[str, Any], errors: list[str]) -> list[dict[str, Any]]:
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 10:
        errors.append("plan tasks must contain exactly 10 entries")
        return []
    fields = {
        "task_id", "base_commit", "task", "files", "acceptance_command",
        "withheld_audit_sha256",
    }
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for index, task in enumerate(tasks):
        label = f"tasks[{index}]"
        if not _exact_fields(task, fields, label, errors):
            continue
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not SAFE_ID.fullmatch(task_id):
            errors.append(f"{label}.task_id is unsafe")
        elif task_id in seen:
            errors.append(f"duplicate task_id {task_id!r}")
        else:
            seen.add(task_id)
        if not _is_hex(task.get("base_commit"), HEX40):
            errors.append(f"{label}.base_commit must be a full lowercase Git SHA")
        if not isinstance(task.get("task"), str) or not task["task"].strip():
            errors.append(f"{label}.task must be non-empty")
        if not isinstance(task.get("acceptance_command"), str) or not task[
            "acceptance_command"
        ].strip():
            errors.append(f"{label}.acceptance_command must be non-empty")
        if not _is_hex(task.get("withheld_audit_sha256"), HEX64):
            errors.append(f"{label}.withheld_audit_sha256 must be sha256")
        files = task.get("files")
        if not isinstance(files, list) or not files:
            errors.append(f"{label}.files must be a non-empty array")
        else:
            normalized: list[str] = []
            for file_index, value in enumerate(files):
                item = _safe_relative(value, f"{label}.files[{file_index}]", errors)
                if item is not None:
                    normalized.append(item)
                    pure = PurePosixPath(item.rstrip("/"))
                    if pure.name.lower() in {"agents.md", "claude.md"} or any(
                        part.lower() in {".codex", ".claude"} for part in pure.parts
                    ):
                        errors.append(f"{label}.files[{file_index}] is an instruction path")
            if len(set(normalized)) != len(normalized):
                errors.append(f"{label}.files contains duplicate scopes")
        rows.append(task)
    if len(seen) != 10:
        errors.append("plan must contain exactly 10 unique task_ids")
    return rows


def derive_schedule(tasks: list[dict[str, Any]], protocol_commit: str) -> list[dict[str, Any]]:
    if (
        len(tasks) != 10
        or not all(
            isinstance(task, dict)
            and isinstance(task.get("task_id"), str)
            and SAFE_ID.fullmatch(task["task_id"])
            and _is_hex(task.get("base_commit"), HEX40)
            for task in tasks
        )
        or len({task.get("task_id") for task in tasks}) != 10
    ):
        raise PilotError("schedule derivation requires exactly 10 unique valid tasks")
    if not _is_hex(protocol_commit, HEX40):
        raise PilotError("protocol_commit must be a full lowercase Git SHA")
    ordered = sorted(tasks, key=lambda item: item["task_id"])
    orders = [BASE_ORDERS[index % 3] for index in range(9)]
    residual_seed = f"{ordered[9]['task_id']}:{protocol_commit}".encode()
    residual_index = int(hashlib.sha256(residual_seed).hexdigest(), 16) % 6
    orders.append(RESIDUAL_ORDERS[residual_index])
    schedule: list[dict[str, Any]] = []
    sequence = 1
    for task, order in zip(ordered, orders):
        for position, code in enumerate(order, 1):
            schedule.append({
                "sequence": sequence,
                "task_id": task["task_id"],
                "arm": ARM_CODES[code],
                "position": position,
                "base_commit": task["base_commit"],
            })
            sequence += 1
    return schedule


def validate_plan(plan: Any) -> list[str]:
    errors: list[str] = []
    fields = {
        "schema", "pilot_id", "protocol_commit", "backend_manifest_sha256",
        "target_remote", "default_branch", "audit_normalization_profile",
        "real_billed_tolerance_fraction",
        "intervention_log_path", "follow_up_days",
        "audit_label_seed_commitment_sha256", "residual_order_enumeration",
        "tasks", "schedule",
    }
    if not _exact_fields(plan, fields, "plan", errors):
        return errors
    if plan.get("schema") != PLAN_SCHEMA:
        errors.append(f"plan.schema must be {PLAN_SCHEMA}")
    if not isinstance(plan.get("pilot_id"), str) or not SAFE_ID.fullmatch(plan["pilot_id"]):
        errors.append("plan.pilot_id is unsafe")
    if plan.get("protocol_commit") != PROTOCOL_V13_COMMIT:
        errors.append(
            f"plan.protocol_commit must equal exact v1.3 commit {PROTOCOL_V13_COMMIT}"
        )
    if not _is_hex(plan.get("backend_manifest_sha256"), HEX64):
        errors.append("plan.backend_manifest_sha256 must be sha256")
    if not isinstance(plan.get("target_remote"), str) or not plan["target_remote"].strip():
        errors.append("plan.target_remote must be non-empty")
    if not isinstance(plan.get("default_branch"), str) or not SAFE_ID.fullmatch(plan["default_branch"]):
        errors.append("plan.default_branch is unsafe")
    profile = plan.get("audit_normalization_profile")
    if not isinstance(profile, dict) or set(profile) != {"path", "sha256"} or not _is_hex(profile.get("sha256"), HEX64):
        errors.append("plan.audit_normalization_profile must bind path and sha256")
    else:
        _safe_relative(profile.get("path"), "plan.audit_normalization_profile.path", errors)
    tolerance = plan.get("real_billed_tolerance_fraction")
    if (
        not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool)
        or not math.isfinite(float(tolerance)) or not 0 <= tolerance <= 0.1
    ):
        errors.append("plan.real_billed_tolerance_fraction must be frozen between 0 and 0.1")
    _safe_relative(plan.get("intervention_log_path"), "plan.intervention_log_path", errors)
    if plan.get("follow_up_days") != FOLLOW_UP_DAYS:
        errors.append(f"plan.follow_up_days must equal {FOLLOW_UP_DAYS}")
    if not _is_hex(plan.get("audit_label_seed_commitment_sha256"), HEX64):
        errors.append("plan.audit_label_seed_commitment_sha256 must be sha256")
    if plan.get("residual_order_enumeration") != list(RESIDUAL_ORDERS):
        errors.append(
            "plan.residual_order_enumeration must equal "
            "[ABC, ACB, BAC, BCA, CAB, CBA] (GATED proposal)"
        )
    tasks = _task_rows(plan, errors)
    if (
        len(tasks) == 10
        and _is_hex(plan.get("protocol_commit"), HEX40)
        and all(
            isinstance(task.get("task_id"), str)
            and SAFE_ID.fullmatch(task["task_id"])
            and _is_hex(task.get("base_commit"), HEX40)
            for task in tasks
        )
    ):
        expected = derive_schedule(tasks, plan["protocol_commit"])
        if plan.get("schedule") != expected:
            errors.append(
                "plan.schedule does not equal the frozen Latin-square schedule with "
                "lexicographic residual enumeration"
            )
    return errors


def load_plan(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PilotError(f"invalid pilot plan JSON: {exc}") from exc
    errors = validate_plan(value)
    if errors:
        raise PilotError("invalid pilot plan:\n- " + "\n- ".join(errors))
    return value, raw


def audit_label(seed: bytes, pilot_id: str, task_id: str, arm: str) -> str:
    if len(seed) != 32:
        raise PilotError("audit label seed must be exactly 32 bytes")
    if arm not in ARMS:
        raise PilotError(f"unknown arm {arm!r}")
    message = f"{pilot_id}\0{task_id}\0{arm}".encode()
    return "audit-" + hmac.new(seed, message, hashlib.sha256).hexdigest()[:20]


def _artifact(
    root: Path, value: Any, label: str, errors: list[str]
) -> tuple[Path, str] | None:
    if not _exact_fields(value, {"path", "sha256"}, label, errors):
        return None
    relative = _safe_relative(value.get("path"), f"{label}.path", errors)
    digest = value.get("sha256")
    if not _is_hex(digest, HEX64):
        errors.append(f"{label}.sha256 must be sha256")
        return None
    if relative is None:
        return None
    path = (root / Path(*PurePosixPath(relative).parts)).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        errors.append(f"{label}.path escapes the evidence root")
        return None
    if not path.is_file():
        errors.append(f"{label}.path does not exist: {relative}")
        return None
    actual = sha256_file(path)
    if actual != digest:
        errors.append(f"{label} hash mismatch: expected {digest}, got {actual}")
        return None
    return path, digest


def _git_artifact(
    root: Path, value: Any, label: str, errors: list[str]
) -> tuple[Path, str, dict[str, str]] | None:
    if not _exact_fields(value, {"path", "sha256", "git_proof"}, label, errors):
        return None
    artifact = _artifact(
        root, {"path": value.get("path"), "sha256": value.get("sha256")}, label, errors
    )
    proof = value.get("git_proof")
    fields = {"commit_oid", "path", "blob_oid", "anchor_commit_oid"}
    if not _exact_fields(proof, fields, f"{label}.git_proof", errors):
        return None
    assert isinstance(proof, dict)
    for key in ("commit_oid", "blob_oid", "anchor_commit_oid"):
        if not isinstance(proof.get(key), str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", proof[key]):
            errors.append(f"{label}.git_proof.{key} must be a full Git object id")
    git_path = _safe_relative(proof.get("path"), f"{label}.git_proof.path", errors)
    if artifact is None or git_path is None:
        return None
    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=False
        )
    shown = git("show", f"{proof['commit_oid']}:{git_path}")
    if shown.returncode or shown.stdout != artifact[0].read_bytes():
        errors.append(f"{label} exact bytes are not present at the proved Git object/path")
    listed = git("ls-tree", proof["commit_oid"], "--", git_path)
    try:
        actual_blob = listed.stdout.decode("utf-8").strip().split()[2]
    except (IndexError, UnicodeDecodeError):
        actual_blob = None
    if actual_blob != proof.get("blob_oid"):
        errors.append(f"{label}.git_proof.blob_oid does not match the committed path")
    ancestry = git("merge-base", "--is-ancestor", proof["commit_oid"], proof["anchor_commit_oid"])
    if ancestry.returncode:
        errors.append(f"{label} ratification commit is not anchored in the selected custody point")
    return artifact[0], artifact[1], proof


def _git_is_ancestor(root: Path, older: str, newer: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", older, newer],
        capture_output=True,
    ).returncode == 0


def _git_path_exists(root: Path, commit: str, path: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(root), "cat-file", "-e", f"{commit}:{path}"],
        capture_output=True,
    ).returncode == 0


def _git_blob_exists(root: Path, commit: str, blob_oid: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", commit],
        capture_output=True, text=True,
    )
    if result.returncode:
        return False
    return any(
        len(parts := line.split(None, 3)) >= 3 and parts[2] == blob_oid
        for line in result.stdout.splitlines()
    )


def _json_artifact_object(
    artifact: tuple[Path, str] | None, label: str, errors: list[str]
) -> dict[str, Any] | None:
    if artifact is None:
        return None
    try:
        value = json.loads(artifact[0].read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        errors.append(f"{label} must be a UTF-8 JSON object")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label} must be a JSON object")
        return None
    return value


def _load_composition_manifest(
    artifact: tuple[Path, str] | None, plan: dict[str, Any], errors: list[str]
) -> dict[str, Any] | None:
    manifest = _json_artifact_object(artifact, "backend_manifest", errors)
    if manifest is None or artifact is None:
        return None
    root_fields = {
        "schema", "protocol_commit", "isolation", "tool_versions", "acceptance_tool_versions",
        "prompt_templates", "backends", "arms",
    }
    if not _exact_fields(manifest, root_fields, "backend_manifest payload", errors):
        return None
    if manifest.get("schema") != MANIFEST_SCHEMA:
        errors.append("backend_manifest payload must use pilot-backends@2")
    if manifest.get("protocol_commit") != PROTOCOL_V13_COMMIT:
        errors.append("backend_manifest payload is not bound to exact protocol v1.3")
    if artifact[1] != plan.get("backend_manifest_sha256"):
        errors.append("backend_manifest artifact does not open the plan commitment")
    isolation = manifest.get("isolation")
    required_isolation = {
        "fresh_session_per_call": True,
        "instruction_files": False,
        "auto_memory": False,
        "conversation_carryover": False,
    }
    if not isinstance(isolation, dict) or any(
        isolation.get(key) is not value for key, value in required_isolation.items()
    ):
        errors.append("backend_manifest isolation contract is not fail-closed")
    tool_versions = manifest.get("tool_versions")
    if not isinstance(tool_versions, dict) or not tool_versions or not all(
        isinstance(key, str) and key and isinstance(value, str) and value
        for key, value in tool_versions.items()
    ):
        errors.append("backend_manifest tool_versions are invalid")
    acceptance_tools = manifest.get("acceptance_tool_versions")
    if not isinstance(acceptance_tools, dict) or not acceptance_tools or not all(
        isinstance(key, str) and key and isinstance(value, str) and value
        for key, value in acceptance_tools.items()
    ):
        errors.append("backend_manifest acceptance_tool_versions are invalid")
    templates = manifest.get("prompt_templates")
    if not isinstance(templates, dict) or not templates:
        errors.append("backend_manifest prompt_templates must be non-empty")
        templates = {}
    for name, binding in templates.items():
        label = f"backend_manifest.prompt_templates.{name}"
        if not _exact_fields(binding, {"path", "sha256"}, label, errors):
            continue
        relative = _safe_relative(binding.get("path"), f"{label}.path", errors)
        if not _is_hex(binding.get("sha256"), HEX64):
            errors.append(f"{label}.sha256 must be sha256")
        if relative is not None:
            template_path = (artifact[0].parent / Path(*PurePosixPath(relative).parts)).resolve()
            try:
                template_path.relative_to(artifact[0].parent.resolve())
            except ValueError:
                errors.append(f"{label}.path escapes the manifest root")
            else:
                if not template_path.is_file():
                    errors.append(f"{label}.path does not exist beside the manifest")
                elif sha256_file(template_path) != binding.get("sha256"):
                    errors.append(f"{label} exact prompt bytes do not open the manifest hash")
    backends = manifest.get("backends")
    backend_fields = {
        "model_id", "effort", "surface", "cost_basis", "account", "tier", "adapter",
    }
    if not isinstance(backends, dict) or not backends:
        errors.append("backend_manifest backends must be non-empty")
        backends = {}
    for name, backend in backends.items():
        label = f"backend_manifest.backends.{name}"
        if not _exact_fields(backend, backend_fields, label, errors):
            continue
        for key in ("model_id", "effort", "surface", "account", "tier"):
            if not isinstance(backend.get(key), str) or not backend[key]:
                errors.append(f"{label}.{key} must be non-empty")
        if backend.get("cost_basis") not in COST_BASES:
            errors.append(f"{label}.cost_basis is invalid")
        adapter = backend.get("adapter")
        if not _exact_fields(adapter, {"command"}, f"{label}.adapter", errors):
            continue
        command = adapter.get("command")
        if not isinstance(command, list) or not command or not all(
            isinstance(item, str) and item for item in command
        ):
            errors.append(f"{label}.adapter.command must be non-empty argv")
    arms = manifest.get("arms")
    if not isinstance(arms, dict) or set(arms) != set(ARMS):
        errors.append("backend_manifest arms must contain exactly arm_a/arm_b/arm_c")
        return manifest
    try:
        hands = [
            (arms[arm]["hands"]["backend"], arms[arm]["hands"]["prompt_template"])
            for arm in ARMS
        ]
    except (KeyError, TypeError):
        errors.append("backend_manifest arms do not expose frozen hands stages")
    else:
        if len(set(hands)) != 1:
            errors.append("backend_manifest does not freeze identical hands across all arms")
    return manifest


def _load_ledger(path: Path, label: str, errors: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"{label} line {number} is invalid JSON")
            continue
        if not isinstance(row, dict):
            errors.append(f"{label} line {number} must be an object")
            continue
        rows.append(row)
    if not rows:
        errors.append(f"{label} must contain at least one call")
    return rows


def _manifest_stage(
    manifest: dict[str, Any], arm: str, stage: str, attempt: Any
) -> tuple[str, str] | None:
    try:
        arm_spec = manifest["arms"][arm]
        if stage == "driver_plan":
            spec = arm_spec["driver"]
        elif stage == "hands":
            spec = arm_spec["hands"]
        elif stage == "repair":
            spec = arm_spec["repair"]
        elif stage == "hands_resume":
            spec = {
                "backend": arm_spec["hands"]["backend"],
                "prompt_template": arm_spec["question_route"]["resume_prompt_template"],
            }
        elif stage == "escalation":
            spec = arm_spec["escalations"][int(attempt) - 1]
        else:
            return None
        return spec["backend"], spec["prompt_template"]
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _validate_dispatch(
    value: dict[str, Any] | None,
    label: str,
    task: dict[str, Any] | None,
    run: dict[str, Any],
    manifest_sha: str,
    errors: list[str],
) -> None:
    fields = {
        "schema", "call_id", "task_id", "arm", "stage", "attempt", "backend",
        "prompt_template", "prompt_sha256", "base_commit", "task_sha256", "files",
        "acceptance_sha256", "composition_manifest_sha256",
    }
    if not _exact_fields(value, fields, label, errors):
        return
    assert value is not None
    if value.get("schema") != DISPATCH_RECEIPT_SCHEMA:
        errors.append(f"{label}.schema is invalid")
    for key in ("task_id", "arm", "base_commit"):
        if value.get(key) != run.get(key):
            errors.append(f"{label}.{key} differs from the frozen arm coordinate")
    if value.get("composition_manifest_sha256") != manifest_sha:
        errors.append(f"{label} backend manifest hash drifted")
    if value.get("stage") not in CALL_STAGES:
        errors.append(f"{label}.stage is invalid")
    if not isinstance(value.get("attempt"), int) or isinstance(value.get("attempt"), bool) or value["attempt"] < 1:
        errors.append(f"{label}.attempt must be a positive integer")
    if not isinstance(value.get("prompt_template"), dict) or set(value["prompt_template"]) != {"name", "sha256"}:
        errors.append(f"{label}.prompt_template must contain exactly name and sha256")
    if not _is_hex(value.get("prompt_sha256"), HEX64):
        errors.append(f"{label}.prompt_sha256 must be sha256")
    if task is not None:
        expected = {
            "task_sha256": sha256_bytes(task["task"].encode("utf-8")),
            "files": task["files"],
            "acceptance_sha256": sha256_bytes(task["acceptance_command"].encode("utf-8")),
        }
        for key, frozen in expected.items():
            if value.get(key) != frozen:
                errors.append(f"{label}.{key} differs from the frozen task packet")


def _validate_call_against_manifest(
    receipt: dict[str, Any], manifest: dict[str, Any], manifest_sha: str,
    label: str, errors: list[str]
) -> None:
    expected = _manifest_stage(
        manifest, str(receipt.get("arm")), str(receipt.get("stage")), receipt.get("attempt")
    )
    if expected is None:
        errors.append(f"{label} has no frozen backend/template stage")
        return
    backend_name, template_name = expected
    if receipt.get("backend") != backend_name:
        errors.append(f"{label}.backend contradicts the backend manifest")
    template = receipt.get("prompt_template")
    template_spec = manifest.get("prompt_templates", {}).get(template_name, {})
    expected_template = {"name": template_name, "sha256": template_spec.get("sha256")}
    if template != expected_template:
        errors.append(f"{label}.prompt_template contradicts the backend manifest")
    backend = manifest.get("backends", {}).get(backend_name)
    if not isinstance(backend, dict):
        errors.append(f"{label} names an unknown backend")
        return
    call = receipt.get("ledger_call")
    if not isinstance(call, dict) or set(call) != CALL_FIELDS:
        errors.append(f"{label}.ledger_call fields do not match ledger.Call")
        return
    expected_call = {
        "account": backend.get("account"), "model": backend.get("model_id"),
        "tier": backend.get("tier"), "task_id": receipt.get("task_id"),
        "phase": receipt.get("arm"), "effort": backend.get("effort"),
    }
    for key, frozen in expected_call.items():
        if call.get(key) != frozen:
            errors.append(f"{label}.ledger_call.{key} contradicts the backend manifest")
    for key in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "trial"):
        value = call.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(f"{label}.ledger_call.{key} must be a non-negative integer")
    for key in ("cost_usd", "latency_ms"):
        value = call.get(key)
        if (
            not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(float(value)) or value < 0
        ):
            errors.append(f"{label}.ledger_call.{key} must be finite and non-negative")
    output = receipt.get("output")
    if not isinstance(output, dict) or set(output) != {"kind", "text", "sha256"}:
        errors.append(f"{label}.output must contain exactly kind/text/sha256")
    elif (
        not isinstance(output.get("text"), str) or not output["text"]
        or output.get("sha256") != sha256_bytes(output["text"].encode("utf-8"))
    ):
        errors.append(f"{label}.output does not open its exact provider bytes")
    if receipt.get("session_id") != call.get("extra", {}).get("session_id"):
        errors.append(f"{label}.session_id contradicts ledger_call")
    extra = call.get("extra")
    expected_extra = {
        "backend_manifest_sha256": manifest_sha,
        "backend_surface": backend.get("surface"),
        "cost_basis": backend.get("cost_basis"),
        "dispatch_receipt_sha256": receipt.get("dispatch_receipt_sha256"),
        "prompt_template_sha256": template_spec.get("sha256"),
        "runtime_model_id": backend.get("model_id"),
        "session_id": receipt.get("session_id"),
        "tool_versions": manifest.get("tool_versions"),
    }
    if not isinstance(extra, dict):
        errors.append(f"{label}.ledger_call.extra must be an object")
        return
    for key, frozen in expected_extra.items():
        if extra.get(key) != frozen:
            errors.append(f"{label}.ledger_call.extra.{key} contradicts sealed provenance")
    if extra.get("telemetry_complete") is not True:
        errors.append(f"{label}.ledger_call telemetry is incomplete")


def _validate_bridge_raw_evidence(
    run: dict[str, Any], calls: list[dict[str, Any]], state: dict[str, Any] | None,
    root: Path, label: str, errors: list[str],
) -> None:
    providers = run.get("provider_receipts")
    if not isinstance(providers, list) or len(providers) != len(calls):
        errors.append(f"{label}.provider_receipts must cover every call exactly once")
    else:
        for index, row in enumerate(providers):
            artifact = _artifact(root, row, f"{label}.provider_receipts[{index}]", errors)
            value = _json_artifact_object(artifact, f"{label}.provider_receipts[{index}]", errors)
            fields = {"schema", "call_id", "dispatch_receipt_sha256", "provider_result", "raw_artifacts"}
            if value is None or not _exact_fields(value, fields, f"{label}.provider_receipts[{index}] payload", errors):
                continue
            call = calls[index]
            if value.get("schema") != "tier-bench/tier-pilot-provider-evidence@1":
                errors.append(f"{label}.provider_receipts[{index}] schema is invalid")
            if value.get("call_id") != call.get("call_id"):
                errors.append(f"{label}.provider_receipts[{index}] call_id drifted")
            if value.get("dispatch_receipt_sha256") != call.get("dispatch_receipt_sha256"):
                errors.append(f"{label}.provider_receipts[{index}] dispatch hash drifted")
            result_artifact = _artifact(root, value.get("provider_result"), f"{label}.provider_receipts[{index}].provider_result", errors)
            result = _json_artifact_object(result_artifact, f"{label}.provider_receipts[{index}].provider_result", errors)
            if not isinstance(result, dict) or result.get("schema") != "tier-bench/tier-backend-result@1":
                errors.append(f"{label}.provider_receipts[{index}] provider result schema is invalid")
                continue
            if set(result) != {"schema", "calls", "pilot_output", "artifacts"}:
                errors.append(f"{label}.provider_receipts[{index}] provider result fields are invalid")
            if result.get("calls") != [call.get("ledger_call")]:
                errors.append(f"{label}.provider_receipts[{index}] provider call differs from sealed call")
            pilot_output = result.get("pilot_output")
            if not isinstance(pilot_output, dict) or set(pilot_output) != {"outcome", "text"}:
                errors.append(f"{label}.provider_receipts[{index}] pilot_output shape is invalid")
            else:
                if pilot_output.get("outcome") != call.get("outcome"):
                    errors.append(f"{label}.provider_receipts[{index}] pilot_output outcome drifted")
                call_output = call.get("output", {})
                if call_output.get("kind") in {"plan", "question", "error"} and pilot_output.get("text") != call_output.get("text"):
                    errors.append(f"{label}.provider_receipts[{index}] pilot_output bytes drifted")
            declared = result.get("artifacts")
            raws = value.get("raw_artifacts")
            if not isinstance(declared, list) or not isinstance(raws, list) or not raws:
                errors.append(f"{label}.provider_receipts[{index}] must open raw provider artifacts")
                continue
            expected = {(item.get("name"), item.get("sha256")) for item in declared if isinstance(item, dict)}
            opened: set[tuple[Any, Any]] = set()
            for raw_index, raw in enumerate(raws):
                if not isinstance(raw, dict) or set(raw) != {"name", "path", "sha256"}:
                    errors.append(f"{label}.provider_receipts[{index}].raw_artifacts[{raw_index}] shape is invalid")
                    continue
                opened_artifact = _artifact(root, {"path": raw.get("path"), "sha256": raw.get("sha256")}, f"{label}.provider_receipts[{index}].raw_artifacts[{raw_index}]", errors)
                if opened_artifact is not None:
                    opened.add((raw.get("name"), opened_artifact[1]))
            if opened != expected or not any(name == "provider_raw" for name, _ in opened):
                errors.append(f"{label}.provider_receipts[{index}] raw artifact custody is incomplete")

    attempts = state.get("acceptance_attempts", []) if isinstance(state, dict) else []
    acceptances = run.get("acceptance_receipts")
    if not isinstance(acceptances, list) or len(acceptances) != len(attempts):
        errors.append(f"{label}.acceptance_receipts must cover every acceptance exactly once")
        return
    for index, row in enumerate(acceptances):
        artifact = _artifact(root, row, f"{label}.acceptance_receipts[{index}]", errors)
        value = _json_artifact_object(artifact, f"{label}.acceptance_receipts[{index}]", errors)
        fields = {"schema", "receipt_sha256", "receipt", "stdout", "stderr", "candidate_before", "candidate_after", "report"}
        if value is None or not _exact_fields(value, fields, f"{label}.acceptance_receipts[{index}] payload", errors):
            continue
        expected_receipt = attempts[index]
        if value.get("schema") != "tier-bench/tier-pilot-acceptance-evidence@1":
            errors.append(f"{label}.acceptance_receipts[{index}] schema is invalid")
        if value.get("receipt_sha256") != expected_receipt.get("receipt_sha256"):
            errors.append(f"{label}.acceptance_receipts[{index}] receipt hash drifted")
        receipt_artifact = _artifact(root, value.get("receipt"), f"{label}.acceptance_receipts[{index}].receipt", errors)
        if _json_artifact_object(receipt_artifact, f"{label}.acceptance_receipts[{index}].receipt", errors) != expected_receipt:
            errors.append(f"{label}.acceptance_receipts[{index}] receipt differs from replayed state")
        opened: dict[str, tuple[Path, str]] = {}
        for name in ("stdout", "stderr", "candidate_before", "candidate_after", "report"):
            item = _artifact(root, value.get(name), f"{label}.acceptance_receipts[{index}].{name}", errors)
            if item is not None:
                opened[name] = item
        for name in ("stdout", "stderr"):
            if name in opened and opened[name][1] != expected_receipt.get(f"{name}_sha256"):
                errors.append(f"{label}.acceptance_receipts[{index}] {name} hash drifted")
        for name in ("candidate_before", "candidate_after"):
            if name in opened and opened[name][1] != expected_receipt.get("candidate_patch_sha256"):
                errors.append(f"{label}.acceptance_receipts[{index}] {name} is not the tested candidate")
        if "candidate_before" in opened and "candidate_after" in opened and opened["candidate_before"][0].read_bytes() != opened["candidate_after"][0].read_bytes():
            errors.append(f"{label}.acceptance_receipts[{index}] candidate changed during acceptance")
        if "report" in opened and (
            opened["report"][1] != expected_receipt.get("report_sha256")
            or opened["report"][0].read_text(encoding="utf-8") != expected_receipt.get("report")
        ):
            errors.append(f"{label}.acceptance_receipts[{index}] raw report drifted")


def _validate_arm_run(
    run: Any,
    index: int,
    tasks: dict[str, dict[str, Any]],
    plan: dict[str, Any],
    manifest: dict[str, Any],
    composition: PilotComposition | None,
    root: Path,
    authorization_time: datetime | None,
    errors: list[str],
) -> tuple[
    tuple[str, str] | None, list[dict[str, Any]], datetime | None,
    list[dict[str, Any]], dict[str, Any] | None,
]:
    label = f"arm_runs[{index}]"
    fields = {
        "task_id", "arm", "sequence", "position", "base_commit", "sealed_at", "final_state",
        "protocol_valid", "composition_state", "arm_seal", "call_receipts",
        "dispatch_receipts", "provider_receipts", "acceptance_receipts",
        "question_receipts", "driver_trace", "ledger",
    }
    if not _exact_fields(run, fields, label, errors):
        return None, [], None, [], None
    task_id = run.get("task_id")
    arm = run.get("arm")
    coordinate = (task_id, arm) if isinstance(task_id, str) and isinstance(arm, str) else None
    task = tasks.get(task_id) if isinstance(task_id, str) else None
    if task is None:
        errors.append(f"{label}.task_id is not in the frozen plan")
    if arm not in ARMS:
        errors.append(f"{label}.arm is invalid")
    schedule_by_coordinate = {
        (entry["task_id"], entry["arm"]): entry for entry in plan.get("schedule", [])
        if isinstance(entry, dict) and "task_id" in entry and "arm" in entry
    }
    expected_schedule = schedule_by_coordinate.get((task_id, arm))
    if expected_schedule is None:
        errors.append(f"{label} has no coordinate in the frozen schedule")
    elif (
        run.get("sequence") != expected_schedule["sequence"]
        or run.get("position") != expected_schedule["position"]
    ):
        errors.append(f"{label} sequence/position deviates from the frozen schedule")
    if task is not None and run.get("base_commit") != task["base_commit"]:
        errors.append(f"{label}.base_commit differs from the task base")
    if run.get("final_state") not in FINAL_STATES:
        errors.append(f"{label}.final_state is invalid")
    if not isinstance(run.get("protocol_valid"), bool):
        errors.append(f"{label}.protocol_valid must be boolean")
    sealed_at = _timestamp(run.get("sealed_at"), f"{label}.sealed_at", errors)

    state_artifact = _artifact(root, run.get("composition_state"), f"{label}.composition_state", errors)
    state: dict[str, Any] | None = None
    if state_artifact is not None and composition is not None:
        try:
            state = read_state(composition, state_artifact[0])
        except (CompositionError, OSError, UnicodeDecodeError) as exc:
            errors.append(f"{label}.composition_state log does not replay: {exc}")
    elif state_artifact is not None:
        errors.append(f"{label}.composition_state cannot replay without a valid manifest")
    if state is not None:
        bindings = {
            "schema": ARM_STATE_SCHEMA, "composition_manifest_sha256": plan["backend_manifest_sha256"],
            "protocol_commit": PROTOCOL_V13_COMMIT, "task_id": task_id, "arm": arm,
            "base_commit": run.get("base_commit"),
        }
        if task is not None:
            bindings.update({"task": task["task"], "files": task["files"], "acceptance_command": task["acceptance_command"]})
        for key, frozen in bindings.items():
            if state.get(key) != frozen:
                errors.append(f"{label}.composition_state payload {key} contradicts frozen input")
        if state.get("status") not in {"COMPLETE", "FAILED"} or state.get("next_stage") is not None:
            errors.append(f"{label}.composition_state is not terminal")
        if run.get("final_state") == "ACCEPTED" and state.get("status") != "COMPLETE":
            errors.append(f"{label}.final_state contradicts composition terminal state")
        acceptance_attempts = state.get("acceptance_attempts", [])
        if run.get("final_state") == "ACCEPTED" and not (
            acceptance_attempts and acceptance_attempts[-1].get("passed") is True
        ):
            errors.append(f"{label}.final_state ACCEPTED lacks a sealed passing acceptance receipt")
        for receipt_index, receipt in enumerate(acceptance_attempts):
            recorded = _timestamp(
                receipt.get("recorded_at"),
                f"{label}.composition_state acceptance[{receipt_index}].recorded_at", errors,
            )
            if recorded is not None and sealed_at is not None and recorded > sealed_at:
                errors.append(f"{label}.composition_state acceptance occurred after arm seal")
            if recorded is not None and authorization_time is not None and recorded < authorization_time:
                errors.append(f"{label}.composition_state acceptance occurred before authorization")

    driver_trace_sha: str | None = None
    if arm == "arm_a":
        trace_artifact = _artifact(root, run.get("driver_trace"), f"{label}.driver_trace", errors)
        expected_trace = b"".join(
            canonical_json(trace) for trace in (state or {}).get("driver_traces", [])
        )
        if trace_artifact is not None:
            driver_trace_sha = trace_artifact[1]
            if trace_artifact[0].read_bytes() != expected_trace:
                errors.append(f"{label}.driver_trace does not equal replay-derived append_driver_traces output")
    elif run.get("driver_trace") is not None:
        errors.append(f"{label}.driver_trace must be null outside Arm A")

    dispatches = run.get("dispatch_receipts")
    dispatch_hashes: list[str] = []
    dispatch_values: dict[str, dict[str, Any]] = {}
    if not isinstance(dispatches, list) or not dispatches:
        errors.append(f"{label}.dispatch_receipts must be non-empty")
    else:
        for dispatch_index, artifact in enumerate(dispatches):
            result = _artifact(
                root, artifact, f"{label}.dispatch_receipts[{dispatch_index}]", errors
            )
            if result is not None:
                dispatch_hashes.append(result[1])
                value = _json_artifact_object(result, f"{label}.dispatch_receipts[{dispatch_index}]", errors)
                _validate_dispatch(value, f"{label}.dispatch_receipts[{dispatch_index}] payload", task, run, plan["backend_manifest_sha256"], errors)
                if value is not None:
                    dispatch_values[result[1]] = value
        if len(set(dispatch_hashes)) != len(dispatch_hashes):
            errors.append(f"{label}.dispatch_receipts contains duplicate hashes")
    call_artifacts = run.get("call_receipts")
    call_values: list[dict[str, Any]] = []
    if not isinstance(call_artifacts, list) or not call_artifacts:
        errors.append(f"{label}.call_receipts must be non-empty")
    else:
        for call_index, artifact_value in enumerate(call_artifacts):
            artifact = _artifact(root, artifact_value, f"{label}.call_receipts[{call_index}]", errors)
            receipt = _json_artifact_object(artifact, f"{label}.call_receipts[{call_index}]", errors)
            receipt_fields = {
                "schema", "call_id", "task_id", "arm", "stage", "attempt", "backend",
                "prompt_template", "prompt_sha256", "dispatch_receipt_sha256", "session_id",
                "outcome", "output", "ledger_call",
            }
            if receipt is None or not _exact_fields(receipt, receipt_fields, f"{label}.call_receipts[{call_index}] payload", errors):
                continue
            if receipt.get("schema") != CALL_RECEIPT_SCHEMA:
                errors.append(f"{label}.call_receipts[{call_index}] schema is invalid")
            if receipt.get("task_id") != task_id or receipt.get("arm") != arm:
                errors.append(f"{label}.call_receipts[{call_index}] task/arm differs from run")
            dispatch_sha = receipt.get("dispatch_receipt_sha256")
            dispatch = dispatch_values.get(dispatch_sha)
            if dispatch is None:
                errors.append(f"{label}.call_receipts[{call_index}] names no frozen dispatch receipt")
            else:
                for key in ("call_id", "task_id", "arm", "stage", "attempt", "backend", "prompt_template", "prompt_sha256"):
                    if receipt.get(key) != dispatch.get(key):
                        errors.append(f"{label}.call_receipts[{call_index}] {key} contradicts dispatch")
            _validate_call_against_manifest(
                receipt, manifest, plan["backend_manifest_sha256"],
                f"{label}.call_receipts[{call_index}]", errors
            )
            call_values.append(receipt)

    if state is not None and state.get("calls") != call_values:
        errors.append(f"{label}.composition_state calls do not equal sealed call receipts in order")
    _validate_bridge_raw_evidence(run, call_values, state, root, label, errors)

    question_artifacts = run.get("question_receipts")
    question_values: list[dict[str, Any]] = []
    question_hashes: list[str] = []
    if not isinstance(question_artifacts, list):
        errors.append(f"{label}.question_receipts must be an array")
    else:
        question_fields = {
            "schema", "question_id", "task_id", "arm", "intervention_id",
            "asked_at", "answered_at", "question_sha256", "answer_sha256",
        }
        state_questions = state.get("questions", []) if isinstance(state, dict) else []
        for question_index, artifact_value in enumerate(question_artifacts):
            artifact = _artifact(root, artifact_value, f"{label}.question_receipts[{question_index}]", errors)
            receipt = _json_artifact_object(artifact, f"{label}.question_receipts[{question_index}]", errors)
            if artifact is not None:
                question_hashes.append(artifact[1])
            if receipt is None or not _exact_fields(receipt, question_fields, f"{label}.question_receipts[{question_index}] payload", errors):
                continue
            if receipt.get("schema") != QUESTION_RECEIPT_SCHEMA or receipt.get("arm") != "arm_c":
                errors.append(f"{label}.question_receipts[{question_index}] is not an Arm-C question receipt")
            if receipt.get("task_id") != task_id or arm != "arm_c":
                errors.append(f"{label}.question_receipts[{question_index}] coordinate differs from run")
            matching = [q for q in state_questions if isinstance(q, dict) and q.get("question_id") == receipt.get("question_id")]
            if len(matching) != 1:
                errors.append(f"{label}.question_receipts[{question_index}] does not bind exactly one state question")
            else:
                q = matching[0]
                for key in ("question_sha256", "answer_sha256", "answered_at"):
                    if receipt.get(key) != q.get(key):
                        errors.append(f"{label}.question_receipts[{question_index}] {key} contradicts state question")
                source_calls = [
                    call for call in call_values if call.get("call_id") == q.get("call_id")
                ]
                if len(source_calls) != 1:
                    errors.append(f"{label}.question_receipts[{question_index}] does not bind one question-producing call")
                elif (
                    source_calls[0].get("outcome") != "question"
                    or source_calls[0].get("output", {}).get("sha256") != receipt.get("question_sha256")
                ):
                    errors.append(f"{label}.question_receipts[{question_index}] source call is not the sealed question")
                else:
                    source_time = _timestamp(
                        source_calls[0].get("ledger_call", {}).get("ts"),
                        f"{label}.question_receipts[{question_index}] source call ts", errors,
                    )
                    asked_time = _timestamp(
                        receipt.get("asked_at"),
                        f"{label}.question_receipts[{question_index}] asked_at", errors,
                    )
                    if source_time is not None and asked_time is not None and asked_time < source_time:
                        errors.append(f"{label}.question_receipts[{question_index}] predates its question-producing call")
            asked = _timestamp(receipt.get("asked_at"), f"{label}.question_receipts[{question_index}].asked_at", errors)
            answered = _timestamp(receipt.get("answered_at"), f"{label}.question_receipts[{question_index}].answered_at", errors)
            if asked is not None and answered is not None and asked > answered:
                errors.append(f"{label}.question_receipts[{question_index}] answer precedes question")
            question_values.append(receipt)
        answered_questions = [q for q in state_questions if isinstance(q, dict) and q.get("answer") is not None]
        if sorted(q.get("question_id") for q in answered_questions) != sorted(q.get("question_id") for q in question_values):
            errors.append(f"{label} answered questions and question receipts are not bidirectionally complete")
        if isinstance(state, dict) and state.get("question_receipts") != question_values:
            errors.append(f"{label} state question receipts do not equal sealed artifacts in order")
        if arm != "arm_c" and question_artifacts:
            errors.append(f"{label} non-Arm-C run cannot carry question receipts")

    seal_artifact = _artifact(root, run.get("arm_seal"), f"{label}.arm_seal", errors)
    seal = _json_artifact_object(seal_artifact, f"{label}.arm_seal", errors)
    seal_fields = {
        "schema", "task_id", "arm", "base_commit", "sequence", "position", "sealed_at",
        "final_state", "protocol_valid", "composition_state_sha256",
        "question_receipt_sha256s", "driver_trace_sha256",
    }
    if seal is not None and _exact_fields(seal, seal_fields, f"{label}.arm_seal payload", errors):
        frozen = {key: run.get(key) for key in ("task_id", "arm", "base_commit", "sequence", "position", "sealed_at", "final_state", "protocol_valid")}
        frozen.update({
            "schema": ARM_SEAL_SCHEMA,
            "composition_state_sha256": state_artifact[1] if state_artifact else None,
            "question_receipt_sha256s": sorted(question_hashes),
            "driver_trace_sha256": driver_trace_sha,
        })
        for key, expected in frozen.items():
            if seal.get(key) != expected:
                errors.append(f"{label}.arm_seal payload {key} does not bind exact final evidence")

    ledger_artifact = _artifact(root, run.get("ledger"), f"{label}.ledger", errors)
    calls: list[dict[str, Any]] = []
    if ledger_artifact is not None:
        calls = _load_ledger(ledger_artifact[0], f"{label}.ledger", errors)
        expected_calls = [receipt.get("ledger_call") for receipt in call_values]
        if calls != expected_calls:
            errors.append(f"{label} ledger rows do not equal sealed call receipts in order")
        seen_dispatches: list[str] = []
        previous_call_time: datetime | None = None
        for call_index, call in enumerate(calls):
            call_label = f"{label}.ledger[{call_index}]"
            if set(call) != CALL_FIELDS:
                errors.append(f"{call_label} fields do not match ledger.Call")
                continue
            if call.get("task_id") != task_id or call.get("phase") != arm:
                errors.append(f"{call_label} task_id/phase differs from the arm coordinate")
            extra = call.get("extra")
            if not isinstance(extra, dict):
                errors.append(f"{call_label}.extra must be an object")
                continue
            dispatch_hash = extra.get("dispatch_receipt_sha256")
            if dispatch_hash not in dispatch_hashes:
                errors.append(f"{call_label} names no frozen dispatch receipt")
            elif dispatch_hash in seen_dispatches:
                errors.append(f"{call_label} reuses a dispatch receipt")
            else:
                seen_dispatches.append(dispatch_hash)
            if extra.get("backend_manifest_sha256") != plan["backend_manifest_sha256"]:
                errors.append(f"{call_label} backend manifest hash drifted")
            if extra.get("cost_basis") not in COST_BASES:
                errors.append(f"{call_label} has an invalid cost_basis")
            call_time = _timestamp(call.get("ts"), f"{call_label}.ts", errors)
            if call_time is not None:
                if previous_call_time is not None and call_time < previous_call_time:
                    errors.append(f"{label} ledger calls are not chronological")
                if sealed_at is not None and call_time > sealed_at:
                    errors.append(f"{call_label} occurred after the arm seal")
                if authorization_time is not None and call_time < authorization_time:
                    errors.append(f"{call_label} occurred before operator authorization")
                previous_call_time = call_time
            cost = call.get("cost_usd")
            if (
                not isinstance(cost, (int, float))
                or isinstance(cost, bool)
                or not math.isfinite(float(cost))
                or cost < 0
            ):
                errors.append(f"{call_label}.cost_usd must be non-negative")
        if sorted(seen_dispatches) != sorted(dispatch_hashes):
            errors.append(f"{label} dispatch/ledger completeness is not bidirectional")
    return coordinate, calls, sealed_at, question_values, state


def _validate_costs(
    calls: list[dict[str, Any]], reconciliation: Any, plan: dict[str, Any],
    root: Path, errors: list[str]
) -> None:
    if not isinstance(reconciliation, list):
        errors.append("cost_reconciliation must be an array")
        return
    records: dict[str, dict[str, Any]] = {}
    fields = {"account", "billed_usd", "bill", "provider_artifact"}
    for index, record in enumerate(reconciliation):
        label = f"cost_reconciliation[{index}]"
        if not _exact_fields(record, fields, label, errors):
            continue
        account = record.get("account")
        billed = record.get("billed_usd")
        if not isinstance(account, str) or not account:
            errors.append(f"{label}.account must be non-empty")
            continue
        if account in records:
            errors.append(f"duplicate cost reconciliation account {account!r}")
        billed_valid = (
            isinstance(billed, (int, float))
            and not isinstance(billed, bool)
            and math.isfinite(float(billed))
            and billed >= 0
        )
        if not billed_valid:
            errors.append(f"{label}.billed_usd must be non-negative")
        bill_artifact = _artifact(root, record.get("bill"), f"{label}.bill", errors)
        provider_artifact = _artifact(
            root, record.get("provider_artifact"), f"{label}.provider_artifact", errors
        )
        bill = _json_artifact_object(bill_artifact, f"{label}.bill", errors)
        if bill is not None and _exact_fields(
            bill, {"schema", "account", "currency", "period", "total_usd", "provider_artifact_sha256"},
            f"{label}.bill payload", errors,
        ):
            if bill.get("schema") != "tier-bench/tier-pilot-bill@1":
                errors.append(f"{label}.bill schema is invalid")
            if bill.get("account") != account or bill.get("currency") != "USD":
                errors.append(f"{label}.bill account/currency mismatch")
            if bill.get("total_usd") != billed:
                errors.append(f"{label}.billed_usd does not equal the opened bill")
            provider_sha = bill.get("provider_artifact_sha256")
            if not _is_hex(provider_sha, HEX64):
                errors.append(f"{label}.bill provider_artifact_sha256 must be non-null sha256")
            elif provider_artifact is None or provider_artifact[1] != provider_sha:
                errors.append(f"{label}.bill does not bind the opened raw provider artifact")
        if billed_valid and bill is not None and provider_artifact is not None:
            records[account] = record
    real: dict[str, float] = {}
    for call in calls:
        extra = call.get("extra")
        if isinstance(extra, dict) and extra.get("cost_basis") == "real-billed":
            account = call.get("account")
            if isinstance(account, str):
                real[account] = real.get(account, 0.0) + float(call.get("cost_usd", 0))
    if set(records) != set(real):
        errors.append(
            "real-billed reconciliation accounts must exactly match real-billed ledger accounts"
        )
    for account, total in real.items():
        record = records.get(account)
        if record is None:
            continue
        billed = float(record["billed_usd"])
        tolerance = float(plan["real_billed_tolerance_fraction"])
        denominator = max(abs(billed), 0.01)
        if abs(total - billed) / denominator > tolerance:
            errors.append(
                f"real-billed account {account!r} does not reconcile: "
                f"ledger={total:.8f}, billed={billed:.8f}"
            )


def _validate_audits(
    audits: Any,
    seed: bytes | None,
    plan: dict[str, Any],
    tasks: dict[str, dict[str, Any]],
    unvoided: set[str],
    sealed: dict[tuple[str, str], datetime | None],
    root: Path,
    as_of: datetime,
    errors: list[str],
) -> set[str]:
    if not isinstance(audits, list):
        errors.append("audits must be an array")
        return set()
    fields = {
        "task_id", "final_arm_sealed_at", "followup_closes_at", "scores",
        "scores_sha256", "scores_sealed_at", "unblinded_at", "label_map",
        "withheld_audit",
    }
    score_fields = {
        "opaque_label", "repository_ci", "scope_ok", "operator_accepted",
        "escaped_defects",
    }
    seen: set[str] = set()
    for index, audit in enumerate(audits):
        label = f"audits[{index}]"
        if not _exact_fields(audit, fields, label, errors):
            continue
        task_id = audit.get("task_id")
        if task_id not in unvoided:
            errors.append(f"{label}.task_id is voided or absent from the plan")
            continue
        if task_id in seen:
            errors.append(f"duplicate audit for task {task_id!r}")
            continue
        seen.add(task_id)
        audit_artifact = _artifact(
            root, audit.get("withheld_audit"), f"{label}.withheld_audit", errors
        )
        if (
            audit_artifact is not None
            and audit_artifact[1] != tasks[task_id]["withheld_audit_sha256"]
        ):
            errors.append(f"{label}.withheld_audit does not open the task commitment")
        final = _timestamp(audit.get("final_arm_sealed_at"), f"{label}.final_arm_sealed_at", errors)
        closes = _timestamp(audit.get("followup_closes_at"), f"{label}.followup_closes_at", errors)
        scores_sealed = _timestamp(
            audit.get("scores_sealed_at"), f"{label}.scores_sealed_at", errors
        )
        unblinded = _timestamp(audit.get("unblinded_at"), f"{label}.unblinded_at", errors)
        arm_times = [sealed.get((task_id, arm)) for arm in ARMS]
        if all(value is not None for value in arm_times):
            expected_final = max(value for value in arm_times if value is not None)
            if final != expected_final:
                errors.append(f"{label}.final_arm_sealed_at is not the last arm seal")
        if final is not None and closes != final + timedelta(days=FOLLOW_UP_DAYS):
            errors.append(f"{label}.followup_closes_at must be exactly 14 days after final seal")
        if closes is not None and scores_sealed is not None and scores_sealed < closes:
            errors.append(f"{label}.scores were sealed before the follow-up window closed")
        if scores_sealed is not None and unblinded is not None and unblinded < scores_sealed:
            errors.append(f"{label} was unblinded before scores were sealed")
        if closes is not None and as_of < closes:
            errors.append(f"{label} follow-up window is still open")
        if unblinded is not None and as_of < unblinded:
            errors.append(f"{label}.unblinded_at is in the future")

        label_map = audit.get("label_map")
        if not isinstance(label_map, dict) or set(label_map) != set(ARMS):
            errors.append(f"{label}.label_map must contain exactly arm_a/arm_b/arm_c")
            expected_labels: dict[str, str] = {}
        elif seed is None:
            expected_labels = {}
        else:
            expected_labels = {
                arm: audit_label(seed, plan["pilot_id"], task_id, arm) for arm in ARMS
            }
            if label_map != expected_labels:
                errors.append(f"{label}.label_map does not match the committed seed")
        scores = audit.get("scores")
        if not isinstance(scores, list) or len(scores) != 3:
            errors.append(f"{label}.scores must contain exactly three opaque scores")
            continue
        score_labels: list[str] = []
        for score_index, score in enumerate(scores):
            score_label = f"{label}.scores[{score_index}]"
            if not _exact_fields(score, score_fields, score_label, errors):
                continue
            opaque = score.get("opaque_label")
            if not isinstance(opaque, str) or not opaque:
                errors.append(f"{score_label}.opaque_label must be non-empty")
            else:
                score_labels.append(opaque)
            for key in ("repository_ci", "scope_ok", "operator_accepted"):
                if not isinstance(score.get(key), bool):
                    errors.append(f"{score_label}.{key} must be boolean")
            defects = score.get("escaped_defects")
            if not isinstance(defects, int) or isinstance(defects, bool) or defects < 0:
                errors.append(f"{score_label}.escaped_defects must be a non-negative integer")
        if expected_labels and sorted(score_labels) != sorted(expected_labels.values()):
            errors.append(f"{label}.scores do not cover the three committed opaque labels")
        if score_labels != sorted(score_labels):
            errors.append(f"{label}.scores must be ordered by opaque_label before sealing")
        expected_scores_hash = sha256_bytes(canonical_json(scores))
        if audit.get("scores_sha256") != expected_scores_hash:
            errors.append(f"{label}.scores_sha256 does not bind the canonical scores")
    if seen != unvoided:
        errors.append("audits must cover every and only unvoided task")
    return seen


def _validate_audits_v2(
    audits: Any,
    seed: bytes | None,
    plan: dict[str, Any],
    tasks: dict[str, dict[str, Any]],
    unvoided: set[str],
    sealed: dict[tuple[str, str], datetime | None],
    seal_hashes: dict[tuple[str, str], str],
    terminal_states: dict[tuple[str, str], dict[str, Any]],
    intervals: dict[str, tuple[dict[str, Any], dict[str, Any]]],
    used_operator_intervals: set[str],
    root: Path,
    as_of: datetime,
    errors: list[str],
) -> tuple[set[str], str | None]:
    if not isinstance(audits, list):
        errors.append("audits must be an array")
        return set(), None
    row_fields = {
        "task_id", "final_arm_sealed_at", "followup_closes_at", "withheld_audit",
        "normalized_inputs", "score_commitment", "mapping_reveal",
    }
    score_fields = {
        "opaque_label", "repository_ci", "scope_ok", "operator_accepted", "escaped_defects",
    }
    seen: set[str] = set()
    score_commits: set[str] = set()
    for index, row in enumerate(audits):
        label = f"audits[{index}]"
        if not _exact_fields(row, row_fields, label, errors):
            continue
        task_id = row.get("task_id")
        if task_id not in unvoided or task_id in seen:
            errors.append(f"{label}.task_id is voided, absent, or duplicated")
            continue
        seen.add(task_id)
        withheld = _artifact(root, row.get("withheld_audit"), f"{label}.withheld_audit", errors)
        if withheld is not None and withheld[1] != tasks[task_id]["withheld_audit_sha256"]:
            errors.append(f"{label}.withheld_audit does not open the task commitment")
        final = _timestamp(row.get("final_arm_sealed_at"), f"{label}.final_arm_sealed_at", errors)
        closes = _timestamp(row.get("followup_closes_at"), f"{label}.followup_closes_at", errors)
        arm_times = [sealed.get((task_id, arm)) for arm in ARMS]
        if all(value is not None for value in arm_times):
            expected_final = max(value for value in arm_times if value is not None)
            if final != expected_final:
                errors.append(f"{label}.final_arm_sealed_at is not the last arm seal")
        if final is not None and closes != final + timedelta(days=FOLLOW_UP_DAYS):
            errors.append(f"{label}.followup_closes_at must be exactly 14 days after final seal")
        if closes is not None and as_of < closes:
            errors.append(f"{label} follow-up window is still open")

        normalized_artifact = _git_artifact(root, row.get("normalized_inputs"), f"{label}.normalized_inputs", errors)
        score_artifact = _git_artifact(root, row.get("score_commitment"), f"{label}.score_commitment", errors)
        reveal_artifact = _git_artifact(root, row.get("mapping_reveal"), f"{label}.mapping_reveal", errors)
        normalized = _json_artifact_object(
            (normalized_artifact[0], normalized_artifact[1]) if normalized_artifact else None,
            f"{label}.normalized_inputs", errors,
        )
        score = _json_artifact_object(
            (score_artifact[0], score_artifact[1]) if score_artifact else None,
            f"{label}.score_commitment", errors,
        )
        reveal = _json_artifact_object(
            (reveal_artifact[0], reveal_artifact[1]) if reveal_artifact else None,
            f"{label}.mapping_reveal", errors,
        )
        normalized_labels: list[str] = []
        normalized_entries: dict[str, tuple[dict[str, Any], tuple[Path, str] | None]] = {}
        if normalized is not None and _exact_fields(
            normalized, {"schema", "pilot_id", "task_id", "profile_sha256", "entries"},
            f"{label}.normalized_inputs payload", errors,
        ):
            if normalized.get("schema") != "tier-bench/tier-pilot-audit-inputs@1":
                errors.append(f"{label}.normalized_inputs schema is invalid")
            bindings = {
                "pilot_id": plan["pilot_id"], "task_id": task_id,
                "profile_sha256": plan["audit_normalization_profile"]["sha256"],
            }
            for key, frozen in bindings.items():
                if normalized.get(key) != frozen:
                    errors.append(f"{label}.normalized_inputs {key} drifted")
            entries = normalized.get("entries")
            if not isinstance(entries, list) or len(entries) != 3:
                errors.append(f"{label}.normalized_inputs must contain three entries")
            else:
                for entry_index, entry in enumerate(entries):
                    if not _exact_fields(
                        entry,
                        {"opaque_label", "artifact"},
                        f"{label}.normalized_inputs.entries[{entry_index}]", errors,
                    ):
                        continue
                    opaque = entry.get("opaque_label")
                    if not isinstance(opaque, str):
                        errors.append(f"{label}.normalized_inputs.entries[{entry_index}].opaque_label must be a string")
                        continue
                    normalized_labels.append(opaque)
                    artifact = _artifact(
                        root, entry.get("artifact"),
                        f"{label}.normalized_inputs.entries[{entry_index}].artifact", errors,
                    )
                    normalized_entries[opaque] = (entry, artifact)
                if normalized_labels != sorted(normalized_labels) or len(set(normalized_labels)) != 3:
                    errors.append(f"{label}.normalized_inputs labels must be unique and sorted")

        score_labels: list[str] = []
        scores_by_label: dict[str, dict[str, Any]] = {}
        score_time: datetime | None = None
        if score is not None and _exact_fields(
            score, {"schema", "pilot_id", "task_id", "normalized_inputs_sha256", "scores", "sealed_at"},
            f"{label}.score_commitment payload", errors,
        ):
            if score.get("schema") != "tier-bench/tier-pilot-audit-scores@1":
                errors.append(f"{label}.score_commitment schema is invalid")
            bindings = {
                "pilot_id": plan["pilot_id"], "task_id": task_id,
                "normalized_inputs_sha256": normalized_artifact[1] if normalized_artifact else None,
            }
            for key, frozen in bindings.items():
                if score.get(key) != frozen:
                    errors.append(f"{label}.score_commitment {key} drifted")
            scores = score.get("scores")
            if not isinstance(scores, list) or len(scores) != 3:
                errors.append(f"{label}.score_commitment must contain three scores")
            else:
                for score_index, item in enumerate(scores):
                    if not _exact_fields(item, score_fields, f"{label}.score_commitment.scores[{score_index}]", errors):
                        continue
                    score_labels.append(item.get("opaque_label"))
                    if isinstance(item.get("opaque_label"), str):
                        scores_by_label[item["opaque_label"]] = item
                if score_labels != sorted(score_labels) or score_labels != normalized_labels:
                    errors.append(f"{label}.score labels do not exactly match normalized inputs")
            score_time = _timestamp(score.get("sealed_at"), f"{label}.score_commitment.sealed_at", errors)
            if score_artifact is not None:
                score_commits.add(score_artifact[2]["commit_oid"])
            if closes is not None and score_time is not None and score_time < closes:
                errors.append(f"{label}.scores were sealed before the follow-up window closed")

        if reveal is not None and _exact_fields(
            reveal, {"schema", "pilot_id", "task_id", "score_commitment_sha256", "seed_hex", "label_map", "revealed_at"},
            f"{label}.mapping_reveal payload", errors,
        ):
            if reveal.get("schema") != "tier-bench/tier-pilot-audit-reveal@1":
                errors.append(f"{label}.mapping_reveal schema is invalid")
            for key, frozen in {
                "pilot_id": plan["pilot_id"], "task_id": task_id,
                "score_commitment_sha256": score_artifact[1] if score_artifact else None,
                "seed_hex": seed.hex() if seed is not None else None,
            }.items():
                if reveal.get(key) != frozen:
                    errors.append(f"{label}.mapping_reveal {key} drifted")
            label_map = reveal.get("label_map")
            if not isinstance(label_map, dict) or set(label_map) != set(ARMS):
                errors.append(f"{label}.mapping_reveal must map exactly A/B/C")
            elif seed is not None:
                for arm in ARMS:
                    binding = label_map.get(arm)
                    if not isinstance(binding, dict) or set(binding) != {"opaque_label", "source_seal_sha256"}:
                        errors.append(f"{label}.mapping_reveal.{arm} shape is invalid")
                        continue
                    if binding.get("opaque_label") != audit_label(seed, plan["pilot_id"], task_id, arm):
                        errors.append(f"{label}.mapping_reveal.{arm} label does not match committed seed")
                    if binding.get("source_seal_sha256") != seal_hashes.get((task_id, arm)):
                        errors.append(f"{label}.mapping_reveal.{arm} does not bind the actual arm seal")
                    state = terminal_states.get((task_id, arm))
                    normalized_entry = normalized_entries.get(binding.get("opaque_label"))
                    if state is None or normalized_entry is None:
                        errors.append(f"{label}.mapping_reveal.{arm} has no replayed normalized source")
                    else:
                        _, artifact = normalized_entry
                        try:
                            expected_normalized = canonical_json(audit_normalized_payload(
                                plan["pilot_id"], task_id, binding["opaque_label"],
                                plan["audit_normalization_profile"]["sha256"], state,
                            ))
                        except PilotError as exc:
                            errors.append(f"{label}.normalized_inputs cannot derive {arm}: {exc}")
                        else:
                            if artifact is None or artifact[0].read_bytes() != expected_normalized:
                                errors.append(f"{label}.normalized_inputs artifact is not the built-in projection for {arm}")
                    score_item = scores_by_label.get(binding.get("opaque_label"))
                    if isinstance(score_item, dict) and score_item.get("operator_accepted") is True:
                        matches = [
                            (iid, pair) for iid, pair in intervals.items()
                            if pair[0].get("task_id") == task_id
                            and pair[0].get("arm") == arm
                            and pair[0].get("category") in {"acceptance", "review"}
                            and pair[0].get("reference_id") == binding.get("opaque_label")
                        ]
                        if len(matches) != 1:
                            errors.append(f"{label}.mapping_reveal.{arm} operator acceptance lacks exactly one timed intervention")
                        else:
                            iid, (_, stop_event) = matches[0]
                            used_operator_intervals.add(iid)
                            stop_time = _timestamp(stop_event.get("ts"), f"{label}.mapping_reveal.{arm} intervention stop", errors)
                            if score_time is not None and stop_time is not None and stop_time > score_time:
                                errors.append(f"{label}.mapping_reveal.{arm} operator acceptance occurred after score sealing")
            reveal_time = _timestamp(reveal.get("revealed_at"), f"{label}.mapping_reveal.revealed_at", errors)
            if score_time is not None and reveal_time is not None and reveal_time < score_time:
                errors.append(f"{label}.mapping_reveal precedes sealed scores")

        if normalized_artifact and score_artifact and reveal_artifact:
            n_commit = normalized_artifact[2]["commit_oid"]
            s_commit = score_artifact[2]["commit_oid"]
            r_commit = reveal_artifact[2]["commit_oid"]
            if n_commit == s_commit or not _git_is_ancestor(root, n_commit, s_commit):
                errors.append(f"{label} normalized inputs were not committed before scores")
            if s_commit == r_commit or not _git_is_ancestor(root, s_commit, r_commit):
                errors.append(f"{label} scores were not committed before mapping reveal")
            reveal_path = reveal_artifact[2]["path"]
            reveal_blob = reveal_artifact[2]["blob_oid"]
            if _git_path_exists(root, s_commit, reveal_path):
                errors.append(f"{label} mapping reveal path already existed at score commit")
            if _git_blob_exists(root, s_commit, reveal_blob):
                errors.append(f"{label} exact mapping reveal bytes already existed at score commit")
    if seen != unvoided:
        errors.append("audits must cover every and only unvoided task")
    if unvoided and len(score_commits) != 1:
        errors.append("all unvoided score artifacts must share one common score commit")
    return seen, next(iter(score_commits)) if len(score_commits) == 1 else None


def validate_evidence(
    plan: dict[str, Any],
    plan_raw: bytes,
    evidence: Any,
    evidence_root: Path,
    *,
    as_of: datetime,
) -> tuple[list[str], dict[str, Any]]:
    errors = validate_plan(plan)
    fields = {
        "schema", "pilot_id", "plan_sha256", "backend_manifest",
        "intervention_log", "arm_runs", "voids", "audit_seed_reveal_hex",
        "audits", "cost_reconciliation", "operator_authorization",
    }
    if not _exact_fields(evidence, fields, "evidence", errors):
        return errors, {}
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        errors.append(f"evidence.schema must be {EVIDENCE_SCHEMA}")
    if evidence.get("pilot_id") != plan.get("pilot_id"):
        errors.append("evidence.pilot_id differs from the plan")
    if evidence.get("plan_sha256") != sha256_bytes(plan_raw):
        errors.append("evidence.plan_sha256 does not bind the exact plan bytes")
    manifest_artifact = _artifact(
        evidence_root, evidence.get("backend_manifest"), "backend_manifest", errors
    )
    manifest = _load_composition_manifest(manifest_artifact, plan, errors) or {}
    composition: PilotComposition | None = None
    if manifest_artifact is not None:
        try:
            composition = load_pilot_composition(manifest_artifact[0])
        except (ManifestError, OSError) as exc:
            errors.append(f"backend_manifest fails the production composition contract: {exc}")
    authorization_time: datetime | None = None
    authorization_artifact = _git_artifact(
        evidence_root,
        evidence.get("operator_authorization"),
        "operator_authorization",
        errors,
    )
    if authorization_artifact is not None:
        try:
            authorization = json.loads(authorization_artifact[0].read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            errors.append("operator_authorization is invalid JSON")
        else:
            authorization_fields = {
                "schema", "pilot_id", "plan_sha256", "backend_manifest_sha256",
                "protocol_commit", "authority", "authorized", "ratified_at",
            }
            if _exact_fields(
                authorization, authorization_fields, "operator_authorization payload", errors
            ):
                if authorization.get("schema") != "tier-bench/tier-pilot-authorization@1":
                    errors.append("operator_authorization payload schema is invalid")
                bindings = {
                    "pilot_id": plan.get("pilot_id"),
                    "plan_sha256": sha256_bytes(plan_raw),
                    "backend_manifest_sha256": plan.get("backend_manifest_sha256"),
                    "protocol_commit": plan.get("protocol_commit"),
                    "authority": "operator",
                    "authorized": True,
                }
                for key, expected in bindings.items():
                    if authorization.get(key) != expected:
                        errors.append(f"operator_authorization payload {key} is not ratified")
                declared_authorization_time = _timestamp(
                    authorization.get("ratified_at"),
                    "operator_authorization payload ratified_at",
                    errors,
                )
                ratification_commit = authorization_artifact[2]["commit_oid"]
                anchor_commit = authorization_artifact[2]["anchor_commit_oid"]
                commit_time_result = subprocess.run(
                    ["git", "-C", str(evidence_root), "show", "-s", "--format=%cI", ratification_commit],
                    capture_output=True, text=True,
                )
                authorization_time = _timestamp(
                    commit_time_result.stdout.strip() if commit_time_result.returncode == 0 else None,
                    "operator_authorization ratification commit time", errors,
                )
                if declared_authorization_time != authorization_time:
                    errors.append("operator_authorization ratified_at differs from its commit time")
                for task in plan.get("tasks", []):
                    base = task.get("base_commit") if isinstance(task, dict) else None
                    if isinstance(base, str) and not _git_is_ancestor(evidence_root, base, ratification_commit):
                        errors.append("a task base is not an ancestor of the ratification commit")
                branch = subprocess.run(
                    ["git", "-C", str(evidence_root), "rev-parse", plan.get("default_branch", "")],
                    capture_output=True, text=True,
                )
                branch_head = branch.stdout.strip() if branch.returncode == 0 else ""
                if not branch_head or not _git_is_ancestor(evidence_root, anchor_commit, branch_head):
                    errors.append("authorization anchor is not in pinned default-branch custody")
                remote = subprocess.run(
                    ["git", "-C", str(evidence_root), "remote", "get-url", "origin"],
                    capture_output=True, text=True,
                )
                if remote.returncode or remote.stdout.strip() != plan.get("target_remote"):
                    errors.append("target repository origin does not match the frozen plan")

    profile = _artifact(
        evidence_root, plan.get("audit_normalization_profile"),
        "audit_normalization_profile", errors,
    )
    profile_value = _json_artifact_object(profile, "audit_normalization_profile", errors)
    if profile_value is not None and _exact_fields(
        profile_value, {"schema", "normalizer"},
        "audit_normalization_profile payload", errors,
    ):
        expected_profile = {
            "schema": AUDIT_PROFILE_SCHEMA,
            "normalizer": AUDIT_NORMALIZATION_ALGORITHM,
        }
        if profile_value != expected_profile:
            errors.append("audit_normalization_profile is not the built-in supported algorithm")
    intervention = evidence.get("intervention_log")
    intervention_fields = {"path", "sha256", "head_sha256"}
    events: list[dict[str, Any]] = []
    if _exact_fields(intervention, intervention_fields, "intervention_log", errors):
        if intervention.get("path") != plan.get("intervention_log_path"):
            errors.append("intervention_log.path differs from the canonical plan path")
        artifact = _artifact(
            evidence_root,
            {"path": intervention.get("path"), "sha256": intervention.get("sha256")},
            "intervention_log",
            errors,
        )
        if artifact is not None:
            try:
                events = validate_events(artifact[0])
            except InterventionError as exc:
                errors.append(f"intervention log invalid: {exc}")
            expected_head = events[-1]["event_sha256"] if events else None
            if intervention.get("head_sha256") != expected_head:
                errors.append("intervention_log.head_sha256 does not match the event chain")

    tasks = {task["task_id"]: task for task in plan.get("tasks", []) if isinstance(task, dict)}
    for event_index, event in enumerate(events):
        if event.get("task_id") not in tasks or event.get("arm") not in ARMS:
            errors.append(f"intervention event {event_index} is outside the frozen task/arm set")

    void_rows = evidence.get("voids")
    voided: set[str] = set()
    if not isinstance(void_rows, list):
        errors.append("voids must be an array")
    else:
        for index, row in enumerate(void_rows):
            label = f"voids[{index}]"
            if not isinstance(row, dict):
                errors.append(f"{label} must be an object")
                continue
            task_id = row.get("task_id")
            if task_id not in tasks:
                errors.append(f"{label}.task_id is not in the frozen plan")
            elif task_id in voided:
                errors.append(f"duplicate void for task {task_id!r}")
            else:
                voided.add(task_id)
            if row.get("reason_code") not in VOID_REASONS:
                errors.append(f"{label}.reason_code is invalid")
            if row.get("authority") not in {"derived", "ratified"}:
                errors.append(f"{label}.authority must be derived or ratified")

    arm_rows = evidence.get("arm_runs")
    coordinates: set[tuple[str, str]] = set()
    all_calls: list[dict[str, Any]] = []
    sealed: dict[tuple[str, str], datetime | None] = {}
    seal_hashes: dict[tuple[str, str], str] = {}
    protocol_invalid_tasks: set[str] = set()
    all_dispatch_hashes: set[str] = set()
    all_question_receipts: list[dict[str, Any]] = []
    terminal_states: dict[tuple[str, str], dict[str, Any]] = {}
    if not isinstance(arm_rows, list):
        errors.append("arm_runs must be an array")
    else:
        previous_sequence = 0
        previous_sealed_at: datetime | None = None
        for index, row in enumerate(arm_rows):
            coordinate, calls, sealed_at, questions, terminal_state = _validate_arm_run(
                row, index, tasks, plan, manifest, composition,
                evidence_root, authorization_time, errors
            )
            if coordinate is not None:
                if coordinate in coordinates:
                    errors.append(f"duplicate arm run coordinate {coordinate}")
                coordinates.add(coordinate)
                sealed[coordinate] = sealed_at
                seal_value = row.get("arm_seal") if isinstance(row, dict) else None
                if isinstance(seal_value, dict) and isinstance(seal_value.get("sha256"), str):
                    seal_hashes[coordinate] = seal_value["sha256"]
                if row.get("protocol_valid") is False and coordinate[0] in tasks:
                    protocol_invalid_tasks.add(coordinate[0])
                if terminal_state is not None:
                    terminal_states[coordinate] = terminal_state
            sequence = row.get("sequence") if isinstance(row, dict) else None
            if not isinstance(sequence, int) or isinstance(sequence, bool):
                errors.append(f"arm_runs[{index}].sequence must be an integer")
            elif sequence <= previous_sequence:
                errors.append("arm_runs must be recorded in strictly increasing schedule order")
            else:
                previous_sequence = sequence
            if (
                sealed_at is not None
                and previous_sealed_at is not None
                and sealed_at < previous_sealed_at
            ):
                errors.append("arm run seal times are out of frozen schedule order")
            if sealed_at is not None:
                previous_sealed_at = sealed_at
            for call in calls:
                extra = call.get("extra")
                dispatch_hash = (
                    extra.get("dispatch_receipt_sha256")
                    if isinstance(extra, dict)
                    else None
                )
                if isinstance(dispatch_hash, str):
                    if dispatch_hash in all_dispatch_hashes:
                        errors.append("a dispatch receipt is reused across arm runs")
                    all_dispatch_hashes.add(dispatch_hash)
            all_calls.extend(calls)
            all_question_receipts.extend(questions)
    ratified_void_commits: list[tuple[str, str]] = []
    if protocol_invalid_tasks - voided:
        errors.append("every protocol-invalid arm must atomically void its whole task")
    for index, row in enumerate(void_rows or []):
        if not isinstance(row, dict):
            continue
        label = f"voids[{index}]"
        if row.get("authority") == "derived":
            if set(row) != {"task_id", "authority", "reason_code", "trigger_refs"}:
                errors.append(f"{label} derived void fields mismatch")
            # Only predicates attributable without suppressing unrelated validator
            # errors are admitted in v1: a missing arm coordinate or an explicitly
            # protocol-invalid final seal. Other codes require ratification.
            task_id = row.get("task_id")
            actual = {coordinate for coordinate in coordinates if coordinate[0] == task_id}
            missing_arm = actual != {(task_id, arm) for arm in ARMS}
            invalid_arm = task_id in protocol_invalid_tasks
            refs = row.get("trigger_refs")
            if row.get("reason_code") != "other_protocol_fault" or not (missing_arm or invalid_arm):
                errors.append(f"{label} reason/predicate mismatch for derived void")
            if not isinstance(refs, list) or not refs:
                errors.append(f"{label}.trigger_refs must name the reproduced predicate")
        elif row.get("authority") == "ratified":
            if set(row) != {"task_id", "authority", "reason_code", "evidence_refs", "ratification"}:
                errors.append(f"{label} ratified void fields mismatch")
                continue
            refs = row.get("evidence_refs")
            evidence_hashes: list[str] = []
            if not isinstance(refs, list) or not refs:
                errors.append(f"{label}.evidence_refs must be non-empty")
            else:
                for ref_index, ref in enumerate(refs):
                    artifact = _artifact(evidence_root, ref, f"{label}.evidence_refs[{ref_index}]", errors)
                    if artifact is not None:
                        evidence_hashes.append(artifact[1])
            ratified = _git_artifact(evidence_root, row.get("ratification"), f"{label}.ratification", errors)
            if ratified is not None:
                ratified_void_commits.append((label, ratified[2]["commit_oid"]))
            payload = _json_artifact_object(
                (ratified[0], ratified[1]) if ratified else None, f"{label}.ratification", errors
            )
            payload_fields = {
                "schema", "pilot_id", "plan_sha256", "task_id", "reason_code",
                "evidence_sha256s", "arm_seal_sha256s",
            }
            if payload is not None and _exact_fields(payload, payload_fields, f"{label}.ratification payload", errors):
                task_id = row.get("task_id")
                expected_seals = sorted(
                    seal_hashes.get((task_id, arm)) for arm in ARMS
                    if seal_hashes.get((task_id, arm)) is not None
                )
                expected = {
                    "schema": "tier-bench/tier-pilot-void-ratification@1",
                    "pilot_id": plan["pilot_id"], "plan_sha256": sha256_bytes(plan_raw),
                    "task_id": task_id, "reason_code": row.get("reason_code"),
                    "evidence_sha256s": sorted(evidence_hashes),
                    "arm_seal_sha256s": expected_seals,
                }
                for key, frozen in expected.items():
                    if payload.get(key) != frozen:
                        errors.append(f"{label}.ratification {key} does not bind exact void evidence")
                if len(expected_seals) != 3:
                    errors.append(f"{label} ratified void must bind all three arm seals")
    sealed_times = [value for value in sealed.values() if value is not None]
    call_times: list[datetime] = []
    session_ids: set[str] = set()
    for call_index, call in enumerate(all_calls):
        call_time = _timestamp(call.get("ts"), f"ledger call {call_index}.ts", errors)
        if call_time is not None:
            call_times.append(call_time)
        extra = call.get("extra")
        session_id = extra.get("session_id") if isinstance(extra, dict) else None
        if not isinstance(session_id, str) or not session_id:
            errors.append(f"ledger call {call_index} has no fresh session identity")
        elif session_id in session_ids:
            errors.append("a model session identity was reused across pilot calls")
        else:
            session_ids.add(session_id)
        if not isinstance(extra, dict) or extra.get("telemetry_complete") is not True:
            errors.append(f"ledger call {call_index} telemetry is incomplete")
    if (
        authorization_time is not None
        and (call_times or sealed_times)
        and authorization_time > min(call_times or sealed_times)
    ):
        errors.append("operator authorization was ratified after pilot execution began")

    intervals: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for event_index in range(0, len(events), 2):
        if event_index + 1 >= len(events):
            break
        start_event, stop_event = events[event_index], events[event_index + 1]
        if start_event.get("event") == "start" and stop_event.get("event") == "stop":
            intervals[start_event["intervention_id"]] = (start_event, stop_event)
    used_question_intervals: set[str] = set()
    for index, receipt in enumerate(all_question_receipts):
        iid = receipt.get("intervention_id")
        interval = intervals.get(iid)
        if interval is None:
            errors.append(f"question receipt {index} has no closed intervention interval")
            continue
        start_event, stop_event = interval
        if (
            start_event.get("task_id") != receipt.get("task_id")
            or start_event.get("arm") != "arm_c"
            or start_event.get("category") != "clarification"
            or start_event.get("reference_id") != receipt.get("question_id")
            or stop_event.get("reference_id") != receipt.get("question_id")
        ):
            errors.append(f"question receipt {index} intervention does not bind its Arm-C question")
        start_time = _timestamp(start_event.get("ts"), f"question interval {index}.start", errors)
        stop_time = _timestamp(stop_event.get("ts"), f"question interval {index}.stop", errors)
        asked = _timestamp(receipt.get("asked_at"), f"question receipt {index}.asked_at", errors)
        answered = _timestamp(receipt.get("answered_at"), f"question receipt {index}.answered_at", errors)
        if all(value is not None for value in (start_time, stop_time, asked, answered)) and not (
            asked <= start_time <= answered <= stop_time
        ):
            errors.append(f"question receipt {index} falls outside its intervention interval")
        if isinstance(iid, str):
            used_question_intervals.add(iid)
    for iid, (start_event, _) in intervals.items():
        if (
            start_event.get("arm") == "arm_c"
            and start_event.get("category") == "clarification"
            and iid not in used_question_intervals
        ):
            errors.append("an Arm-C clarification intervention has no sealed question receipt")
    used_operator_intervals = set(used_question_intervals)
    unvoided = set(tasks) - voided
    for task_id in sorted(unvoided):
        expected = {(task_id, arm) for arm in ARMS}
        actual = {coordinate for coordinate in coordinates if coordinate[0] == task_id}
        if actual != expected:
            errors.append(f"unvoided task {task_id!r} does not have all three arm seals")
        for arm in ARMS:
            matching = [
                row for row in arm_rows or []
                if isinstance(row, dict) and row.get("task_id") == task_id and row.get("arm") == arm
            ]
            if matching and matching[0].get("protocol_valid") is not True:
                errors.append(f"unvoided task {task_id!r} has a protocol-invalid arm")
    _validate_costs(
        all_calls, evidence.get("cost_reconciliation"), plan, evidence_root, errors
    )

    seed_hex = evidence.get("audit_seed_reveal_hex")
    seed: bytes | None = None
    if not isinstance(seed_hex, str) or not re.fullmatch(r"[0-9a-f]{64}", seed_hex):
        errors.append("audit_seed_reveal_hex must be 32 lowercase hex bytes")
    else:
        seed = bytes.fromhex(seed_hex)
        if sha256_bytes(seed) != plan.get("audit_label_seed_commitment_sha256"):
            errors.append("audit seed reveal does not open the frozen commitment")
    audited, common_score_commit = _validate_audits_v2(
        evidence.get("audits"), seed, plan, tasks, unvoided, sealed,
        seal_hashes, terminal_states, intervals, used_operator_intervals,
        evidence_root, as_of, errors
    )
    if unvoided:
        if ratified_void_commits and common_score_commit is None:
            errors.append("ratified voids cannot close without one common unvoided score commit")
        elif common_score_commit is not None:
            for label, ratification_commit in ratified_void_commits:
                if (
                    ratification_commit == common_score_commit
                    or not _git_is_ancestor(evidence_root, ratification_commit, common_score_commit)
                ):
                    errors.append(
                        f"{label}.ratification commit must be a strict ancestor of the common score commit"
                    )
    for iid, (start_event, _) in intervals.items():
        if start_event.get("category") in {"clarification", "review", "rescue", "acceptance"} and iid not in used_operator_intervals:
            errors.append(
                "an output-affecting operator intervention has no sealed causal receipt"
            )
    completed = sorted(task_id for task_id in unvoided if task_id in audited)
    summary = {
        "completed_task_ids": completed,
        "voided_task_ids": sorted(voided),
        "completed_count": len(completed),
    }
    return errors, summary


def close_pilot(
    plan_path: Path,
    evidence_path: Path,
    *,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    plan, plan_raw = load_plan(plan_path)
    evidence_raw = evidence_path.read_bytes()
    try:
        evidence = json.loads(evidence_raw)
    except json.JSONDecodeError as exc:
        raise PilotError(f"invalid pilot evidence JSON: {exc}") from exc
    if as_of is not None and as_of.tzinfo is None:
        raise PilotError("as_of must include a timezone")
    now = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
    errors, summary = validate_evidence(
        plan, plan_raw, evidence, evidence_path.parent, as_of=now
    )
    if errors:
        raise PilotError("pilot closeout refused:\n- " + "\n- ".join(errors))
    completed = summary["completed_count"]
    state = "ADMINISTRATIVELY_COMPLETE" if completed >= 7 else "PARTIAL"
    return {
        "schema": CLOSEOUT_SCHEMA,
        "pilot_id": plan["pilot_id"],
        "administrative_state": state,
        "scientific_verdict_minted": False,
        "feasibility_readout_permitted": completed >= 7,
        "equivalence_claim_permitted": False,
        "noninferiority_claim_permitted": False,
        "tasks_total": 10,
        "completed_tasks": completed,
        "voided_tasks": len(summary["voided_task_ids"]),
        "completed_task_ids": summary["completed_task_ids"],
        "voided_task_ids": summary["voided_task_ids"],
        "no_replacement": True,
        "follow_up_days": FOLLOW_UP_DAYS,
        "plan_sha256": sha256_bytes(plan_raw),
        "evidence_sha256": sha256_bytes(evidence_raw),
        "backend_manifest_sha256": plan["backend_manifest_sha256"],
        "intervention_head_sha256": evidence["intervention_log"]["head_sha256"],
        "ratification_provenance": "local_git_object",
        "exact_ratification_bytes_verified": True,
        "human_identity_authenticated": False,
        "time_authenticated": False,
        "closed_at": now.isoformat().replace("+00:00", "Z"),
    }
