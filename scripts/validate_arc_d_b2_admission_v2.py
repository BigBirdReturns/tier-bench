#!/usr/bin/env python3
"""Validate the ARC-D B2 admission-v2 *specification* fail closed.

This tool intentionally has no private/public/batch admission mode. The merged
amendment remains ADOPTED_PENDING_CUSTODY until the separately queued custody,
activation, preregistration, authenticated-audit, and exact-private-Git tooling
exists. Public hash shape alone can never close admission.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PARENT_REL = Path("data/oss-replay/arc_d_buffalo_pilot_v2/harvest_charter.json")
AMENDMENT_REL = Path("data/oss-replay/arc_d_buffalo_pilot_v2/harvest_charter_v2.json")
AMENDMENT_SCHEMA = ROOT / "schemas" / "arc_d_b2_admission_amendment.schema.json"
PARENT_SHA256 = "44306491048c792cf4e1a049d8e8059d8033f4f56bb73f8b821cf1483c20a16e"
SECTION_DIGESTS = {
    "sealed_evidence": "e0009163e4b7dbeef79772d5076c5a6ca32357e7c7a83096668fcc96d602f090",
    "grading_instruments": "eaba26ba0f19516bd8b7c1517cf9b5a9c021f94debb9d4b287ee0464833683e9",
    "packet_allowlist": "f91079aaaf411c7ce3a090e3390db67cdf532e205e59dbd472c44c3d1e289155",
    "packet_denylist": "7daacd26e4618e432a976c5358c7645a51cad70173f0441e8a9f8c613d629d1e",
    "rubric": "cfed83e68af612a0e799ed06fc4d0f9c0d64d546c74a55741ced83fb2eeb27ac",
    "prospective_harvest_gate": "d400acae4cd8b987877d2a7eec212992a770b3673ee2c129f137a63190ca31e7",
    "disagreement": "25bc81b08271ac3d5ba5de42de2fa875adb898597d6633e8d17bc1b0b5cef974",
}
AMENDMENT_SECTION_DIGESTS = {
    "scope": "bb22f3c472261a08961beeee3247ec2335fcde4cddd4aca823a242314e99a855",
    "activation": "00c96238a0eefcd039a4a5b2e62d8f8c4ae6c6416affd4e439d8522aabc2b09e",
    "versioning": "35c46c8e0431747d2415a9f74d05e8bed928916749bf9c6d1ed009aebc6a7814",
    "fresh_attempt": "bc5c62795bff7725c8dfd6ac70200f27457b9d2401d3756a9fa17736b5b4a04b",
    "packet_transport": "75b290d58a849f85f03b418f57cec5e6c4ce5fcfc74b39fc7e14c6a596d6862d",
    "custody": "f9c8a3a24f9557a278c67d19862cbd7bc76e52c233ae28f51b04321771ebe817",
    "admission_state_machine": "76c26ce81877c0ad804d5d75bd66b3386359419a497b21c52e0f47d9dcb8e591",
    "comparison_gate": "2420369e6bcf6881a42ab13ab9b0c4098ae5e43aa087b94cba734e00d4f25903",
    "implementation_gate": "c67e2f7b10ebe6119d2c9b28dfcf49d27671fe820725889740a98dcb302329d4",
    "historical_attempts": "09a2730a9e68dea9d0af1ca84b521d248863d81b06192950bf30e8d85cd805fd",
    "failure_default": "54af1fb98c93497189c67209cd35a31f81074d1ce35fabca5007aebda53f1555",
}
SCHEMAS = {
    "arc_d_b2_admission_amendment.schema.json": "https://tier-bench.local/schemas/arc_d_b2_admission_amendment.schema.json",
    "arc_d_b2_custody_profile.schema.json": "https://tier-bench.local/schemas/arc_d_b2_custody_profile.schema.json",
    "arc_d_b2_attempt_preregistration.schema.json": "https://tier-bench.local/schemas/arc_d_b2_attempt_preregistration.schema.json",
    "arc_d_b2_dispatch_ledger.schema.json": "https://tier-bench.local/schemas/arc_d_b2_dispatch_ledger.schema.json",
    "arc_d_b2_private_bundle_manifest.schema.json": "https://tier-bench.local/schemas/arc_d_b2_private_bundle_manifest.schema.json",
    "arc_d_b2_public_admission_receipt.schema.json": "https://tier-bench.local/schemas/arc_d_b2_public_admission_receipt.schema.json",
    "arc_d_b2_batch_admission_receipt.schema.json": "https://tier-bench.local/schemas/arc_d_b2_batch_admission_receipt.schema.json",
}
PUBLIC_FORBIDDEN_KEYS = {
    "atomic_findings", "behavior_claim", "regression_test", "residue",
    "response_spans", "rationale", "session_id", "telemetry", "raw_grade",
    "grade_payload", "response_disposition",
}


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate JSON object key")
        out[key] = value
    return out


def _loads(data: bytes) -> Any:
    return json.loads(data.decode("utf-8"), object_pairs_hook=_strict_pairs)


def _load(path: Path) -> Any:
    return _loads(path.read_bytes())


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _git_blob(rel: Path, warnings: list[str] | None = None) -> bytes:
    proc = subprocess.run(
        ["git", "cat-file", "blob", f"HEAD:{rel.as_posix()}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if proc.returncode == 0:
        return proc.stdout
    if warnings is not None:
        warnings.append(f"canonical Git blob unavailable; using LF-normalized working tree for {rel.as_posix()}")
    return (ROOT / rel).read_bytes().replace(b"\r\n", b"\n")


def _walk_keys(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _resolve_ref(root: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise ValueError("only local schema references are supported")
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def schema_errors(value: Any, schema: dict[str, Any], *, label: str = "value") -> list[str]:
    """Validate the JSON-Schema subset used by the frozen admission specs."""
    errors: list[str] = []
    root = schema

    def visit(instance: Any, rule: dict[str, Any], path: str) -> None:
        if "$ref" in rule:
            visit(instance, _resolve_ref(root, rule["$ref"]), path)
            return
        if "const" in rule and instance != rule["const"]:
            errors.append(f"{path}: const mismatch")
        if "enum" in rule and instance not in rule["enum"]:
            errors.append(f"{path}: enum mismatch")
        expected = rule.get("type")
        type_ok = True
        if expected == "object":
            type_ok = isinstance(instance, dict)
        elif expected == "array":
            type_ok = isinstance(instance, list)
        elif expected == "string":
            type_ok = isinstance(instance, str)
        elif expected == "integer":
            type_ok = isinstance(instance, int) and not isinstance(instance, bool)
        elif expected == "boolean":
            type_ok = isinstance(instance, bool)
        if not type_ok:
            errors.append(f"{path}: type mismatch")
            return
        if isinstance(instance, dict):
            required = set(rule.get("required", []))
            missing = required - set(instance)
            if missing:
                errors.append(f"{path}: required fields missing")
            properties = rule.get("properties", {})
            if rule.get("additionalProperties") is False and set(instance) - set(properties):
                errors.append(f"{path}: additional properties forbidden")
            for key, child in instance.items():
                if key in properties:
                    visit(child, properties[key], f"{path}.{key}")
        elif isinstance(instance, list):
            if len(instance) < rule.get("minItems", 0):
                errors.append(f"{path}: too few items")
            if "maxItems" in rule and len(instance) > rule["maxItems"]:
                errors.append(f"{path}: too many items")
            if rule.get("uniqueItems") and len({_canonical_json(x) for x in instance}) != len(instance):
                errors.append(f"{path}: duplicate items")
            if "items" in rule:
                for index, child in enumerate(instance):
                    visit(child, rule["items"], f"{path}[{index}]")
        elif isinstance(instance, str):
            if len(instance) < rule.get("minLength", 0):
                errors.append(f"{path}: string too short")
            if "maxLength" in rule and len(instance) > rule["maxLength"]:
                errors.append(f"{path}: string too long")
            if "pattern" in rule and re.fullmatch(rule["pattern"], instance) is None:
                errors.append(f"{path}: pattern mismatch")
            if rule.get("format") == "date-time":
                try:
                    parsed = datetime.fromisoformat(instance.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        raise ValueError
                except ValueError:
                    errors.append(f"{path}: invalid date-time")
        elif isinstance(instance, int) and not isinstance(instance, bool):
            if "minimum" in rule and instance < rule["minimum"]:
                errors.append(f"{path}: below minimum")

    visit(value, schema, label)
    return errors


def validate_static() -> list[str]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        parent_bytes = _git_blob(PARENT_REL, warnings)
        parent = _loads(parent_bytes)
        amendment_worktree_bytes = (ROOT / AMENDMENT_REL).read_bytes().replace(b"\r\n", b"\n")
        amendment_git_bytes = _git_blob(AMENDMENT_REL, warnings)
        if amendment_worktree_bytes != amendment_git_bytes:
            warnings.append("working-tree amendment differs from the canonical HEAD Git blob; development validation uses working-tree bytes")
        amendment = _loads(amendment_worktree_bytes)
        amendment_schema = _load(AMENDMENT_SCHEMA)
    except Exception as exc:
        validate_static.last_warnings = warnings
        return [f"governing JSON is malformed or duplicate-keyed: {type(exc).__name__}"]
    if _sha(parent_bytes) != PARENT_SHA256:
        validate_static.last_warnings = warnings
        return ["parent charter canonical Git blob hash changed"]
    errors.extend(schema_errors(amendment, amendment_schema, label="amendment"))
    for section, expected in AMENDMENT_SECTION_DIGESTS.items():
        if _sha(_canonical_json(amendment.get(section))) != expected:
            errors.append(f"amendment frozen section changed: {section}")
    authority = amendment.get("parent_authority", {})
    if authority.get("canonical_git_blob_sha256") != PARENT_SHA256:
        errors.append("amendment does not bind the ratified parent charter")
    if authority.get("substantive_rules_changed") is not False:
        errors.append("amendment must declare zero substantive rule changes")
    if authority.get("does_not_reclassify_prior_attempts") is not True:
        errors.append("amendment must forbid retroactive admission")
    if authority.get("imported_section_sha256") != SECTION_DIGESTS:
        errors.append("declared imported-section digest set changed")
    for section, expected in SECTION_DIGESTS.items():
        if _sha(_canonical_json(parent.get(section))) != expected:
            errors.append(f"parent substantive section changed: {section}")
    fresh = amendment.get("fresh_attempt", {})
    if fresh.get("required_sessions") != 6 or fresh.get("maximum_dispatches_per_lane_item") != 1:
        errors.append("fresh attempt must be exactly six single-dispatch sessions")
    if fresh.get("prior_attempts_may_be_admitted") is not False:
        errors.append("prior attempts may not enter admission v2")
    transport = amendment.get("packet_transport", {})
    if transport.get("new_packet_exporter_required") is not False or "ratified v1 packet format" not in transport.get("grader_visible_packet", ""):
        errors.append("grader-visible packet must remain the exact v1 format")
    gate = amendment.get("implementation_gate", {})
    if gate.get("state_at_amendment_merge") != "SPECIFICATION_ONLY_NOT_OPERATIONAL" or gate.get("dispatch_before_all_components_merge") != "FORBIDDEN":
        errors.append("amendment merge must not activate operational admission")
    for filename, schema_id in SCHEMAS.items():
        try:
            schema = _load(ROOT / "schemas" / filename)
        except Exception:
            errors.append(f"{filename}: malformed or duplicate-keyed")
            continue
        if schema.get("$id") != schema_id or schema.get("type") != "object" or schema.get("additionalProperties") is not False:
            errors.append(f"{filename}: schema identity or fail-closed root changed")
    public_schema = _load(ROOT / "schemas" / "arc_d_b2_public_admission_receipt.schema.json")
    if PUBLIC_FORBIDDEN_KEYS.intersection(_walk_keys(public_schema.get("properties", {}))):
        errors.append("public receipt schema exposes content-bearing fields")
    validate_static.last_warnings = warnings
    return errors


validate_static.last_warnings = []


def main() -> int:
    if len(sys.argv) != 1:
        print(
            "ERROR: operational admission modes are intentionally unavailable until ARC-D-B2-CUSTODY-V2 merges",
            file=sys.stderr,
        )
        return 2
    errors = validate_static()
    for warning in validate_static.last_warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("OK: ARC-D B2 admission-v2 amendment validates; draft operational interfaces remain disabled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
