from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import math
from pathlib import Path, PurePosixPath
import re
from typing import Any

from .core import CALL_FIELDS
from .events import InterventionError, validate_events


PLAN_SCHEMA = "tier-bench/tier-pilot-plan@1"
EVIDENCE_SCHEMA = "tier-bench/tier-pilot-evidence@1"
CLOSEOUT_SCHEMA = "tier-bench/tier-pilot-closeout@1"
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
    if not _is_hex(plan.get("protocol_commit"), HEX40):
        errors.append("plan.protocol_commit must be a full lowercase Git SHA")
    if not _is_hex(plan.get("backend_manifest_sha256"), HEX64):
        errors.append("plan.backend_manifest_sha256 must be sha256")
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


def _validate_arm_run(
    run: Any,
    index: int,
    tasks: dict[str, dict[str, Any]],
    plan: dict[str, Any],
    root: Path,
    errors: list[str],
) -> tuple[tuple[str, str] | None, list[dict[str, Any]], datetime | None]:
    label = f"arm_runs[{index}]"
    fields = {
        "task_id", "arm", "sequence", "position", "base_commit", "sealed_at", "final_state",
        "protocol_valid", "seal_sha256", "dispatch_receipts", "ledger",
    }
    if not _exact_fields(run, fields, label, errors):
        return None, [], None
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
    if not _is_hex(run.get("seal_sha256"), HEX64):
        errors.append(f"{label}.seal_sha256 must be sha256")
    sealed_at = _timestamp(run.get("sealed_at"), f"{label}.sealed_at", errors)
    dispatches = run.get("dispatch_receipts")
    dispatch_hashes: list[str] = []
    if not isinstance(dispatches, list) or not dispatches:
        errors.append(f"{label}.dispatch_receipts must be non-empty")
    else:
        for dispatch_index, artifact in enumerate(dispatches):
            result = _artifact(
                root, artifact, f"{label}.dispatch_receipts[{dispatch_index}]", errors
            )
            if result is not None:
                dispatch_hashes.append(result[1])
        if len(set(dispatch_hashes)) != len(dispatch_hashes):
            errors.append(f"{label}.dispatch_receipts contains duplicate hashes")
    ledger_artifact = _artifact(root, run.get("ledger"), f"{label}.ledger", errors)
    calls: list[dict[str, Any]] = []
    if ledger_artifact is not None:
        calls = _load_ledger(ledger_artifact[0], f"{label}.ledger", errors)
        seen_dispatches: list[str] = []
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
    return coordinate, calls, sealed_at


def _validate_costs(
    calls: list[dict[str, Any]], reconciliation: Any, errors: list[str]
) -> None:
    if not isinstance(reconciliation, list):
        errors.append("cost_reconciliation must be an array")
        return
    records: dict[str, dict[str, Any]] = {}
    fields = {"account", "billed_usd", "tolerance_fraction"}
    for index, record in enumerate(reconciliation):
        label = f"cost_reconciliation[{index}]"
        if not _exact_fields(record, fields, label, errors):
            continue
        account = record.get("account")
        billed = record.get("billed_usd")
        tolerance = record.get("tolerance_fraction")
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
        tolerance_valid = (
            isinstance(tolerance, (int, float))
            and not isinstance(tolerance, bool)
            and math.isfinite(float(tolerance))
            and 0 <= tolerance <= 1
        )
        if not billed_valid:
            errors.append(f"{label}.billed_usd must be non-negative")
        if not tolerance_valid:
            errors.append(f"{label}.tolerance_fraction must be between 0 and 1")
        if billed_valid and tolerance_valid:
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
        tolerance = float(record["tolerance_fraction"])
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
        "schema", "pilot_id", "plan_sha256", "backend_manifest_sha256",
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
    if evidence.get("backend_manifest_sha256") != plan.get("backend_manifest_sha256"):
        errors.append("evidence backend manifest differs from the plan")
    authorization_time: datetime | None = None
    authorization_artifact = _artifact(
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
                authorization_time = _timestamp(
                    authorization.get("ratified_at"),
                    "operator_authorization payload ratified_at",
                    errors,
                )
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
        fields = {"task_id", "reason_code", "detail", "recorded_at", "evidence"}
        for index, row in enumerate(void_rows):
            label = f"voids[{index}]"
            if not _exact_fields(row, fields, label, errors):
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
            if not isinstance(row.get("detail"), str) or not row["detail"].strip():
                errors.append(f"{label}.detail must be non-empty")
            _timestamp(row.get("recorded_at"), f"{label}.recorded_at", errors)
            _artifact(evidence_root, row.get("evidence"), f"{label}.evidence", errors)

    arm_rows = evidence.get("arm_runs")
    coordinates: set[tuple[str, str]] = set()
    all_calls: list[dict[str, Any]] = []
    sealed: dict[tuple[str, str], datetime | None] = {}
    protocol_invalid_tasks: set[str] = set()
    all_dispatch_hashes: set[str] = set()
    if not isinstance(arm_rows, list):
        errors.append("arm_runs must be an array")
    else:
        previous_sequence = 0
        previous_sealed_at: datetime | None = None
        for index, row in enumerate(arm_rows):
            coordinate, calls, sealed_at = _validate_arm_run(
                row, index, tasks, plan, evidence_root, errors
            )
            if coordinate is not None:
                if coordinate in coordinates:
                    errors.append(f"duplicate arm run coordinate {coordinate}")
                coordinates.add(coordinate)
                sealed[coordinate] = sealed_at
                if row.get("protocol_valid") is False and coordinate[0] in tasks:
                    protocol_invalid_tasks.add(coordinate[0])
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
    if protocol_invalid_tasks - voided:
        errors.append("every protocol-invalid arm must atomically void its whole task")
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
    _validate_costs(all_calls, evidence.get("cost_reconciliation"), errors)

    seed_hex = evidence.get("audit_seed_reveal_hex")
    seed: bytes | None = None
    if not isinstance(seed_hex, str) or not re.fullmatch(r"[0-9a-f]{64}", seed_hex):
        errors.append("audit_seed_reveal_hex must be 32 lowercase hex bytes")
    else:
        seed = bytes.fromhex(seed_hex)
        if sha256_bytes(seed) != plan.get("audit_label_seed_commitment_sha256"):
            errors.append("audit seed reveal does not open the frozen commitment")
    audited = _validate_audits(
        evidence.get("audits"), seed, plan, tasks, unvoided, sealed,
        evidence_root, as_of, errors
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
        "closed_at": now.isoformat().replace("+00:00", "Z"),
    }
