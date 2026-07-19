#!/usr/bin/env python3
"""Test suite for work_receipt_contract_v1 validator.

Validates:
- 1 valid two-receipt chain
- 7 card-frozen rejection classes with named machine-readable reasons
- KERNEL-REFUTATION-DISPOSITION-1 batch-1 additions: SCHEMA_VIOLATION
  (schema.json wiring, P1-16/P2-5), SCOPE_UNBOUND (P1-20), predecessor cycle
  detection and duplicate-detection attempt_id scoping (P1-21/P1-22),
  string-encoded external-ref overrides (P1-23), scheduler-effect
  self-reference and rejected-unlock rules (P1-24), and the ERROR+PASS closed
  truth table (P2-4)
- No model calls, no network
"""

import json
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from validate import WorkReceiptValidator, ValidationResult


def load_fixture(filename: str) -> dict:
    """Load a fixture JSON file."""
    fixture_path = Path(__file__).parent / "fixtures" / filename
    with open(fixture_path, 'r') as f:
        return json.load(f)


def test_valid_chain():
    """Test 1: Valid two-receipt chain."""
    print("TEST 1: Valid two-receipt chain...")
    validator = WorkReceiptValidator()

    receipt_1 = load_fixture("receipt_1_valid.json")
    receipt_2 = load_fixture("receipt_2_valid.json")

    # Validate receipt_1 (root)
    result_1 = validator.validate_receipt(receipt_1)
    assert result_1.valid, f"receipt_1 should be valid: {result_1.reason}"
    print(f"  [OK] receipt_1 valid (root, no predecessors)")

    # Validate receipt_2 with receipt_1 as known
    known_receipts = {
        "ee858f7a4170c7a77f0b92f121fc54fbad31c59df276b0f75136b9d237a7dba2": receipt_1
    }
    result_2 = validator.validate_receipt(receipt_2, known_receipts=known_receipts)
    assert result_2.valid, f"receipt_2 should be valid: {result_2.reason}"
    print(f"  [OK] receipt_2 valid (references receipt_1)")

    print("  [OK] PASS: Valid chain validated\n")
    return 1  # 1 chain tested


def test_rejection_orphaned_decision():
    """Test 2: Rejection class 1 - ORPHANED_DECISION."""
    print("TEST 2: ORPHANED_DECISION rejection...")
    validator = WorkReceiptValidator()

    receipt = load_fixture("rejection_orphaned_decision.json")
    result = validator.validate_receipt(receipt)

    assert not result.valid, "Should reject"
    assert result.rejection_class == "ORPHANED_DECISION", \
        f"Expected ORPHANED_DECISION, got {result.rejection_class}"
    print(f"  [OK] PASS: {result.rejection_class} ({result.reason})\n")
    return 1


def test_rejection_missing_content_binding():
    """Test 3: Rejection class 2 - MISSING_CONTENT_BINDING."""
    print("TEST 3: MISSING_CONTENT_BINDING rejection...")
    validator = WorkReceiptValidator()

    receipt = load_fixture("rejection_missing_content_binding.json")
    result = validator.validate_receipt(receipt)

    assert not result.valid, "Should reject"
    assert result.rejection_class == "MISSING_CONTENT_BINDING", \
        f"Expected MISSING_CONTENT_BINDING, got {result.rejection_class}"
    print(f"  [OK] PASS: {result.rejection_class} ({result.reason})\n")
    return 1


def test_rejection_contradictory_terminal_states():
    """Test 4: Rejection class 3 - CONTRADICTORY_TERMINAL_STATES."""
    print("TEST 4: CONTRADICTORY_TERMINAL_STATES rejection...")
    validator = WorkReceiptValidator()

    receipt = load_fixture("rejection_contradictory_terminal_states.json")
    result = validator.validate_receipt(receipt)

    assert not result.valid, "Should reject"
    assert result.rejection_class == "CONTRADICTORY_TERMINAL_STATES", \
        f"Expected CONTRADICTORY_TERMINAL_STATES, got {result.rejection_class}"
    print(f"  [OK] PASS: {result.rejection_class} ({result.reason})\n")
    return 1


def test_rejection_duplicate_terminal_receipt():
    """Test 5: Rejection class 4 - DUPLICATE_TERMINAL_RECEIPT."""
    print("TEST 5: DUPLICATE_TERMINAL_RECEIPT rejection...")
    validator = WorkReceiptValidator()

    receipt = load_fixture("rejection_duplicate_terminal_receipt.json")

    # Create a second receipt with same attempt_id and terminal_state
    receipt_dup = json.loads(json.dumps(receipt))
    receipt_dup["patch_sha256"] = "f1f2f3f4f5f6f7f8f9fafbfcfdfefff0f1f2f3f4f5f6f7f8f9fafbfcfdfefff0"

    # Pass both receipts to validator
    all_receipts = [receipt, receipt_dup]
    result = validator.validate_receipt(receipt_dup, all_receipts_for_attempt=all_receipts)

    assert not result.valid, "Should reject duplicate terminal receipt"
    assert result.rejection_class == "DUPLICATE_TERMINAL_RECEIPT", \
        f"Expected DUPLICATE_TERMINAL_RECEIPT, got {result.rejection_class}"
    print(f"  [OK] PASS: {result.rejection_class} ({result.reason})\n")
    return 1


def test_rejection_unverified_predecessor():
    """Test 6: Rejection class 5 - UNVERIFIED_PREDECESSOR."""
    print("TEST 6: UNVERIFIED_PREDECESSOR rejection...")
    validator = WorkReceiptValidator()

    receipt = load_fixture("rejection_unverified_predecessor.json")

    # Pass empty known_receipts so predecessor is not found
    result = validator.validate_receipt(receipt, known_receipts={})

    assert not result.valid, "Should reject unverified predecessor"
    assert result.rejection_class == "UNVERIFIED_PREDECESSOR", \
        f"Expected UNVERIFIED_PREDECESSOR, got {result.rejection_class}"
    print(f"  [OK] PASS: {result.rejection_class} ({result.reason})\n")
    return 1


def test_rejection_malformed_scheduler_effects():
    """Test 7: Rejection class 6 - MALFORMED_SCHEDULER_EFFECTS."""
    print("TEST 7: MALFORMED_SCHEDULER_EFFECTS rejection...")

    # Create validator with known task_ids
    known_task_ids = ["task_001", "task_002", "task_003", "task_004", "task_005"]
    validator = WorkReceiptValidator(all_task_ids=known_task_ids)

    receipt = load_fixture("rejection_malformed_scheduler_effects.json")
    result = validator.validate_receipt(receipt)

    assert not result.valid, "Should reject malformed scheduler effects"
    assert result.rejection_class == "MALFORMED_SCHEDULER_EFFECTS", \
        f"Expected MALFORMED_SCHEDULER_EFFECTS, got {result.rejection_class}"
    print(f"  [OK] PASS: {result.rejection_class} ({result.reason})\n")
    return 1


def test_rejection_external_override_verdict():
    """Test 8: Rejection class 7 - EXTERNAL_OVERRIDE_VERDICT."""
    print("TEST 8: EXTERNAL_OVERRIDE_VERDICT rejection...")
    validator = WorkReceiptValidator()

    receipt = load_fixture("rejection_external_override_verdict.json")
    result = validator.validate_receipt(receipt)

    assert not result.valid, "Should reject external override verdict"
    assert result.rejection_class == "EXTERNAL_OVERRIDE_VERDICT", \
        f"Expected EXTERNAL_OVERRIDE_VERDICT, got {result.rejection_class}"
    print(f"  [OK] PASS: {result.rejection_class} ({result.reason})\n")
    return 1


def test_rejection_schema_missing_required_field():
    """Test 9: SCHEMA_VIOLATION - required field absent (P1-16)."""
    print("TEST 9: SCHEMA_VIOLATION (missing required field) rejection...")
    validator = WorkReceiptValidator()

    receipt = load_fixture("rejection_schema_missing_required_field.json")
    result = validator.validate_receipt(receipt)

    assert not result.valid, "Should reject receipt missing a required field"
    assert result.rejection_class == "SCHEMA_VIOLATION", \
        f"Expected SCHEMA_VIOLATION, got {result.rejection_class}"
    print(f"  [OK] PASS: {result.rejection_class} ({result.reason})\n")
    return 1


def test_rejection_schema_unknown_property():
    """Test 10: SCHEMA_VIOLATION - additionalProperties:false at root (P1-16)."""
    print("TEST 10: SCHEMA_VIOLATION (unknown property) rejection...")
    validator = WorkReceiptValidator()

    receipt = load_fixture("rejection_schema_unknown_property.json")
    result = validator.validate_receipt(receipt)

    assert not result.valid, "Should reject receipt with an undeclared property"
    assert result.rejection_class == "SCHEMA_VIOLATION", \
        f"Expected SCHEMA_VIOLATION, got {result.rejection_class}"
    print(f"  [OK] PASS: {result.rejection_class} ({result.reason})\n")
    return 1


def test_rejection_schema_runtime_evidence_incomplete():
    """Test 11: SCHEMA_VIOLATION - nested required field in runtime_evidence (P2-5)."""
    print("TEST 11: SCHEMA_VIOLATION (runtime_evidence incomplete) rejection...")
    validator = WorkReceiptValidator()

    receipt = load_fixture("rejection_schema_runtime_evidence_incomplete.json")
    result = validator.validate_receipt(receipt)

    assert not result.valid, "Should reject runtime_evidence missing model_used"
    assert result.rejection_class == "SCHEMA_VIOLATION", \
        f"Expected SCHEMA_VIOLATION, got {result.rejection_class}"
    print(f"  [OK] PASS: {result.rejection_class} ({result.reason})\n")
    return 1


def test_rejection_scope_unbound_path_traversal():
    """Test 12: SCOPE_UNBOUND - allowed_paths escapes via '..' (P1-20)."""
    print("TEST 12: SCOPE_UNBOUND (path traversal) rejection...")
    validator = WorkReceiptValidator()

    receipt = load_fixture("rejection_scope_unbound_path_traversal.json")
    result = validator.validate_receipt(receipt)

    assert not result.valid, "Should reject scope.allowed_paths containing '..'"
    assert result.rejection_class == "SCOPE_UNBOUND", \
        f"Expected SCOPE_UNBOUND, got {result.rejection_class}"
    print(f"  [OK] PASS: {result.rejection_class} ({result.reason})\n")
    return 1


def test_rejection_external_override_verdict_string_encoded():
    """Test 13: EXTERNAL_OVERRIDE_VERDICT - string-encoded override (P1-23)."""
    print("TEST 13: EXTERNAL_OVERRIDE_VERDICT (string-encoded) rejection...")
    validator = WorkReceiptValidator()

    receipt = load_fixture("rejection_external_override_verdict_string_encoded.json")
    result = validator.validate_receipt(receipt)

    assert not result.valid, "Should reject a string-encoded verdict override"
    assert result.rejection_class == "EXTERNAL_OVERRIDE_VERDICT", \
        f"Expected EXTERNAL_OVERRIDE_VERDICT, got {result.rejection_class}"
    print(f"  [OK] PASS: {result.rejection_class} ({result.reason})\n")
    return 1


def test_rejection_scheduler_effect_self_reference():
    """Test 14: MALFORMED_SCHEDULER_EFFECTS - receipt unlocks its own task_id (P1-24)."""
    print("TEST 14: MALFORMED_SCHEDULER_EFFECTS (self-reference) rejection...")
    validator = WorkReceiptValidator()

    receipt = load_fixture("rejection_scheduler_effect_self_reference.json")
    result = validator.validate_receipt(receipt)

    assert not result.valid, "Should reject a receipt naming itself in unlocks"
    assert result.rejection_class == "MALFORMED_SCHEDULER_EFFECTS", \
        f"Expected MALFORMED_SCHEDULER_EFFECTS, got {result.rejection_class}"
    print(f"  [OK] PASS: {result.rejection_class} ({result.reason})\n")
    return 1


def test_rejection_scheduler_effect_rejected_unlock():
    """Test 15: MALFORMED_SCHEDULER_EFFECTS - REJECTED receipt may not unlock (P1-24)."""
    print("TEST 15: MALFORMED_SCHEDULER_EFFECTS (rejected-unlock) rejection...")
    validator = WorkReceiptValidator()

    receipt = json.loads(json.dumps(load_fixture("receipt_1_valid.json")))
    receipt["terminal_state"] = "REJECTED"
    receipt["referee_result"] = "FAIL"
    # unlocks inherited non-empty from the base fixture

    result = validator.validate_receipt(receipt)

    assert not result.valid, "A REJECTED receipt must not unlock downstream work"
    assert result.rejection_class == "MALFORMED_SCHEDULER_EFFECTS", \
        f"Expected MALFORMED_SCHEDULER_EFFECTS, got {result.rejection_class}"
    print(f"  [OK] PASS: {result.rejection_class} ({result.reason})\n")
    return 1


def test_rejection_contradictory_error_with_pass():
    """Test 16: CONTRADICTORY_TERMINAL_STATES - ERROR paired with PASS (P2-4)."""
    print("TEST 16: CONTRADICTORY_TERMINAL_STATES (ERROR+PASS) rejection...")
    validator = WorkReceiptValidator()

    receipt = json.loads(json.dumps(load_fixture("receipt_1_valid.json")))
    receipt["terminal_state"] = "ERROR"
    receipt["referee_result"] = "PASS"

    result = validator.validate_receipt(receipt)

    assert not result.valid, "terminal_state=ERROR must never carry referee_result=PASS"
    assert result.rejection_class == "CONTRADICTORY_TERMINAL_STATES", \
        f"Expected CONTRADICTORY_TERMINAL_STATES, got {result.rejection_class}"
    print(f"  [OK] PASS: {result.rejection_class} ({result.reason})\n")
    return 1


def test_duplicate_terminal_receipt_ignores_unrelated_attempt():
    """Test 17: DUPLICATE_TERMINAL_RECEIPT must not false-flag on an unrelated
    attempt_id sharing the presented list (P1-22 fix; positive proof)."""
    print("TEST 17: duplicate-detection ignores unrelated attempt_id...")
    validator = WorkReceiptValidator()

    receipt = load_fixture("receipt_1_valid.json")
    unrelated = json.loads(json.dumps(receipt))
    unrelated["attempt_id"] = "attempt_unrelated_999"

    result = validator.validate_receipt(receipt, all_receipts_for_attempt=[receipt, unrelated])

    assert result.valid, \
        f"An unrelated attempt_id's terminal receipt must not false-flag this one: {result.reason}"
    print(f"  [OK] PASS: unrelated-attempt terminal receipt correctly ignored\n")
    return 1


def test_rejection_predecessor_self_cycle():
    """Test 18: UNVERIFIED_PREDECESSOR - self-cycle within the presented set (P1-21)."""
    print("TEST 18: UNVERIFIED_PREDECESSOR (self-cycle) rejection...")
    validator = WorkReceiptValidator()

    self_hash = "4" * 64
    node = json.loads(json.dumps(load_fixture("receipt_1_valid.json")))
    node["predecessor_receipts"] = [self_hash]

    receipt = json.loads(json.dumps(load_fixture("receipt_2_valid.json")))
    receipt["predecessor_receipts"] = [self_hash]

    result = validator.validate_receipt(receipt, known_receipts={self_hash: node})

    assert not result.valid, "A node listing itself as its own predecessor is a cycle"
    assert result.rejection_class == "UNVERIFIED_PREDECESSOR", \
        f"Expected UNVERIFIED_PREDECESSOR, got {result.rejection_class}"
    print(f"  [OK] PASS: {result.rejection_class} ({result.reason})\n")
    return 1


def test_rejection_predecessor_two_node_cycle():
    """Test 19: UNVERIFIED_PREDECESSOR - two-node cycle within the presented set (P1-21)."""
    print("TEST 19: UNVERIFIED_PREDECESSOR (two-node cycle) rejection...")
    validator = WorkReceiptValidator()

    hash_a = "5" * 64
    hash_b = "6" * 64
    node_a = json.loads(json.dumps(load_fixture("receipt_1_valid.json")))
    node_a["predecessor_receipts"] = [hash_b]
    node_b = json.loads(json.dumps(load_fixture("receipt_1_valid.json")))
    node_b["predecessor_receipts"] = [hash_a]

    receipt = json.loads(json.dumps(load_fixture("receipt_2_valid.json")))
    receipt["predecessor_receipts"] = [hash_a]

    result = validator.validate_receipt(receipt, known_receipts={hash_a: node_a, hash_b: node_b})

    assert not result.valid, "A -> B -> A is a cycle even though every hash is 'known'"
    assert result.rejection_class == "UNVERIFIED_PREDECESSOR", \
        f"Expected UNVERIFIED_PREDECESSOR, got {result.rejection_class}"
    print(f"  [OK] PASS: {result.rejection_class} ({result.reason})\n")
    return 1


def main():
    """Run all tests."""
    print("=" * 70)
    print("RECEIPT-CONTRACT VALIDATOR TEST SUITE")
    print("=" * 70)
    print()

    fixture_count = 0

    try:
        fixture_count += test_valid_chain()
        fixture_count += test_rejection_orphaned_decision()
        fixture_count += test_rejection_missing_content_binding()
        fixture_count += test_rejection_contradictory_terminal_states()
        fixture_count += test_rejection_duplicate_terminal_receipt()
        fixture_count += test_rejection_unverified_predecessor()
        fixture_count += test_rejection_malformed_scheduler_effects()
        fixture_count += test_rejection_external_override_verdict()
        fixture_count += test_rejection_schema_missing_required_field()
        fixture_count += test_rejection_schema_unknown_property()
        fixture_count += test_rejection_schema_runtime_evidence_incomplete()
        fixture_count += test_rejection_scope_unbound_path_traversal()
        fixture_count += test_rejection_external_override_verdict_string_encoded()
        fixture_count += test_rejection_scheduler_effect_self_reference()
        fixture_count += test_rejection_scheduler_effect_rejected_unlock()
        fixture_count += test_rejection_contradictory_error_with_pass()
        fixture_count += test_duplicate_terminal_receipt_ignores_unrelated_attempt()
        fixture_count += test_rejection_predecessor_self_cycle()
        fixture_count += test_rejection_predecessor_two_node_cycle()

        print("=" * 70)
        print(f"RECEIPT-CONTRACT-TESTS OK ({fixture_count} fixtures tested)")
        print("=" * 70)
        sys.exit(0)

    except AssertionError as e:
        print(f"\nFAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
