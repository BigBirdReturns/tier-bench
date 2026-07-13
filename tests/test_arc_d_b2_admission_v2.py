"""Admission-v2 specification tests; no grader or response bytes are opened."""
from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "admission_v2", ROOT / "scripts" / "validate_arc_d_b2_admission_v2.py"
)
validator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(validator)


def test_static_spec_imports_v1_without_substantive_change():
    assert validator.validate_static() == []


def test_amendment_schema_rejects_added_override_and_weakened_gate():
    amendment = validator._load(ROOT / validator.AMENDMENT_REL)
    schema = validator._load(validator.AMENDMENT_SCHEMA)
    mutated = copy.deepcopy(amendment)
    mutated["override"] = "admit old grades"
    assert any("additional properties" in error for error in validator.schema_errors(mutated, schema))
    mutated = copy.deepcopy(amendment)
    mutated["implementation_gate"]["dispatch_before_all_components_merge"] = "PERMITTED"
    assert any("const mismatch" in error for error in validator.schema_errors(mutated, schema))


def test_critical_amendment_law_is_digest_frozen_not_merely_nonempty():
    amendment = validator._load(ROOT / validator.AMENDMENT_REL)
    for section, expected in validator.AMENDMENT_SECTION_DIGESTS.items():
        assert validator._sha(validator._canonical_json(amendment[section])) == expected
    weakened = copy.deepcopy(amendment)
    weakened["activation"]["active_only_when"] = "nothing"
    assert validator._sha(validator._canonical_json(weakened["activation"])) != validator.AMENDMENT_SECTION_DIGESTS["activation"]
    weakened = copy.deepcopy(amendment)
    weakened["implementation_gate"]["required_later_merged_components"] = ["x"] * 7
    assert validator._sha(validator._canonical_json(weakened["implementation_gate"])) != validator.AMENDMENT_SECTION_DIGESTS["implementation_gate"]
    weakened = copy.deepcopy(amendment)
    weakened["custody"]["public_receipts_must_exclude"] = ["x"]
    assert validator._sha(validator._canonical_json(weakened["custody"])) != validator.AMENDMENT_SECTION_DIGESTS["custody"]


def test_schema_engine_enforces_nested_types_enums_patterns_and_unique_items():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["mode", "ids"],
        "properties": {
            "mode": {"enum": ["SAFE"]},
            "ids": {
                "type": "array",
                "minItems": 2,
                "uniqueItems": True,
                "items": {"type": "string", "pattern": "^[a-z]{3}$"},
            },
        },
    }
    bad = {"mode": "UNSAFE", "ids": ["abc", "abc"], "extra": True}
    errors = validator.schema_errors(bad, schema)
    assert any("enum mismatch" in error for error in errors)
    assert any("duplicate items" in error for error in errors)
    assert any("additional properties" in error for error in errors)


def test_strict_json_rejects_duplicate_keys():
    try:
        validator._loads(b'{"state":"SAFE","state":"OVERRIDE"}')
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate JSON keys must fail closed")


def test_packet_transport_reuses_exact_v1_grader_scope():
    amendment = validator._load(ROOT / validator.AMENDMENT_REL)
    transport = amendment["packet_transport"]
    assert transport["new_packet_exporter_required"] is False
    assert "ratified v1 packet format" in transport["grader_visible_packet"]
    assert "same item hash in both lanes" in transport["grader_visible_packet"]
    assert "validate_arc_d_b2_packet.py" in transport["required_validation"]
    assert "Outside grader scope" in (ROOT / "docs" / "arc-d-b2-admission-v2.md").read_text(encoding="utf-8")


def test_public_schema_has_no_content_fields_and_bounds_public_strings():
    schema = validator._load(ROOT / "schemas" / "arc_d_b2_public_admission_receipt.schema.json")
    keys = set(validator._walk_keys(schema["properties"]))
    assert not validator.PUBLIC_FORBIDDEN_KEYS.intersection(keys)
    surface = schema["properties"]["instrument"]["properties"]["surface"]
    verifier = schema["properties"]["audit"]["properties"]["verifier_id"]
    assert "pattern" in surface and "maxLength" not in surface  # pattern itself caps at 128
    assert "127" in surface["pattern"] and "127" in verifier["pattern"]
    assert "maintainer_merge_attestation" not in schema["properties"]["audit"]["properties"]["authentication"]["enum"]


def test_custody_profile_bars_rubric_author_and_instruments_by_attestation():
    schema = validator._load(ROOT / "schemas" / "arc_d_b2_custody_profile.schema.json")
    roles = schema["properties"]["roles"]
    for key in (
        "verifier_is_not_rubric_author",
        "verifier_is_not_grading_instrument",
        "verifier_is_administration_only",
    ):
        assert key in roles["required"]
        assert roles["properties"][key]["const"] is True
    for key in ("custodian_is_verifier", "coordinator_is_verifier"):
        assert key in roles["required"]
        assert roles["properties"][key]["const"] is False
    assert "verifier_lineage" in roles["required"]
    assert "verifier_lineage_conflicts" in roles["required"]
    assert roles["additionalProperties"] is False


def test_all_receipts_bind_preregistration_and_dispatch_ledger():
    required_bindings = {
        "preregistration_manifest_sha256",
        "preregistration_commit",
        "dispatch_ledger_sha256",
        "dispatch_ledger_commit",
    }
    for name in (
        "arc_d_b2_private_bundle_manifest.schema.json",
        "arc_d_b2_public_admission_receipt.schema.json",
        "arc_d_b2_batch_admission_receipt.schema.json",
    ):
        schema = validator._load(ROOT / "schemas" / name)
        assert required_bindings.issubset(schema["required"])


def test_batch_receipt_is_an_exact_keyed_three_by_two_grid():
    schema = validator._load(ROOT / "schemas" / "arc_d_b2_batch_admission_receipt.schema.json")
    receipt_ref = {"path": "receipts/a.json", "sha256": "a" * 64}
    lane = {
        "attrs_1567_setattr_mro": receipt_ref,
        "httpx_3614_base_url_query": receipt_ref,
        "httpx_3221_ipv6_no_proxy": receipt_ref,
    }
    receipt = {
        "schema": "tier-bench/arc-d-b2-batch-admission-receipt@2",
        "protocol_id": "arc_d_buffalo_pilot_v2",
        "attempt_id": "arc-d-b2-v2-test",
        "amendment_sha256": "a" * 64,
        "custody_profile_sha256": "b" * 64,
        "activation_commit": "c" * 40,
        "preregistration_manifest_sha256": "d" * 64,
        "preregistration_commit": "e" * 40,
        "dispatch_ledger_sha256": "f" * 64,
        "dispatch_ledger_commit": "1" * 40,
        "required_receipt_count": 6,
        "receipts": {"grade_a": lane, "grade_b": lane},
        "seal": {
            "last_private_sealed_at": "2026-07-13T00:00:00Z",
            "first_public_disclosure_at": "2026-07-13T00:01:00Z",
            "all_private_before_public": True,
        },
        "attempt_failures": 0,
        "state": "PROPOSED_FOR_ATOMIC_ADMISSION",
    }
    assert validator.schema_errors(receipt, schema) == []
    duplicated_six = copy.deepcopy(receipt)
    duplicated_six["receipts"] = [receipt_ref] * 6
    assert any("type mismatch" in error for error in validator.schema_errors(duplicated_six, schema))
    missing_cell = copy.deepcopy(receipt)
    del missing_cell["receipts"]["grade_b"]["httpx_3221_ipv6_no_proxy"]
    assert any("required fields missing" in error for error in validator.schema_errors(missing_cell, schema))


def test_preregistration_fixes_one_packet_per_item_before_dispatch():
    schema = validator._load(ROOT / "schemas" / "arc_d_b2_attempt_preregistration.schema.json")
    items = schema["properties"]["items"]
    assert items["additionalProperties"] is False
    assert set(items["required"]) == {
        "attrs_1567_setattr_mro",
        "httpx_3614_base_url_query",
        "httpx_3221_ipv6_no_proxy",
    }
    assert schema["properties"]["maximum_dispatches_per_lane_item"]["const"] == 1
    assert schema["$defs"]["item"]["properties"]["same_packet_required_in_both_lanes"]["const"] is True


def test_public_dispatch_ledger_represents_failed_attempts():
    schema = validator._load(ROOT / "schemas" / "arc_d_b2_dispatch_ledger.schema.json")
    failed = {"dispatch_index": 1, "outcome": "PROVIDER_FAILURE", "event_commitment_sha256": "a" * 64}
    lane = {
        "attrs_1567_setattr_mro": failed,
        "httpx_3614_base_url_query": failed,
        "httpx_3221_ipv6_no_proxy": failed,
    }
    ledger = {
        "schema": "tier-bench/arc-d-b2-dispatch-ledger@2",
        "protocol_id": "arc_d_buffalo_pilot_v2",
        "attempt_id": "arc-d-b2-v2-failed",
        "preregistration_manifest_sha256": "b" * 64,
        "preregistration_commit": "c" * 40,
        "cells": {"grade_a": lane, "grade_b": lane},
        "state": "SEALED_PARTIAL_UNPAIRED",
    }
    assert validator.schema_errors(ledger, schema) == []


def test_parser_clarification_does_not_reclassify_prior_outcomes():
    amendment = validator._load(ROOT / validator.AMENDMENT_REL)
    effect = amendment["scope"]["clarification_historical_effect"]
    assert "no historical Grade B outcome is reclassified" in effect
    assert "remains invalid" in effect


def test_operational_modes_fail_closed_until_custody_task_merges():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_arc_d_b2_admission_v2.py"), "--public-receipt", "fake.json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "intentionally unavailable" in proc.stderr
    assert "ADMITTED" not in proc.stdout


def _run_standalone() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok  {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return int(failed > 0)


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
