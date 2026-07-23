"""Validate the review-only Tier Desk newsroom constitution.

The validator is intentionally stdlib-only. It checks the frozen v1 role
charters, authority ceilings, custody objects, epistemic and action state
machines, standing editions, and the absence of runtime bindings.

Usage:
    python -B scripts/validate_newsroom.py [newsroom.json|-] [--json]

Exit codes:
    0   constitution is valid
    1   constitution is invalid
    2   input is unreadable or not valid JSON
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any, Iterable

SCHEMA = "tier-bench/newsroom@1"
STATUS = "REVIEW_ONLY"

TOP_FIELDS = frozenset(
    {
        "schema",
        "status",
        "purpose",
        "project_map",
        "publisher",
        "planes",
        "octopode",
        "roles",
        "objects",
        "epistemic_state_machine",
        "action_state_machine",
        "editions",
        "invariants",
        "implementation_status",
        "review_questions",
    }
)

BANNED_RUNTIME_KEYS = frozenset(
    {
        "model",
        "models",
        "arm",
        "arms",
        "provider",
        "providers",
        "vendor",
        "vendors",
        "command",
        "commands",
        "acceptance",
        "argv",
        "shell",
        "environment",
        "env",
        "token",
        "tokens",
        "secret",
        "secrets",
        "credential",
        "credentials",
        "endpoint",
        "endpoints",
    }
)

PLANES = frozenset(
    {"OBSERVATION", "ANALYSIS", "VALIDATION", "EXECUTION", "PUBLICATION"}
)
PUBLISHER_AUTHORITIES = frozenset(
    {
        "AUTHORIZE_EXECUTION",
        "AUTHORIZE_PUBLICATION",
        "MERGE",
        "CHANGE_CAPS",
        "ACCEPT_CUSTODY_EXCEPTION",
    }
)

COMPONENTS = {
    "tier_bench": ("MEASUREMENT_AND_ROUTING", "EVIDENCE_ONLY"),
    "tier_run": ("EXECUTION_AND_REFEREE", "TERMINAL_RECEIPT"),
    "tier_desk": ("LOCAL_CONTROL_PLANE", "PUBLISHER_GATED_EXECUTION"),
    "crate_ops": ("OPERATING_METHOD", "NONE"),
    "chair_inbox": ("EXTERNAL_SUBMISSION_INTAKE", "DRAFT_ONLY"),
    "newsroom_contract": ("INSTITUTIONAL_COORDINATION_MODEL", "REVIEW_ONLY"),
}

ROLE_CHARTERS = {
    "assignment_desk": {
        "classification": "INTERNAL_CONTROL",
        "planes": {"OBSERVATION", "ANALYSIS"},
        "may": {"TRIAGE", "ASSIGN", "KILL", "EXPIRE", "PREPARE_ACTION"},
        "must_not": {
            "AUTHORIZE_EXECUTION",
            "EXECUTE",
            "VALIDATE_OWN_WORK",
            "AUTHORIZE_PUBLICATION",
            "PUBLISH",
            "MERGE",
        },
    },
    "reporter": {
        "classification": "INTERNAL_ANALYSIS",
        "planes": {"OBSERVATION", "ANALYSIS"},
        "may": {"REPORT", "REVISE_CORRECTION"},
        "must_not": {
            "AUTHORIZE_EXECUTION",
            "EXECUTE",
            "VALIDATE_OWN_WORK",
            "AUTHORIZE_PUBLICATION",
            "PUBLISH",
            "MERGE",
        },
    },
    "copy_desk": {
        "classification": "INTERNAL_ANALYSIS",
        "planes": {"ANALYSIS"},
        "may": {"EDIT", "ACCEPT_VERIFIED"},
        "must_not": {
            "AUTHORIZE_EXECUTION",
            "EXECUTE",
            "VALIDATE_OWN_WORK",
            "AUTHORIZE_PUBLICATION",
            "PUBLISH",
            "MERGE",
        },
    },
    "referee": {
        "classification": "INDEPENDENT_VALIDATION",
        "planes": {"VALIDATION"},
        "may": {"VALIDATE", "ADJUDICATE"},
        "must_not": {
            "AUTHOR_CANDIDATE",
            "AUTHORIZE_EXECUTION",
            "EXECUTE",
            "AUTHORIZE_PUBLICATION",
            "PUBLISH",
            "MERGE",
        },
    },
    "auditor": {
        "classification": "INDEPENDENT_VALIDATION",
        "planes": {"VALIDATION"},
        "may": {"AUDIT", "CHALLENGE_RECEIPT", "CHALLENGE_INDEPENDENCE"},
        "must_not": {
            "AUTHORIZE_EXECUTION",
            "EXECUTE",
            "AUTHORIZE_PUBLICATION",
            "PUBLISH",
            "MERGE",
        },
    },
    "archivist": {
        "classification": "INTERNAL_CUSTODY",
        "planes": {"OBSERVATION", "ANALYSIS"},
        "may": {"ARCHIVE", "DEDUPLICATE", "INVALIDATE_DOWNSTREAM"},
        "must_not": {
            "AUTHORIZE_EXECUTION",
            "EXECUTE",
            "VALIDATE",
            "AUTHORIZE_PUBLICATION",
            "PUBLISH",
            "MERGE",
        },
    },
    "corrections_desk": {
        "classification": "INTERNAL_CONTROL",
        "planes": {"OBSERVATION", "ANALYSIS"},
        "may": {"OPEN_CORRECTION", "TRACE_DEPENDENTS"},
        "must_not": {
            "AUTHORIZE_EXECUTION",
            "EXECUTE",
            "VALIDATE_OWN_WORK",
            "AUTHORIZE_PUBLICATION",
            "PUBLISH",
            "MERGE",
        },
    },
    "production_desk": {
        "classification": "INTERNAL_EXECUTION",
        "planes": {"EXECUTION"},
        "may": {"EXECUTE_AUTHORIZED", "INTERRUPT", "RECORD_INFRASTRUCTURE_ERROR"},
        "must_not": {
            "AUTHORIZE_EXECUTION",
            "AUTHOR_CANDIDATE",
            "VALIDATE",
            "AUTHORIZE_PUBLICATION",
            "PUBLISH",
            "MERGE",
        },
    },
    "chair": {
        "classification": "EXTERNAL_UNTRUSTED",
        "planes": set(),
        "may": {"SUBMIT_EXTERNAL"},
        "must_not": {
            "TRIAGE",
            "ASSIGN",
            "PREPARE_ACTION",
            "AUTHORIZE_EXECUTION",
            "EXECUTE",
            "VALIDATE",
            "AUTHORIZE_PUBLICATION",
            "PUBLISH",
            "MERGE",
        },
    },
}

OBJECTS = {
    "tip": ("EXTERNAL_UNTRUSTED", False),
    "assignment": ("LOCAL_CONTROL", False),
    "submission": ("EXTERNAL_UNTRUSTED", False),
    "evidence_packet": ("MIXED_EVIDENCE", False),
    "candidate": ("LOCAL_DERIVED", False),
    "receipt": ("LOCAL_VERIFIED", False),
    "edition": ("LOCAL_VERIFIED", False),
    "correction": ("LOCAL_CONTROL", False),
    "action_task": ("LOCAL_PUBLISHER_GATED", True),
}

EPISTEMIC_STATES = frozenset(
    {
        "OBSERVED",
        "TRIAGED",
        "ASSIGNED",
        "REPORTED",
        "SUBMITTED",
        "VERIFIED",
        "ACCEPTED",
        "PUBLISHED",
        "CORRECTION_OPEN",
        "CORRECTION_REPORTED",
        "CORRECTED",
        "KILLED",
        "EXPIRED",
    }
)
EPISTEMIC_TRANSITIONS = frozenset(
    {
        ("OBSERVED", "TRIAGED", "assignment_desk", "NONE"),
        ("TRIAGED", "ASSIGNED", "assignment_desk", "NONE"),
        ("ASSIGNED", "REPORTED", "reporter", "NONE"),
        ("ASSIGNED", "SUBMITTED", "chair", "NONE"),
        ("REPORTED", "VERIFIED", "referee", "NONE"),
        ("SUBMITTED", "VERIFIED", "referee", "NONE"),
        ("VERIFIED", "ACCEPTED", "copy_desk", "NONE"),
        ("ACCEPTED", "PUBLISHED", "publisher", "PUBLISHER"),
        ("ACCEPTED", "CORRECTION_OPEN", "corrections_desk", "NONE"),
        ("PUBLISHED", "CORRECTION_OPEN", "corrections_desk", "NONE"),
        ("CORRECTION_OPEN", "CORRECTION_REPORTED", "reporter", "NONE"),
        ("CORRECTION_REPORTED", "CORRECTED", "referee", "NONE"),
        ("CORRECTED", "PUBLISHED", "publisher", "PUBLISHER"),
        ("OBSERVED", "KILLED", "assignment_desk", "NONE"),
        ("TRIAGED", "KILLED", "assignment_desk", "NONE"),
        ("ASSIGNED", "KILLED", "assignment_desk", "NONE"),
        ("OBSERVED", "EXPIRED", "assignment_desk", "NONE"),
        ("TRIAGED", "EXPIRED", "assignment_desk", "NONE"),
        ("ASSIGNED", "EXPIRED", "assignment_desk", "NONE"),
    }
)

ACTION_STATES = frozenset(
    {"DRAFT", "QUEUED", "RUNNING", "ACCEPTED", "REJECTED", "ERROR", "CANCELED", "INTERRUPTED"}
)
ACTION_TRANSITIONS = frozenset(
    {
        ("DRAFT", "QUEUED", "publisher", "PUBLISHER"),
        ("QUEUED", "RUNNING", "production_desk", "PRIOR_PUBLISHER_AUTHORIZATION"),
        ("RUNNING", "ACCEPTED", "referee", "NONE"),
        ("RUNNING", "REJECTED", "referee", "NONE"),
        ("RUNNING", "ERROR", "production_desk", "NONE"),
        ("RUNNING", "INTERRUPTED", "production_desk", "NONE"),
        ("DRAFT", "CANCELED", "publisher", "PUBLISHER"),
        ("QUEUED", "CANCELED", "publisher", "PUBLISHER"),
        ("RUNNING", "CANCELED", "publisher", "PUBLISHER"),
        ("REJECTED", "DRAFT", "assignment_desk", "PUBLISHER"),
        ("ERROR", "DRAFT", "assignment_desk", "PUBLISHER"),
        ("CANCELED", "DRAFT", "assignment_desk", "PUBLISHER"),
        ("INTERRUPTED", "DRAFT", "assignment_desk", "PUBLISHER"),
    }
)

EDITION_POLICIES = {
    "daily_project": "DAILY",
    "weekly_investigations": "WEEKLY",
    "monthly_corrections": "MONTHLY",
}

INVARIANT_IDS = frozenset(
    {
        "external-evidence-no-authority",
        "role-continuity-not-session",
        "author-validator-separation",
        "publisher-gates-execution",
        "publisher-gates-publication",
        "receipt-before-acceptance",
        "unmeasured-is-unmeasured",
        "corrections-propagate",
        "atomic-auditable-transitions",
        "fail-closed-on-missing-evidence",
        "independence-is-recorded",
        "bounded-attention",
    }
)

EXPECTED_IMPLEMENTATION = {
    "implemented": {
        "TIER_RUN_REFEREE_AND_RECEIPTS",
        "TIER_DESK_DURABLE_TASK_AND_ACTION_STATES",
        "PUBLISHER_APPROVAL_GATE",
        "CHAIR_SINGLE_USE_DRAFT_ONLY_INTAKE",
        "CRATE_OPS_DISPOSABLE_SESSION_METHOD",
    },
    "review_only": {
        "NEWSROOM_ROLE_REGISTRY",
        "EPISTEMIC_STATE_MACHINE",
        "STANDING_EDITIONS",
        "CORRECTION_DEPENDENCY_TRACING",
        "OSS_SECURITY_BEATS",
    },
    "explicitly_absent": {
        "AUTONOMOUS_PUBLICATION",
        "EXTERNAL_EXECUTION_AUTHORITY",
        "IMMUTABLE_HEAD_CHAIR_EXECUTOR",
        "AUTOMATIC_MERGE",
        "AUTOMATIC_POLICY_REWRITING",
    },
}


class InputError(ValueError):
    """The input could not be read or decoded as JSON."""


def load_raw(source: str) -> Any:
    try:
        text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    except OSError as exc:
        raise InputError(f"cannot read input: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"input is not valid JSON: {exc}") from exc


def _fields(value: Any, allowed: set[str] | frozenset[str], label: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    unexpected = sorted(set(value) - set(allowed))
    missing = sorted(set(allowed) - set(value))
    violations = [f"{label} has unknown field {field!r}" for field in unexpected]
    violations.extend(f"{label} is missing field {field!r}" for field in missing)
    return violations


def _string_set(value: Any, label: str, *, allow_empty: bool = False) -> tuple[set[str], list[str]]:
    if not isinstance(value, list):
        return set(), [f"{label} must be a list"]
    if not value and not allow_empty:
        return set(), [f"{label} must not be empty"]
    violations: list[str] = []
    result: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            violations.append(f"{label} entries must be non-empty strings, got {item!r}")
            continue
        if item in result:
            violations.append(f"{label} has duplicate entry {item!r}")
        result.add(item)
    return result, violations


def _safe_repo_path(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    normalized = value.strip().replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        return False
    pure = PurePosixPath(normalized.rstrip("/"))
    return bool(pure.parts) and ".." not in pure.parts and pure.parts[0] != ".git"


def _walk_banned_keys(value: Any, path: str = "$") -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in BANNED_RUNTIME_KEYS:
                yield f"{path}.{key} is a forbidden runtime-binding field in a review-only contract"
            yield from _walk_banned_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_banned_keys(child, f"{path}[{index}]")


def _check_header(raw: dict[str, Any]) -> list[str]:
    violations = _fields(raw, TOP_FIELDS, "newsroom")
    if raw.get("schema") != SCHEMA:
        violations.append(f"schema must be exactly {SCHEMA!r}")
    if raw.get("status") != STATUS:
        violations.append("status must be REVIEW_ONLY")
    purpose = raw.get("purpose")
    if not isinstance(purpose, str) or not purpose.strip() or len(purpose) > 1000:
        violations.append("purpose must be a non-empty string of at most 1,000 characters")
    return violations


def _check_project_map(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["project_map must be a list"]
    violations: list[str] = []
    found: dict[str, dict[str, Any]] = {}
    allowed = {"id", "classification", "authority", "paths"}
    for index, item in enumerate(value):
        label = f"project_map[{index}]"
        violations.extend(_fields(item, allowed, label))
        if not isinstance(item, dict):
            continue
        component_id = item.get("id")
        if not isinstance(component_id, str):
            violations.append(f"{label}.id must be a string")
            continue
        if component_id in found:
            violations.append(f"project_map duplicates component {component_id!r}")
        found[component_id] = item
        expected = COMPONENTS.get(component_id)
        if expected is None:
            violations.append(f"{label}.id is unknown: {component_id!r}")
        elif (item.get("classification"), item.get("authority")) != expected:
            violations.append(
                f"{label} must classify {component_id!r} as {expected[0]!r} "
                f"with authority {expected[1]!r}"
            )
        paths, path_violations = _string_set(item.get("paths"), f"{label}.paths")
        violations.extend(path_violations)
        for path in paths:
            if not _safe_repo_path(path):
                violations.append(f"{label}.paths has unsafe repository path {path!r}")
    if set(found) != set(COMPONENTS):
        violations.append(
            f"project_map ids must be exactly {sorted(COMPONENTS)}, got {sorted(found)}"
        )
    return violations


def _check_publisher(value: Any) -> list[str]:
    allowed = {"kind", "exclusive_authorities"}
    violations = _fields(value, allowed, "publisher")
    if not isinstance(value, dict):
        return violations
    if value.get("kind") != "HUMAN":
        violations.append("publisher.kind must be HUMAN")
    authorities, errors = _string_set(
        value.get("exclusive_authorities"), "publisher.exclusive_authorities"
    )
    violations.extend(errors)
    if authorities != PUBLISHER_AUTHORITIES:
        violations.append(
            "publisher.exclusive_authorities must be exactly "
            f"{sorted(PUBLISHER_AUTHORITIES)}, got {sorted(authorities)}"
        )
    return violations


def _check_planes(value: Any) -> list[str]:
    planes, violations = _string_set(value, "planes")
    if planes != PLANES:
        violations.append(f"planes must be exactly {sorted(PLANES)}, got {sorted(planes)}")
    return violations


def _check_octopode(value: Any) -> list[str]:
    allowed = {
        "definition",
        "continuity",
        "execution_lanes_are_disposable",
        "lineage_independence_must_be_recorded",
    }
    violations = _fields(value, allowed, "octopode")
    if not isinstance(value, dict):
        return violations
    definition = value.get("definition")
    if not isinstance(definition, str) or not definition.strip():
        violations.append("octopode.definition must be a non-empty string")
    continuity, errors = _string_set(value.get("continuity"), "octopode.continuity")
    violations.extend(errors)
    expected = {
        "ROLE_CHARTER",
        "BEAT",
        "SOURCE_POLICY",
        "AUTHORITY_CEILING",
        "DECISION_HISTORY",
        "RECEIPT_HISTORY",
    }
    if continuity != expected:
        violations.append(
            f"octopode.continuity must be exactly {sorted(expected)}, got {sorted(continuity)}"
        )
    for field in (
        "execution_lanes_are_disposable",
        "lineage_independence_must_be_recorded",
    ):
        if value.get(field) is not True:
            violations.append(f"octopode.{field} must be true")
    return violations


def _check_roles(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["roles must be a list"]
    violations: list[str] = []
    found: dict[str, dict[str, Any]] = {}
    allowed = {"id", "classification", "planes", "may", "must_not"}
    for index, item in enumerate(value):
        label = f"roles[{index}]"
        violations.extend(_fields(item, allowed, label))
        if not isinstance(item, dict):
            continue
        role_id = item.get("id")
        if not isinstance(role_id, str):
            violations.append(f"{label}.id must be a string")
            continue
        if role_id in found:
            violations.append(f"roles duplicates {role_id!r}")
        found[role_id] = item
        expected = ROLE_CHARTERS.get(role_id)
        if expected is None:
            violations.append(f"{label}.id is unknown: {role_id!r}")
            continue
        if item.get("classification") != expected["classification"]:
            violations.append(
                f"{label}.classification must be {expected['classification']!r}"
            )
        planes, errors = _string_set(item.get("planes"), f"{label}.planes", allow_empty=True)
        violations.extend(errors)
        may, errors = _string_set(item.get("may"), f"{label}.may")
        violations.extend(errors)
        must_not, errors = _string_set(item.get("must_not"), f"{label}.must_not")
        violations.extend(errors)
        for field, actual in (("planes", planes), ("may", may), ("must_not", must_not)):
            if actual != expected[field]:
                violations.append(
                    f"{label}.{field} must be exactly {sorted(expected[field])}, "
                    f"got {sorted(actual)}"
                )
        leaked = may & PUBLISHER_AUTHORITIES
        if leaked:
            violations.append(
                f"{label}.may contains publisher-exclusive authority: {sorted(leaked)}"
            )
    if set(found) != set(ROLE_CHARTERS):
        violations.append(
            f"role ids must be exactly {sorted(ROLE_CHARTERS)}, got {sorted(found)}"
        )
    return violations


def _check_objects(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["objects must be a list"]
    violations: list[str] = []
    found: dict[str, dict[str, Any]] = {}
    allowed = {"id", "trust", "may_enter_action_plane"}
    for index, item in enumerate(value):
        label = f"objects[{index}]"
        violations.extend(_fields(item, allowed, label))
        if not isinstance(item, dict):
            continue
        object_id = item.get("id")
        if not isinstance(object_id, str):
            violations.append(f"{label}.id must be a string")
            continue
        if object_id in found:
            violations.append(f"objects duplicates {object_id!r}")
        found[object_id] = item
        expected = OBJECTS.get(object_id)
        if expected is None:
            violations.append(f"{label}.id is unknown: {object_id!r}")
            continue
        actual = (item.get("trust"), item.get("may_enter_action_plane"))
        if actual != expected:
            violations.append(
                f"{label} must have trust {expected[0]!r} and "
                f"may_enter_action_plane={expected[1]!r}"
            )
    if set(found) != set(OBJECTS):
        violations.append(f"object ids must be exactly {sorted(OBJECTS)}, got {sorted(found)}")
    enabled = sorted(
        item.get("id")
        for item in value
        if isinstance(item, dict) and item.get("may_enter_action_plane") is True
    )
    if enabled != ["action_task"]:
        violations.append(
            "action_task must be the only object eligible to enter the action plane; "
            f"got {enabled}"
        )
    return violations


def _transition_tuple(value: Any, label: str) -> tuple[tuple[str, str, str, str] | None, list[str]]:
    allowed = {"from", "to", "actor", "approval"}
    violations = _fields(value, allowed, label)
    if not isinstance(value, dict):
        return None, violations
    result: list[str] = []
    for field in ("from", "to", "actor", "approval"):
        item = value.get(field)
        if not isinstance(item, str) or not item:
            result.append(f"{label}.{field} must be a non-empty string")
    violations.extend(result)
    if result:
        return None, violations
    return (
        (value["from"], value["to"], value["actor"], value["approval"]),
        violations,
    )


def _check_machine(
    value: Any,
    label: str,
    expected_states: frozenset[str],
    expected_transitions: frozenset[tuple[str, str, str, str]],
) -> list[str]:
    allowed = {"states", "transitions"}
    violations = _fields(value, allowed, label)
    if not isinstance(value, dict):
        return violations
    states, errors = _string_set(value.get("states"), f"{label}.states")
    violations.extend(errors)
    if states != expected_states:
        violations.append(
            f"{label}.states must be exactly {sorted(expected_states)}, got {sorted(states)}"
        )
    transitions = value.get("transitions")
    if not isinstance(transitions, list):
        violations.append(f"{label}.transitions must be a list")
        return violations
    found: set[tuple[str, str, str, str]] = set()
    for index, item in enumerate(transitions):
        transition, errors = _transition_tuple(item, f"{label}.transitions[{index}]")
        violations.extend(errors)
        if transition is None:
            continue
        if transition in found:
            violations.append(f"{label}.transitions duplicates {transition!r}")
        found.add(transition)
        if transition[0] not in states or transition[1] not in states:
            violations.append(f"{label}.transitions references undeclared state: {transition!r}")
        if transition[2] != "publisher" and transition[2] not in ROLE_CHARTERS:
            violations.append(f"{label}.transitions has unknown actor: {transition[2]!r}")
        if transition[3] not in {"NONE", "PUBLISHER", "PRIOR_PUBLISHER_AUTHORIZATION"}:
            violations.append(f"{label}.transitions has unknown approval: {transition[3]!r}")
    if found != expected_transitions:
        missing = sorted(expected_transitions - found)
        extra = sorted(found - expected_transitions)
        violations.append(f"{label}.transitions differ from v1; missing={missing}, extra={extra}")
    return violations


def _check_transition_separation(raw: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    epistemic = raw.get("epistemic_state_machine", {})
    action = raw.get("action_state_machine", {})
    epistemic_transitions = epistemic.get("transitions", []) if isinstance(epistemic, dict) else []
    action_transitions = action.get("transitions", []) if isinstance(action, dict) else []

    for item in epistemic_transitions if isinstance(epistemic_transitions, list) else []:
        if not isinstance(item, dict):
            continue
        source, target, actor = item.get("from"), item.get("to"), item.get("actor")
        if source == "SUBMITTED" and target == "PUBLISHED":
            violations.append("SUBMITTED may not transition directly to PUBLISHED")
        if target == "VERIFIED" and actor != "referee":
            violations.append("only referee may move evidence into VERIFIED")
        if target == "PUBLISHED" and actor != "publisher":
            violations.append("only publisher may move material into PUBLISHED")

    for item in action_transitions if isinstance(action_transitions, list) else []:
        if not isinstance(item, dict):
            continue
        target, actor, approval = item.get("to"), item.get("actor"), item.get("approval")
        if actor == "chair":
            violations.append("chair may not appear in the action state machine")
        if target == "QUEUED" and (actor, approval) != ("publisher", "PUBLISHER"):
            violations.append("only publisher approval may move a Draft into QUEUED")
        if target == "RUNNING" and (
            actor,
            approval,
        ) != ("production_desk", "PRIOR_PUBLISHER_AUTHORIZATION"):
            violations.append(
                "only production_desk with prior publisher authorization may move work into RUNNING"
            )
        if target in {"ACCEPTED", "REJECTED"} and actor != "referee":
            violations.append("only referee may adjudicate RUNNING as ACCEPTED or REJECTED")
    return violations


def _check_editions(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["editions must be a list"]
    violations: list[str] = []
    found: dict[str, dict[str, Any]] = {}
    allowed = {
        "id",
        "cadence",
        "basis",
        "wip_limit",
        "inputs",
        "output",
        "empty_result",
        "publication_authority",
    }
    for index, item in enumerate(value):
        label = f"editions[{index}]"
        violations.extend(_fields(item, allowed, label))
        if not isinstance(item, dict):
            continue
        edition_id = item.get("id")
        if not isinstance(edition_id, str):
            violations.append(f"{label}.id must be a string")
            continue
        if edition_id in found:
            violations.append(f"editions duplicates {edition_id!r}")
        found[edition_id] = item
        cadence = EDITION_POLICIES.get(edition_id)
        if cadence is None:
            violations.append(f"{label}.id is unknown: {edition_id!r}")
        elif item.get("cadence") != cadence:
            violations.append(f"{label}.cadence must be {cadence!r}")
        if item.get("basis") not in {"MEASURED", "HYPOTHESIS", "UNMEASURED"}:
            violations.append(f"{label}.basis must name an evidence class")
        limit = item.get("wip_limit")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            violations.append(f"{label}.wip_limit must be an integer from 1 to 1000")
        inputs, errors = _string_set(item.get("inputs"), f"{label}.inputs")
        violations.extend(errors)
        if not inputs:
            violations.append(f"{label}.inputs must not be empty")
        for field in ("output", "empty_result"):
            text = item.get(field)
            if not isinstance(text, str) or not text.strip():
                violations.append(f"{label}.{field} must be a non-empty string")
        if item.get("publication_authority") != "publisher":
            violations.append(f"{label}.publication_authority must be publisher")
    if set(found) != set(EDITION_POLICIES):
        violations.append(
            f"edition ids must be exactly {sorted(EDITION_POLICIES)}, got {sorted(found)}"
        )
    if "monthly_corrections" not in found:
        violations.append("a monthly corrections edition is mandatory")
    return violations


def _check_invariants(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["invariants must be a list"]
    violations: list[str] = []
    found: set[str] = set()
    for index, item in enumerate(value):
        label = f"invariants[{index}]"
        violations.extend(_fields(item, {"id", "rule"}, label))
        if not isinstance(item, dict):
            continue
        invariant_id = item.get("id")
        rule = item.get("rule")
        if not isinstance(invariant_id, str) or not re.fullmatch(r"[a-z0-9-]{1,80}", invariant_id):
            violations.append(f"{label}.id must be a lowercase kebab-case identifier")
            continue
        if invariant_id in found:
            violations.append(f"invariants duplicates {invariant_id!r}")
        found.add(invariant_id)
        if not isinstance(rule, str) or not rule.strip():
            violations.append(f"{label}.rule must be a non-empty string")
    if found != INVARIANT_IDS:
        violations.append(
            f"invariant ids must be exactly {sorted(INVARIANT_IDS)}, got {sorted(found)}"
        )
    return violations


def _check_implementation(value: Any) -> list[str]:
    allowed = {"implemented", "review_only", "explicitly_absent"}
    violations = _fields(value, allowed, "implementation_status")
    if not isinstance(value, dict):
        return violations
    for field, expected in EXPECTED_IMPLEMENTATION.items():
        actual, errors = _string_set(value.get(field), f"implementation_status.{field}")
        violations.extend(errors)
        if actual != expected:
            violations.append(
                f"implementation_status.{field} must be exactly {sorted(expected)}, "
                f"got {sorted(actual)}"
            )
    return violations


def _check_review_questions(value: Any) -> list[str]:
    questions, violations = _string_set(value, "review_questions")
    if len(questions) < 1:
        violations.append("review_questions must contain at least one control question")
    return violations


def validate(raw: Any) -> list[str]:
    """Return all violations. An empty list means the constitution is valid."""
    if not isinstance(raw, dict):
        return ["newsroom constitution must be a JSON object"]

    violations: list[str] = list(_walk_banned_keys(raw))
    violations.extend(_check_header(raw))
    violations.extend(_check_project_map(raw.get("project_map")))
    violations.extend(_check_publisher(raw.get("publisher")))
    violations.extend(_check_planes(raw.get("planes")))
    violations.extend(_check_octopode(raw.get("octopode")))
    violations.extend(_check_roles(raw.get("roles")))
    violations.extend(_check_objects(raw.get("objects")))
    violations.extend(
        _check_machine(
            raw.get("epistemic_state_machine"),
            "epistemic_state_machine",
            EPISTEMIC_STATES,
            EPISTEMIC_TRANSITIONS,
        )
    )
    violations.extend(
        _check_machine(
            raw.get("action_state_machine"),
            "action_state_machine",
            ACTION_STATES,
            ACTION_TRANSITIONS,
        )
    )
    violations.extend(_check_transition_separation(raw))
    violations.extend(_check_editions(raw.get("editions")))
    violations.extend(_check_invariants(raw.get("invariants")))
    violations.extend(_check_implementation(raw.get("implementation_status")))
    violations.extend(_check_review_questions(raw.get("review_questions")))
    return violations


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="validate_newsroom.py",
        description="Validate the frozen tier-bench/newsroom@1 review contract.",
    )
    parser.add_argument(
        "source",
        nargs="?",
        default="newsroom.json",
        metavar="newsroom.json|-",
        help="constitution file, or '-' for stdin (default: newsroom.json)",
    )
    parser.add_argument("--json", action="store_true", help="print JSON result")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        raw = load_raw(args.source)
    except InputError as exc:
        if args.json:
            print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"validate_newsroom.py: {exc}", file=sys.stderr)
        return 2

    violations = validate(raw)
    if args.json:
        print(
            json.dumps(
                {"valid": not violations, "violations": violations},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    elif violations:
        print("invalid:")
        for violation in violations:
            print(f"  - {violation}")
    else:
        print("valid")
    return 0 if not violations else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # unexpected failure outside modeled guard paths
        print(f"validate_newsroom.py: unexpected failure: {exc}", file=sys.stderr)
        raise SystemExit(1)
