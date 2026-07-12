#!/usr/bin/env python3
"""Validate the frozen ARC-D B2 charter without reading response text."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V2 = ROOT / "data" / "oss-replay" / "arc_d_buffalo_pilot_v2"
CHARTER = V2 / "harvest_charter.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate() -> list[str]:
    errors: list[str] = []
    charter = _json(CHARTER)
    contract = _json(V2 / "contract.json")
    admin = _json(V2 / "administration_manifest.json")

    if charter.get("state") != "ratification_candidate":
        errors.append("charter state must remain ratification_candidate in-file")
    if charter.get("activation", {}).get("before_event") != "proposal_only":
        errors.append("pre-merge state must be proposal_only")
    if charter.get("scope", {}).get("rung") != "B2_SOURCE_CASE_REVIEW":
        errors.append("charter may authorize only B2 source-case review")
    if not charter.get("rubric", {}).get("no_harvest_at_b2"):
        errors.append("B2 must not mint HARVEST")
    b4 = charter.get("prospective_harvest_gate", {})
    if b4.get("state_after_activation") != "adopted_not_satisfied":
        errors.append("prospective B4 gate must be adopted but unsatisfied")
    if b4.get("design", {}).get("replicates_per_arm") != 3:
        errors.append("B4 must freeze K=3 per arm")
    crossing = b4.get("decision_rule", {}).get("arm_a_0_of_3_and_arm_b_3_of_3")
    if crossing != "TRANSFER_VALIDATED_AND_ONE_HARVEST":
        errors.append("B4 must require the exact 0/3 to 3/3 crossing")
    if contract.get("observed_run_summary", {}).get("graded_observations") != 0:
        errors.append("sealed contract must remain historically ungraded")

    expected_receipts = {
        row["path"]: row["sha256"]
        for row in admin.get("artifacts", [])
        if row["path"].endswith("administration_receipt.json")
        and row["path"].startswith("runs/")
    }
    rows = charter.get("sealed_evidence", {}).get("responses", [])
    if len(rows) != 3 or len({row.get("item_id") for row in rows}) != 3:
        errors.append("charter must bind exactly three distinct responses")

    for row in rows:
        rel = row.get("administration_receipt", "")
        prefix = "data/oss-replay/arc_d_buffalo_pilot_v2/"
        if not rel.startswith(prefix):
            errors.append(f"{row.get('item_id')}: receipt path escapes v2")
            continue
        manifest_rel = rel[len(prefix):]
        receipt = V2 / manifest_rel
        if not receipt.is_file():
            errors.append(f"{row.get('item_id')}: receipt missing")
            continue
        expected_receipt_hash = expected_receipts.get(manifest_rel)
        if row.get("administration_receipt_sha256") != expected_receipt_hash:
            errors.append(f"{row.get('item_id')}: receipt hash not manifest-bound")
        data = _json(receipt)
        for key in ("item_id", "response_sha256", "response_bytes"):
            if row.get(key) != data.get(key):
                errors.append(f"{row.get('item_id')}: {key} differs from receipt")
        if row.get("prompt_sha256") != data.get("v1_prompt_sha256"):
            errors.append(f"{row.get('item_id')}: prompt hash differs from receipt")
        if data.get("scientific_state") != "SEALED_RESPONSE_UNADJUDICATED":
            errors.append(f"{row.get('item_id')}: response is not sealed/unadjudicated")
        if data.get("graded") is not False or data.get("harvest_gate_applied") is not False:
            errors.append(f"{row.get('item_id')}: historical receipt was mutated")

    instruments = charter.get("grading_instruments", [])
    if {row.get("provider_lineage") for row in instruments} != {"openai", "anthropic"}:
        errors.append("grading requires two named provider lineages")
    if charter.get("disagreement", {}).get("automatic_averaging") is not False:
        errors.append("disagreements must never be averaged")
    if charter.get("rubric_author", {}).get("may_grade_under_this_charter") is not False:
        errors.append("rubric-authoring session must be barred from grading")

    required_receipt = set(charter.get("receipt_requirements", []))
    for field in ("charter_sha256", "packet_sha256", "response_sha256", "raw_grade_sha256"):
        if field not in required_receipt:
            errors.append(f"receipt requirement missing: {field}")
    schemas = charter.get("receipt_schemas", {})
    expected_schema_ids = {
        "grade": "https://tier-bench.local/schemas/arc_d_b2_grade_receipt.schema.json",
        "comparison": "https://tier-bench.local/schemas/arc_d_b2_comparison_receipt.schema.json",
    }
    for name, expected_id in expected_schema_ids.items():
        path = ROOT / schemas.get(name, "")
        if not path.is_file():
            errors.append(f"{name} receipt schema missing")
            continue
        schema = _json(path)
        if schema.get("$id") != expected_id or schema.get("additionalProperties") is not False:
            errors.append(f"{name} receipt schema is not the frozen fail-closed schema")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"OK: {CHARTER.relative_to(ROOT)} sha256={_sha256(CHARTER)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
