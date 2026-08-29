#!/usr/bin/env python3
"""Consolidated, provider-neutral floor for AXM action player products.

This module validates the records that keep Arc law, World presentation, provider
experiments, engine evidence, human observation, and product acceptance separate.

It does not implement gameplay, choose a provider, authenticate a mandate, or
accept a player product.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

CATALOG_FORMAT = "axm-action-player-floor-catalog/1"
INTENT_FORMAT = "axm-action-player-intent/1"
CHANGE_FORMAT = "axm-action-player-change/1"
WITNESS_FORMAT = "axm-action-player-negative-witness/1"
REPORT_FORMAT = "axm-action-player-floor-report/1"

ID_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{40,64}$")
GATE_STATES = {"pass", "warn", "fail", "open", "not_applicable"}
WITNESS_STATES = {"confirmed", "reproduced", "planned"}
EVIDENCE_TIERS = {
    "source",
    "conformance",
    "engine",
    "human",
    "acceptance",
}
OWNERS = {
    "arc",
    "world",
    "tier_bench",
    "tools",
    "hinge",
    "embodied",
    "bloodstream",
    "named_authority",
}
TOUCH_OWNER = {
    "action_law": "arc",
    "timing": "arc",
    "outcome": "arc",
    "objective": "arc",
    "semantic_cue": "arc",
    "mechanic_learning": "arc",
    "difficulty_profile": "arc",
    "input_mapping": "world",
    "camera": "world",
    "animation": "world",
    "vfx": "world",
    "audio": "world",
    "haptic": "world",
    "hud": "world",
    "accessibility_presentation": "world",
    "engine_integration": "world",
    "provider_evaluation": "tier_bench",
    "trace_inspection": "tools",
    "invalidation": "hinge",
    "human_evidence": "embodied",
    "circulation": "bloodstream",
    "product_acceptance": "named_authority",
}


class ContractError(ValueError):
    """Raised when a floor record violates the consolidated contract."""


def _reject_float(value: str) -> None:
    raise ContractError(f"Floating-point JSON values are prohibited: {value}")


def _object_pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"Duplicate JSON object key: {key}")
        result[key] = value
    return result


def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(
            handle,
            object_pairs_hook=_object_pairs_no_duplicates,
            parse_float=_reject_float,
        )


def _validate_json_value(value: Any, path: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        raise ContractError(f"{path}: floating-point values are prohibited")
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError(f"{path}: object keys must be strings")
            _validate_json_value(item, f"{path}.{key}")
        return
    raise ContractError(f"{path}: unsupported JSON value {type(value).__name__}")


def canonical_bytes(value: Any) -> bytes:
    _validate_json_value(value, "$")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _without_keys(value: Any, omitted: set[str]) -> Any:
    if isinstance(value, list):
        return [_without_keys(item, omitted) for item in value]
    if isinstance(value, dict):
        return {
            key: _without_keys(item, omitted)
            for key, item in value.items()
            if key not in omitted
        }
    return value


def digest(prefix: str, value: Any, omitted_keys: Iterable[str] = ()) -> str:
    normalized = _without_keys(value, set(omitted_keys))
    return f"{prefix}_{hashlib.sha256(canonical_bytes(normalized)).hexdigest()}"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _require_id(value: Any, label: str) -> str:
    _require(isinstance(value, str) and bool(ID_RE.fullmatch(value)), f"{label}: invalid id")
    return value


def _unique_ids(rows: Any, label: str) -> dict[str, Mapping[str, Any]]:
    _require(isinstance(rows, list), f"{label}: must be an array")
    result: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(rows):
        _require(isinstance(row, dict), f"{label}[{index}]: must be an object")
        row_id = _require_id(row.get("id"), f"{label}[{index}].id")
        _require(row_id not in result, f"{label}: duplicate id {row_id}")
        result[row_id] = row
    return result


def _require_nonempty_strings(value: Any, label: str) -> list[str]:
    _require(isinstance(value, list) and value, f"{label}: non-empty array required")
    result: list[str] = []
    for index, item in enumerate(value):
        _require(isinstance(item, str) and item, f"{label}[{index}]: string required")
        result.append(item)
    return result


def _validate_record_id(value: Mapping[str, Any], field: str, prefix: str) -> str:
    record_id = value.get(field)
    _require(isinstance(record_id, str), f"{field}: missing")
    expected = digest(prefix, value, {field})
    _require(record_id == expected, f"{field}: expected {expected}, got {record_id}")
    return record_id


def validate_catalog(catalog: Any) -> dict[str, Any]:
    _validate_json_value(catalog, "$")
    _require(isinstance(catalog, dict), "catalog: object required")
    _require(catalog.get("format") == CATALOG_FORMAT, "catalog: unsupported format")
    _require(catalog.get("authority") == "measurement_and_conformance_only", "catalog: invalid authority")
    _require(catalog.get("aggregateReadinessScore") is None, "catalog: aggregate readiness score prohibited")
    _require(catalog.get("floorVersion") == 1, "catalog: unsupported floorVersion")
    _require_nonempty_strings(catalog.get("separations"), "catalog.separations")
    _require_nonempty_strings(catalog.get("scopeHold"), "catalog.scopeHold")

    organs = _unique_ids(catalog.get("organs"), "catalog.organs")
    interfaces = _unique_ids(catalog.get("interfaces"), "catalog.interfaces")
    gates = _unique_ids(catalog.get("gates"), "catalog.gates")
    drift_classes = _unique_ids(catalog.get("driftClasses"), "catalog.driftClasses")
    commodity_cells = _unique_ids(catalog.get("commodityCells"), "catalog.commodityCells")
    issues = _unique_ids(catalog.get("coordination"), "catalog.coordination")

    _require(set(organs) == OWNERS, "catalog: organ owner set is incomplete")
    _require(len(interfaces) >= 9, "catalog: interface spine incomplete")
    _require(len(gates) >= 20, "catalog: gate spine incomplete")
    _require(len(drift_classes) >= 12, "catalog: drift register incomplete")
    _require(len(commodity_cells) >= 10, "catalog: commodity register incomplete")

    for organ_id, organ in organs.items():
        _require(organ.get("authority") in {"law", "presentation", "measurement", "inspection", "challenge", "evidence", "circulation", "acceptance"}, f"{organ_id}: authority class absent")
        _require_nonempty_strings(organ.get("may"), f"{organ_id}.may")
        _require_nonempty_strings(organ.get("mayNot"), f"{organ_id}.mayNot")

    for interface_id, interface in interfaces.items():
        _require(interface.get("owner") in OWNERS, f"{interface_id}: unknown owner")
        _require(interface.get("authority") in {"authoritative", "provisional", "none", "external"}, f"{interface_id}: invalid authority")
        _require_nonempty_strings(interface.get("inputs"), f"{interface_id}.inputs")
        _require_nonempty_strings(interface.get("outputs"), f"{interface_id}.outputs")

    for gate_id, gate in gates.items():
        _require(gate.get("owner") in OWNERS, f"{gate_id}: unknown owner")
        _require(gate.get("tier") in EVIDENCE_TIERS, f"{gate_id}: invalid evidence tier")
        _require(gate.get("hard") in {True, False}, f"{gate_id}: hard flag absent")
        _require(isinstance(gate.get("failureDefault"), str) and gate["failureDefault"], f"{gate_id}: failureDefault absent")
        _require(isinstance(gate.get("description"), str) and gate["description"], f"{gate_id}: description absent")

    for drift_id, drift in drift_classes.items():
        _require(drift.get("owner") in OWNERS, f"{drift_id}: unknown owner")
        _require(drift.get("defaultResponse") in {"investigate", "hold", "diagnostic_only", "repair", "migrate", "revoke"}, f"{drift_id}: invalid defaultResponse")
        _require_nonempty_strings(drift.get("signals"), f"{drift_id}.signals")
        _require(isinstance(drift.get("correction"), str) and drift["correction"], f"{drift_id}: correction absent")

    for cell_id, cell in commodity_cells.items():
        _require(cell.get("owner") == "tier_bench", f"{cell_id}: commodity cells belong to tier_bench")
        _require(cell.get("authority") == "none", f"{cell_id}: commodity may not own authority")
        _require(cell.get("state") in {"discovered", "adapter_planned", "fixture_qualified", "engine_qualified", "revoked"}, f"{cell_id}: invalid state")
        _require_nonempty_strings(cell.get("providers"), f"{cell_id}.providers")
        _require_nonempty_strings(cell.get("requiredGates"), f"{cell_id}.requiredGates")
        for gate_id in cell["requiredGates"]:
            _require(gate_id in gates, f"{cell_id}: unknown gate {gate_id}")

    for issue_id, issue in issues.items():
        _require(issue.get("owner") in OWNERS, f"{issue_id}: unknown owner")
        _require(isinstance(issue.get("url"), str) and issue["url"].startswith("https://github.com/"), f"{issue_id}: invalid url")
        _require(isinstance(issue.get("object"), str) and issue["object"], f"{issue_id}: object absent")

    required_witnesses = _require_nonempty_strings(catalog.get("requiredNegativeWitnesses"), "catalog.requiredNegativeWitnesses")
    _require(len(required_witnesses) >= 3, "catalog: insufficient negative witnesses")
    _validate_record_id(catalog, "catalogId", "actionfloor1")

    return {
        "organs": organs,
        "interfaces": interfaces,
        "gates": gates,
        "driftClasses": drift_classes,
        "commodityCells": commodity_cells,
        "coordination": issues,
        "requiredNegativeWitnesses": set(required_witnesses),
    }


def validate_intent(intent: Any, catalog: Any) -> str:
    indexes = validate_catalog(catalog)
    _validate_json_value(intent, "$")
    _require(isinstance(intent, dict), "intent: object required")
    _require(intent.get("format") == INTENT_FORMAT, "intent: unsupported format")
    _require(intent.get("authority") == "human_owned", "intent: authority must be human_owned")
    _require("provider" not in intent and "supplier" not in intent, "intent: provider-specific fields prohibited")
    _require(intent.get("aggregateReadinessScore") is None, "intent: aggregate readiness score prohibited")
    _require(isinstance(intent.get("title"), str) and intent["title"], "intent.title absent")
    _require_nonempty_strings(intent.get("goals"), "intent.goals")
    _require_nonempty_strings(intent.get("forbidden"), "intent.forbidden")
    _require_nonempty_strings(intent.get("requiredGates"), "intent.requiredGates")
    for gate_id in intent["requiredGates"]:
        _require(gate_id in indexes["gates"], f"intent: unknown gate {gate_id}")

    sources = _unique_ids(intent.get("sourceAuthorities"), "intent.sourceAuthorities")
    _require({"arc", "world"} <= set(sources), "intent: Arc and World source authority required")
    for source_id, source in sources.items():
        _require(source.get("owner") in {"arc", "world"}, f"{source_id}: invalid source owner")
        _require(isinstance(source.get("repository"), str) and "/" in source["repository"], f"{source_id}: repository absent")
        _require(isinstance(source.get("ref"), str) and bool(SHA256_RE.fullmatch(source["ref"])), f"{source_id}: exact ref required")
        _require(source.get("status") in {"authority", "donor", "candidate"}, f"{source_id}: invalid status")

    stages = _unique_ids(intent.get("mechanicLearning"), "intent.mechanicLearning")
    _require({"teach", "practice", "master"} <= set(stages), "intent: teach/practice/master custody required")
    order = [row["id"] for row in intent["mechanicLearning"]]
    _require(order.index("teach") < order.index("practice") < order.index("master"), "intent: mechanic learning order invalid")
    for stage_id, stage in stages.items():
        _require(isinstance(stage.get("challengeId"), str) and stage["challengeId"], f"{stage_id}: challengeId absent")
        _require(stage.get("mandatory") in {True, False}, f"{stage_id}: mandatory flag absent")
        _require(stage.get("safeIntroduction") in {True, False}, f"{stage_id}: safeIntroduction flag absent")
        _require_nonempty_strings(stage.get("requiredCueIds"), f"{stage_id}.requiredCueIds")
        if stage["mandatory"]:
            _require(stage_id == "master", f"{stage_id}: only master may be mandatory")
    _require(stages["teach"]["safeIntroduction"] is True, "intent: teach stage must be safe")
    _require(stages["practice"]["mandatory"] is False, "intent: practice stage must remain optional")
    _require(isinstance(stages["master"].get("alternateCompletionPolicy"), str) and stages["master"]["alternateCompletionPolicy"], "intent: master alternateCompletionPolicy absent")

    cues = _unique_ids(intent.get("requiredCues"), "intent.requiredCues")
    _require(len(cues) >= 10, "intent: cue coverage incomplete")
    for cue_id, cue in cues.items():
        _require(cue.get("owner") == "arc", f"{cue_id}: cue semantics belong to Arc")
        _require_nonempty_strings(cue.get("requiredPresentationChannels"), f"{cue_id}.requiredPresentationChannels")
        _require(cue.get("stateMutation") is False, f"{cue_id}: cue mapping may not mutate state")

    venues = _unique_ids(intent.get("venues"), "intent.venues")
    _require({"browser", "unity_editor", "windows_player", "human_keyboard_mouse", "human_controller"} <= set(venues), "intent: required venues absent")
    for venue_id, venue in venues.items():
        _require(venue.get("tier") in EVIDENCE_TIERS, f"{venue_id}: invalid tier")
        _require_nonempty_strings(venue.get("requiredEvidence"), f"{venue_id}.requiredEvidence")

    accessibility = intent.get("accessibility")
    _require(isinstance(accessibility, dict), "intent.accessibility absent")
    _require_nonempty_strings(accessibility.get("requiredProfiles"), "intent.accessibility.requiredProfiles")
    _require_nonempty_strings(accessibility.get("requiredAlternatives"), "intent.accessibility.requiredAlternatives")

    acceptance = intent.get("acceptance")
    _require(isinstance(acceptance, dict), "intent.acceptance absent")
    _require(acceptance.get("runtimeMayIssueHumanReceipt") is False, "intent: runtime may not issue human receipt")
    _require(acceptance.get("authorMaySelfAccept") is False, "intent: author may not self-accept")
    _require(acceptance.get("namedAuthorityRequired") is True, "intent: named authority required")
    _validate_record_id(intent, "intentId", "playerintent1")
    return intent["intentId"]


def expected_owners(touches: Sequence[str]) -> set[str]:
    owners: set[str] = set()
    for touch in touches:
        _require(touch in TOUCH_OWNER, f"change: unknown touch {touch}")
        owners.add(TOUCH_OWNER[touch])
    return owners


def validate_change(change: Any) -> str:
    _validate_json_value(change, "$")
    _require(isinstance(change, dict), "change: object required")
    _require(change.get("format") == CHANGE_FORMAT, "change: unsupported format")
    _require(isinstance(change.get("summary"), str) and change["summary"], "change.summary absent")
    touches = _require_nonempty_strings(change.get("touches"), "change.touches")
    owners = expected_owners(touches)
    _require(change.get("aggregateReadinessScore") is None, "change: aggregate readiness score prohibited")
    coordination = change.get("coordination")
    proposed_owner = change.get("proposedOwner")

    if len(owners) == 1:
        expected = next(iter(owners))
        _require(proposed_owner == expected, f"change: proposedOwner {proposed_owner!r} must be {expected!r}")
        _require(coordination in {None, "single-organ"}, "change: single-owner change cannot claim cross-organ coordination")
    else:
        _require(coordination == "cross-organ", "change: multi-owner change requires cross-organ coordination")
        subtasks = _unique_ids(change.get("subtasks"), "change.subtasks")
        subtask_owners = {row.get("owner") for row in subtasks.values()}
        _require(subtask_owners == owners, f"change: subtask owners {sorted(subtask_owners)} do not match {sorted(owners)}")
        for subtask_id, subtask in subtasks.items():
            _require(subtask.get("owner") in OWNERS, f"{subtask_id}: unknown owner")
            _require_nonempty_strings(subtask.get("touches"), f"{subtask_id}.touches")
            _require(expected_owners(subtask["touches"]) == {subtask["owner"]}, f"{subtask_id}: mixed owner touches")
    _require_nonempty_strings(change.get("sourceRefs"), "change.sourceRefs")
    rollback = change.get("rollback")
    _require(isinstance(rollback, dict), "change.rollback absent")
    _require(isinstance(rollback.get("point"), str) and rollback["point"], "change.rollback.point absent")
    _require(isinstance(rollback.get("proof"), str) and rollback["proof"], "change.rollback.proof absent")
    _validate_record_id(change, "changeId", "playerchange1")
    return change["changeId"]


def validate_witness(witness: Any, catalog: Any) -> str:
    indexes = validate_catalog(catalog)
    _validate_json_value(witness, "$")
    _require(isinstance(witness, dict), "witness: object required")
    _require(witness.get("format") == WITNESS_FORMAT, "witness: unsupported format")
    witness_name = _require_id(witness.get("name"), "witness.name")
    _require(witness_name in indexes["requiredNegativeWitnesses"], f"witness: {witness_name} is not required")
    _require(witness.get("state") in WITNESS_STATES, "witness: invalid state")
    _require_nonempty_strings(witness.get("signals"), "witness.signals")
    expected = _require_nonempty_strings(witness.get("expectedDriftClasses"), "witness.expectedDriftClasses")
    for drift_id in expected:
        _require(drift_id in indexes["driftClasses"], f"witness: unknown drift class {drift_id}")
    _require_nonempty_strings(witness.get("requiredRefusal"), "witness.requiredRefusal")
    _require(isinstance(witness.get("evidenceLimit"), str) and witness["evidenceLimit"], "witness.evidenceLimit absent")
    _validate_record_id(witness, "witnessId", "playerwitness1")
    return witness["witnessId"]


def build_report(
    catalog: Any,
    intents: Sequence[Any],
    witnesses: Sequence[Any],
    changes: Sequence[Any],
) -> dict[str, Any]:
    indexes = validate_catalog(catalog)
    intent_ids = [validate_intent(intent, catalog) for intent in intents]
    witness_ids = [validate_witness(witness, catalog) for witness in witnesses]
    change_ids = [validate_change(change) for change in changes]
    witnessed = {witness["name"] for witness in witnesses}
    missing_witnesses = sorted(indexes["requiredNegativeWitnesses"] - witnessed)
    qualified_cells = [
        cell_id
        for cell_id, cell in indexes["commodityCells"].items()
        if cell.get("state") in {"fixture_qualified", "engine_qualified"}
    ]
    open_gates = sorted(indexes["gates"])
    report: dict[str, Any] = {
        "format": REPORT_FORMAT,
        "authority": "measurement_and_conformance_only",
        "aggregateReadinessScore": None,
        "catalogId": catalog["catalogId"],
        "intentIds": sorted(intent_ids),
        "witnessIds": sorted(witness_ids),
        "changeIds": sorted(change_ids),
        "counts": {
            "organs": len(indexes["organs"]),
            "interfaces": len(indexes["interfaces"]),
            "gates": len(indexes["gates"]),
            "driftClasses": len(indexes["driftClasses"]),
            "commodityCells": len(indexes["commodityCells"]),
            "coordinationRecords": len(indexes["coordination"]),
            "negativeWitnesses": len(witness_ids),
            "qualifiedCommodityCells": len(qualified_cells),
        },
        "coverage": {
            "requiredNegativeWitnessesComplete": not missing_witnesses,
            "missingNegativeWitnesses": missing_witnesses,
            "qualifiedCommodityCells": sorted(qualified_cells),
            "openGates": open_gates,
            "productAccepted": False,
        },
        "blockers": [
            "Arc semantic phase and mechanic-learning contract is not yet accepted.",
            "World natural player has not completed real Unity and Windows-player acceptance.",
            "Provider substitution has not been qualified against one exact UNDERDRAIN trace.",
            "Independent keyboard/mouse and controller player evidence is absent.",
            "No named authority has accepted a player product.",
        ],
    }
    report["reportId"] = digest("actionfloorreport1", report, {"reportId"})
    return report


def _write_json(path: str | Path, value: Any) -> None:
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def command_validate(args: argparse.Namespace) -> None:
    catalog = load_json(args.catalog)
    validate_catalog(catalog)
    for path in args.intent:
        validate_intent(load_json(path), catalog)
    witnesses = load_json(args.witnesses)
    _require(isinstance(witnesses, list), "witnesses file: array required")
    for witness in witnesses:
        validate_witness(witness, catalog)
    changes = load_json(args.changes)
    _require(isinstance(changes, list), "changes file: array required")
    for change in changes:
        validate_change(change)
    print("PASS: AXM Action Player Floor")


def command_report(args: argparse.Namespace) -> None:
    catalog = load_json(args.catalog)
    intents = [load_json(path) for path in args.intent]
    witnesses = load_json(args.witnesses)
    changes = load_json(args.changes)
    _require(isinstance(witnesses, list), "witnesses file: array required")
    _require(isinstance(changes, list), "changes file: array required")
    report = build_report(catalog, intents, witnesses, changes)
    _write_json(args.output, report)
    print(report["reportId"])


def command_digest(args: argparse.Namespace) -> None:
    value = load_json(args.path)
    print(digest(args.prefix, value, set(args.omit)))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate")
    validate.add_argument("--catalog", required=True)
    validate.add_argument("--intent", action="append", default=[], required=True)
    validate.add_argument("--witnesses", required=True)
    validate.add_argument("--changes", required=True)
    validate.set_defaults(function=command_validate)

    report = sub.add_parser("report")
    report.add_argument("--catalog", required=True)
    report.add_argument("--intent", action="append", default=[], required=True)
    report.add_argument("--witnesses", required=True)
    report.add_argument("--changes", required=True)
    report.add_argument("--output", required=True)
    report.set_defaults(function=command_report)

    digest_parser = sub.add_parser("digest")
    digest_parser.add_argument("path")
    digest_parser.add_argument("--prefix", required=True)
    digest_parser.add_argument("--omit", action="append", default=[])
    digest_parser.set_defaults(function=command_digest)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        args.function(args)
    except ContractError as error:
        raise SystemExit(f"FAIL: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
