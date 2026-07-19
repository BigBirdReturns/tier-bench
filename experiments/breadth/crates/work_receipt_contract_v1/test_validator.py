#!/usr/bin/env python3
"""Test suite for work_receipt_contract_v1 validator.

Validates:
- 1 valid two-receipt chain
- 7 rejection classes with named machine-readable reasons
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
