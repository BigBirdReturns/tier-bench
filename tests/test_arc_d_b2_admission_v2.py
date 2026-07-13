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
    assert roles["additionalProperties"] is False


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
