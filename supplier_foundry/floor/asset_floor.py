#!/usr/bin/env python3
"""Provider-neutral contracts for the AXM Asset Floor.

The floor validates intent, capability, provider, and qualification records. It
does not generate assets, choose suppliers, authenticate mandates, or accept a
game product. All identities are canonical SHA-256 digests over integer-only
JSON so any host can independently reconstruct them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

CATALOG_FORMAT = "axm-asset-floor-catalog/1"
INTENT_FORMAT = "axm-asset-intent/1"
QUALIFICATION_FORMAT = "axm-asset-qualification/1"
REPORT_FORMAT = "axm-asset-floor-report/1"

ID_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GATE_STATES = {"pass", "warn", "fail", "open", "not_applicable"}
SUPPLIER_STATES = {"discovered", "adapter_planned", "fixture_qualified", "engine_qualified", "revoked"}
LICENSE_STATES = {"unknown", "research_only", "legal_review", "shipping_eligible", "blocked"}
AUTHORITY_VALUES = {"none"}
PROFILE_CLASSES = {
    "3d_prop",
    "3d_mechanism",
    "3d_character",
    "3d_creature",
    "3d_environment_kit",
    "material",
    "animation_clip",
    "vfx",
    "audio",
    "ui",
}


class ContractError(ValueError):
    """Raised when a floor record violates the provider-neutral contract."""


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


def canonical_bytes(value: Any) -> bytes:
    _validate_json_value(value, "$")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


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


def digest(prefix: str, value: Any, omitted_keys: Iterable[str] = ()) -> str:
    omitted = set(omitted_keys)
    normalized = _without_keys(value, omitted)
    return f"{prefix}_{hashlib.sha256(canonical_bytes(normalized)).hexdigest()}"


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


def validate_catalog(catalog: Any) -> dict[str, Any]:
    _validate_json_value(catalog, "$")
    _require(isinstance(catalog, dict), "catalog: must be an object")
    _require(catalog.get("format") == CATALOG_FORMAT, "catalog: unsupported format")
    _require(catalog.get("authority") == "measurement_only", "catalog: authority must be measurement_only")
    _require(catalog.get("aggregateReadinessScore") is None, "catalog: aggregate readiness scores are prohibited")

    gates = _unique_ids(catalog.get("gates"), "gates")
    capabilities = _unique_ids(catalog.get("capabilities"), "capabilities")
    profiles = _unique_ids(catalog.get("profiles"), "profiles")
    suppliers = _unique_ids(catalog.get("suppliers"), "suppliers")
    gaps = _unique_ids(catalog.get("gaps"), "gaps")

    _require(len(gates) >= 15, "catalog: at least fifteen independent gates are required")
    _require(len(capabilities) >= 15, "catalog: at least fifteen capabilities are required")
    _require(len(gaps) >= 10, "catalog: the open-gap register is incomplete")

    for gate_id, gate in gates.items():
        _require(gate.get("hard") in {True, False}, f"{gate_id}: gate hard flag missing")
        _require(isinstance(gate.get("description"), str) and gate["description"], f"{gate_id}: description missing")

    for capability_id, capability in capabilities.items():
        _require(isinstance(capability.get("owner"), str) and capability["owner"], f"{capability_id}: owner missing")
        for key in ("canonicalInputs", "canonicalOutputs", "requiredGates"):
            _require(isinstance(capability.get(key), list), f"{capability_id}: {key} must be an array")
        _require(capability.get("providerRequired") in {True, False}, f"{capability_id}: providerRequired missing")
        for gate_id in capability["requiredGates"]:
            _require(gate_id in gates, f"{capability_id}: unknown gate {gate_id}")
        _require(capability.get("authority") == "none", f"{capability_id}: capability adapter may not hold authority")

    for profile_id, profile in profiles.items():
        _require(profile_id in PROFILE_CLASSES, f"{profile_id}: unsupported profile class")
        required_gates = profile.get("requiredGates")
        required_capabilities = profile.get("requiredCapabilities")
        _require(isinstance(required_gates, list) and required_gates, f"{profile_id}: requiredGates absent")
        _require(isinstance(required_capabilities, list) and required_capabilities, f"{profile_id}: requiredCapabilities absent")
        for gate_id in required_gates:
            _require(gate_id in gates, f"{profile_id}: unknown gate {gate_id}")
        for capability_id in required_capabilities:
            _require(capability_id in capabilities, f"{profile_id}: unknown capability {capability_id}")

    for supplier_id, supplier in suppliers.items():
        _require(supplier.get("state") in SUPPLIER_STATES, f"{supplier_id}: invalid state")
        license_record = supplier.get("license")
        _require(isinstance(license_record, dict), f"{supplier_id}: license record absent")
        _require(license_record.get("status") in LICENSE_STATES, f"{supplier_id}: invalid license status")
        _require(isinstance(supplier.get("capabilities"), list) and supplier["capabilities"], f"{supplier_id}: capabilities absent")
        for capability_id in supplier["capabilities"]:
            _require(capability_id in capabilities, f"{supplier_id}: unknown capability {capability_id}")
        authority = supplier.get("authority")
        _require(isinstance(authority, dict) and authority, f"{supplier_id}: authority exclusions absent")
        for axis, value in authority.items():
            _require(value in AUTHORITY_VALUES, f"{supplier_id}: {axis} authority must be none")
        _require(isinstance(supplier.get("evidence"), list), f"{supplier_id}: evidence must be an array")
        if supplier["state"] in {"fixture_qualified", "engine_qualified"}:
            _require(bool(supplier["evidence"]), f"{supplier_id}: qualified supplier has no evidence")

    for gap_id, gap in gaps.items():
        _require(gap.get("state") in {"open", "emerging", "standardizing", "bounded"}, f"{gap_id}: invalid state")
        _require(isinstance(gap.get("firstExperiment"), str) and gap["firstExperiment"], f"{gap_id}: firstExperiment absent")
        _require(isinstance(gap.get("failureDefault"), str) and gap["failureDefault"], f"{gap_id}: failureDefault absent")

    return {
        "gates": gates,
        "capabilities": capabilities,
        "profiles": profiles,
        "suppliers": suppliers,
        "gaps": gaps,
    }


def validate_intent(intent: Any, catalog: Any) -> str:
    indexes = validate_catalog(catalog)
    _validate_json_value(intent, "$")
    _require(isinstance(intent, dict), "intent: must be an object")
    _require(intent.get("format") == INTENT_FORMAT, "intent: unsupported format")
    _require("provider" not in intent and "supplier" not in intent, "intent: supplier-specific fields are prohibited")
    _require(intent.get("authority") == "human_owned", "intent: authority must be human_owned")

    profile_id = _require_id(intent.get("profile"), "intent.profile")
    _require(profile_id in indexes["profiles"], f"intent: unknown profile {profile_id}")
    _require(isinstance(intent.get("name"), str) and intent["name"], "intent: name absent")
    _require(isinstance(intent.get("style"), dict), "intent: style contract absent")
    _require(isinstance(intent.get("gameplay"), dict), "intent: gameplay contract absent")
    _require(isinstance(intent.get("budgets"), list) and intent["budgets"], "intent: target budgets absent")
    _require(isinstance(intent.get("acceptance"), dict), "intent: acceptance contract absent")
    _require(isinstance(intent.get("provenancePolicy"), dict), "intent: provenancePolicy absent")
    _require(isinstance(intent.get("licensePolicy"), dict), "intent: licensePolicy absent")
    _require(isinstance(intent.get("fallback"), dict), "intent: fallback absent")

    references = intent.get("references")
    _require(isinstance(references, list) and references, "intent: references absent")
    reference_ids: set[str] = set()
    for index, reference in enumerate(references):
        _require(isinstance(reference, dict), f"intent.references[{index}]: object required")
        ref_id = _require_id(reference.get("id"), f"intent.references[{index}].id")
        _require(ref_id not in reference_ids, f"intent: duplicate reference {ref_id}")
        reference_ids.add(ref_id)
        sha = reference.get("sha256")
        _require(isinstance(sha, str) and bool(SHA256_RE.fullmatch(sha)), f"{ref_id}: invalid sha256")
        _require(reference.get("rights") in {"owned", "licensed", "reference_only", "unknown"}, f"{ref_id}: rights state absent")

    gameplay = intent["gameplay"]
    parts = _unique_ids(gameplay.get("semanticParts"), "intent.gameplay.semanticParts")
    sockets = _unique_ids(gameplay.get("sockets"), "intent.gameplay.sockets")
    interactions = _unique_ids(gameplay.get("interactions"), "intent.gameplay.interactions")
    _require(parts, "intent: at least one semantic part is required")
    for interaction_id, interaction in interactions.items():
        part_id = interaction.get("partId")
        _require(part_id in parts, f"{interaction_id}: unknown part {part_id}")
        for socket_id in interaction.get("socketIds", []):
            _require(socket_id in sockets, f"{interaction_id}: unknown socket {socket_id}")
        _require(isinstance(interaction.get("verb"), str) and interaction["verb"], f"{interaction_id}: verb absent")
        _require(interaction.get("authority") == "game_law_external", f"{interaction_id}: interaction may not own game law")

    state_machine = gameplay.get("stateMachine")
    _require(isinstance(state_machine, dict), "intent: stateMachine absent")
    states = state_machine.get("states")
    _require(isinstance(states, list) and len(states) >= 2, "intent: state machine needs at least two states")
    _require(len(set(states)) == len(states), "intent: duplicate state-machine state")
    for transition in state_machine.get("transitions", []):
        _require(transition.get("from") in states, "intent: transition from unknown state")
        _require(transition.get("to") in states, "intent: transition to unknown state")
        _require(transition.get("authority") == "game_law_external", "intent: transition may not own game law")

    platform_ids: set[str] = set()
    for index, budget in enumerate(intent["budgets"]):
        _require(isinstance(budget, dict), f"intent.budgets[{index}]: object required")
        platform_id = _require_id(budget.get("platform"), f"intent.budgets[{index}].platform")
        _require(platform_id not in platform_ids, f"intent: duplicate budget platform {platform_id}")
        platform_ids.add(platform_id)
        limits = budget.get("limits")
        _require(isinstance(limits, dict) and limits, f"{platform_id}: limits absent")
        for name, value in limits.items():
            _require(isinstance(value, int) and not isinstance(value, bool) and value >= 0, f"{platform_id}.{name}: nonnegative integer required")

    required = intent["acceptance"].get("requiredGates")
    _require(isinstance(required, list), "intent: acceptance.requiredGates must be an array")
    profile_required = set(indexes["profiles"][profile_id]["requiredGates"])
    _require(set(required) == profile_required, "intent: required gates must exactly match the selected profile")
    _require(intent["acceptance"].get("aggregateScore") is None, "intent: aggregate scores are prohibited")

    computed = digest("assetint1", intent, omitted_keys={"intentId"})
    declared = intent.get("intentId")
    if declared is not None:
        _require(declared == computed, f"intent: identity mismatch, expected {computed}")
    return computed


def classify_qualification(qualification: Any, intent: Any, catalog: Any) -> dict[str, Any]:
    intent_id = validate_intent(intent, catalog)
    indexes = validate_catalog(catalog)
    _require(isinstance(qualification, dict), "qualification: object required")
    _require(qualification.get("format") == QUALIFICATION_FORMAT, "qualification: unsupported format")
    _require(qualification.get("intentId") == intent_id, "qualification: intent identity mismatch")
    _require(qualification.get("authority") == "evidence_only", "qualification: authority must be evidence_only")
    _require(qualification.get("aggregateScore") is None, "qualification: aggregate scores are prohibited")

    gate_rows = _unique_ids(qualification.get("gates"), "qualification.gates")
    required = intent["acceptance"]["requiredGates"]
    _require(set(gate_rows) == set(required), "qualification: gate set does not match intent")
    for gate_id, row in gate_rows.items():
        _require(row.get("state") in GATE_STATES, f"{gate_id}: invalid gate state")
        _require(isinstance(row.get("evidenceRefs"), list), f"{gate_id}: evidenceRefs must be an array")
        if row["state"] == "pass":
            _require(bool(row["evidenceRefs"]), f"{gate_id}: passing gate has no evidence")
        if indexes["gates"][gate_id]["hard"]:
            _require(row["state"] != "not_applicable", f"{gate_id}: hard gate cannot be not_applicable")

    states = {row["state"] for row in gate_rows.values()}
    if "fail" in states:
        disposition = "rejected"
    elif "open" in states:
        disposition = "held"
    elif "warn" in states:
        disposition = "pilot_only"
    else:
        human = gate_rows.get("human_acceptance", {}).get("state")
        disposition = "product_accepted" if human == "pass" else "engine_qualified"

    result = {
        "format": "axm-asset-qualification-disposition/1",
        "intentId": intent_id,
        "qualificationId": digest("assetqual1", qualification, omitted_keys={"qualificationId"}),
        "disposition": disposition,
        "failedGates": sorted(gate_id for gate_id, row in gate_rows.items() if row["state"] == "fail"),
        "openGates": sorted(gate_id for gate_id, row in gate_rows.items() if row["state"] == "open"),
        "warningGates": sorted(gate_id for gate_id, row in gate_rows.items() if row["state"] == "warn"),
        "authority": "classification_only",
    }
    return result


def compile_report(catalog: Any, intents: list[Any]) -> dict[str, Any]:
    indexes = validate_catalog(catalog)
    validated_intents = []
    for intent in intents:
        validated_intents.append(
            {
                "intentId": validate_intent(intent, catalog),
                "name": intent["name"],
                "profile": intent["profile"],
            }
        )

    providers_by_capability: dict[str, list[str]] = {capability_id: [] for capability_id in indexes["capabilities"]}
    qualified_by_capability: dict[str, list[str]] = {capability_id: [] for capability_id in indexes["capabilities"]}
    legal_review: list[str] = []
    for supplier_id, supplier in indexes["suppliers"].items():
        if supplier["license"]["status"] in {"unknown", "legal_review", "research_only"}:
            legal_review.append(supplier_id)
        for capability_id in supplier["capabilities"]:
            providers_by_capability[capability_id].append(supplier_id)
            if supplier["state"] in {"fixture_qualified", "engine_qualified"}:
                qualified_by_capability[capability_id].append(supplier_id)

    missing = sorted(
        capability_id
        for capability_id, rows in providers_by_capability.items()
        if indexes["capabilities"][capability_id]["providerRequired"] and not rows
    )
    single = sorted(capability_id for capability_id, rows in providers_by_capability.items() if len(rows) == 1)
    unqualified = sorted(capability_id for capability_id, rows in qualified_by_capability.items() if not rows)

    report = {
        "format": REPORT_FORMAT,
        "catalogId": digest("assetfloor1", catalog, omitted_keys={"catalogId"}),
        "authority": "measurement_only",
        "summary": {
            "gateCount": len(indexes["gates"]),
            "capabilityCount": len(indexes["capabilities"]),
            "profileCount": len(indexes["profiles"]),
            "supplierCount": len(indexes["suppliers"]),
            "intentCount": len(validated_intents),
            "openGapCount": sum(1 for row in indexes["gaps"].values() if row["state"] == "open"),
        },
        "intents": sorted(validated_intents, key=lambda row: row["intentId"]),
        "coverage": {
            "missingProviderCapabilities": missing,
            "singleProviderCapabilities": single,
            "noQualifiedProviderCapabilities": unqualified,
            "licenseReviewSuppliers": sorted(legal_review),
        },
        "gaps": [
            {
                "id": gap_id,
                "state": gap["state"],
                "firstExperiment": gap["firstExperiment"],
                "failureDefault": gap["failureDefault"],
            }
            for gap_id, gap in sorted(indexes["gaps"].items())
        ],
    }
    report["reportId"] = digest("assetfloorreport1", report, omitted_keys={"reportId"})
    return report


def _write_json(path: str | Path, value: Any) -> None:
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate")
    validate.add_argument("--catalog", required=True)
    validate.add_argument("--intent", action="append", default=[])

    report = sub.add_parser("report")
    report.add_argument("--catalog", required=True)
    report.add_argument("--intent", action="append", default=[])
    report.add_argument("--output", required=True)

    classify = sub.add_parser("classify")
    classify.add_argument("--catalog", required=True)
    classify.add_argument("--intent", required=True)
    classify.add_argument("--qualification", required=True)
    classify.add_argument("--output", required=True)

    args = parser.parse_args(argv)
    catalog = load_json(args.catalog)

    if args.command == "validate":
        validate_catalog(catalog)
        for path in args.intent:
            validate_intent(load_json(path), catalog)
        print("ASSET FLOOR VALID")
        return 0

    if args.command == "report":
        intents = [load_json(path) for path in args.intent]
        result = compile_report(catalog, intents)
        _write_json(args.output, result)
        print(result["reportId"])
        return 0

    intent = load_json(args.intent)
    qualification = load_json(args.qualification)
    result = classify_qualification(qualification, intent, catalog)
    _write_json(args.output, result)
    print(result["qualificationId"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
