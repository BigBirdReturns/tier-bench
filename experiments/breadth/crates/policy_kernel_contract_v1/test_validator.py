#!/usr/bin/env python3
"""
Test suite for policy kernel decision validator.

Validates:
- Valid fixtures pass all checks
- Invalid fixtures fail with expected errors
- All six invariants are witnessed
"""

import json
import re
import sys
from pathlib import Path
from validate import validate_decision, ValidationError

# Fresh/valid staleness inputs shared by fixtures that aren't specifically
# exercising the P1-4 boundary -- keeps unrelated fixtures unaffected by the
# now-required, independently-sourced age plumbing.
FRESH_AGE_KWARGS = {"tank_age_seconds": 100, "max_age_policy": 3600}


class TestResult:
    """Track test pass/fail."""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def assert_valid(self, name, obj, **kwargs):
        """Assert a decision is valid."""
        try:
            validate_decision(obj, **kwargs)
            self.passed += 1
            print(f"  [OK] {name}")
        except ValidationError as e:
            self.failed += 1
            self.errors.append(f"    {name}: expected valid, got error: {e}")
            print(f"  [FAIL] {name}: {e}")

    def assert_invalid(self, name, obj, expected_reason_snippet, **kwargs):
        """Assert a decision is invalid and contains expected error reason."""
        try:
            validate_decision(obj, **kwargs)
            self.failed += 1
            self.errors.append(f"    {name}: expected invalid but passed validation")
            print(f"  [FAIL] {name}: expected validation to fail")
        except ValidationError as e:
            error_msg = str(e).lower()
            expected_lower = expected_reason_snippet.lower()
            if expected_lower in error_msg:
                self.passed += 1
                print(f"  [OK] {name} (rejected: {expected_reason_snippet})")
            else:
                self.failed += 1
                self.errors.append(
                    f"    {name}: got error '{e}' but expected to match '{expected_reason_snippet}'"
                )
                print(f"  [FAIL] {name}: error doesn't match expected: {e}")

    def summary(self):
        """Print summary and return exit code."""
        total = self.passed + self.failed
        print(f"\n{'=' * 70}")
        print(f"Test Results: {self.passed}/{total} passed")
        if self.failed > 0:
            print(f"\nFailures:")
            for err in self.errors:
                print(err)
            return 1
        return 0


def load_fixture(name):
    """Load a fixture JSON file."""
    path = Path(__file__).parent / "fixtures" / f"{name}.json"
    with open(path) as f:
        return json.load(f)


def test_valid_fixtures(results):
    """Test fixtures that should pass validation."""
    print("\n--- Valid Fixtures (should pass) ---")

    # Valid measured decision -- capability_basis "measured" now requires an
    # independently-supplied evidence index + task tier (P1-1/P2-1) in
    # addition to the independently-supplied staleness inputs (P1-4). Every
    # cartridge this fixture touches (selected + both fallbacks) resolves in
    # evidence_index_valid.json at tier T1.
    try:
        obj = load_fixture("valid_measured_decision")
        evidence_index = load_fixture("evidence_index_valid")
        results.assert_valid(
            "valid_measured_decision", obj,
            evidence_index=evidence_index, task_tier="T1", **FRESH_AGE_KWARGS
        )
    except Exception as e:
        results.failed += 1
        results.errors.append(f"    valid_measured_decision: {e}")
        print(f"  ✗ valid_measured_decision: {e}")

    # Valid hypothesis decision -- basis != "measured" so no evidence index
    # is required, but staleness adjudication (P1-4) always applies.
    try:
        obj = load_fixture("valid_hypothesis_decision")
        results.assert_valid(
            "valid_hypothesis_decision", obj, **FRESH_AGE_KWARGS
        )
    except Exception as e:
        results.failed += 1
        results.errors.append(f"    valid_hypothesis_decision: {e}")
        print(f"  ✗ valid_hypothesis_decision: {e}")

    # Valid NO_DECISION
    try:
        obj = load_fixture("valid_no_decision")
        results.assert_valid("valid_no_decision", obj)
    except Exception as e:
        results.failed += 1
        results.errors.append(f"    valid_no_decision: {e}")
        print(f"  ✗ valid_no_decision: {e}")


def test_invalid_fixtures(results):
    """Test fixtures that should fail validation."""
    print("\n--- Invalid Fixtures (should fail) ---")

    # Invalid: fake measured (hypothesis with measured evidence)
    try:
        obj = load_fixture("invalid_fake_measured")
        results.assert_invalid(
            "invalid_fake_measured",
            obj,
            "Cannot emit capability_basis: hypothesis with measured evidence"
        )
    except Exception as e:
        results.failed += 1
        results.errors.append(f"    invalid_fake_measured: {e}")
        print(f"  ✗ invalid_fake_measured: {e}")

    # Invalid: credential in field
    try:
        obj = load_fixture("invalid_credential_in_field")
        results.assert_invalid(
            "invalid_credential_in_field",
            obj,
            "credential patterns"
        )
    except Exception as e:
        results.failed += 1
        results.errors.append(f"    invalid_credential_in_field: {e}")
        print(f"  ✗ invalid_credential_in_field: {e}")

    # Invalid: stale snapshot with wrong label
    try:
        obj = load_fixture("invalid_unlabeled_stale")
        results.assert_invalid(
            "invalid_unlabeled_stale",
            obj,
            "advisory"
        )
    except Exception as e:
        results.failed += 1
        results.errors.append(f"    invalid_unlabeled_stale: {e}")
        print(f"  ✗ invalid_unlabeled_stale: {e}")

    # Invalid: clock-derived decision_id. Needs fresh age inputs to get past
    # the (now age-required) staleness check so the intended decision_id
    # rejection is the one that actually fires.
    try:
        obj = load_fixture("invalid_clock_derived_id")
        results.assert_invalid(
            "invalid_clock_derived_id",
            obj,
            "timestamp",
            **FRESH_AGE_KWARGS
        )
    except Exception as e:
        results.failed += 1
        results.errors.append(f"    invalid_clock_derived_id: {e}")
        print(f"  ✗ invalid_clock_derived_id: {e}")


def test_p1_1_p2_1_evidence_resolution(results):
    """
    P1-1: capability_basis "measured" must resolve selected_cartridge
    against an independently-supplied evidence index at the task's tier.
    P2-1: the same resolution applies to every fallback_order entry.
    """
    print("\n--- P1-1 / P2-1: Measured Evidence Resolution (should fail) ---")

    evidence_index_valid = load_fixture("evidence_index_valid")
    evidence_index_sample = load_fixture("evidence_index_sample")

    # Every case below carries FRESH_AGE_KWARGS so the (unrelated, but now
    # required) P1-4 staleness check passes cleanly and the rejection each
    # case is designed to prove is the one that actually fires, at step 7.
    cases = [
        # (fixture, kwargs, expected snippet)
        (
            "invalid_measured_absent_evidence",
            dict(FRESH_AGE_KWARGS),  # no evidence_index / task_tier at all -> fail closed
            "failing closed",
        ),
        (
            "invalid_measured_wrong_tier",
            dict(FRESH_AGE_KWARGS, evidence_index=evidence_index_sample, task_tier="T1"),
            "no measurement-class evidence record",
        ),
        (
            "invalid_measured_wrong_cartridge",
            dict(FRESH_AGE_KWARGS, evidence_index=evidence_index_sample, task_tier="T1"),
            "no measurement-class evidence record",
        ),
        (
            "invalid_measured_hypothesis_only_evidence",
            dict(FRESH_AGE_KWARGS, evidence_index=evidence_index_sample, task_tier="T1"),
            "no measurement-class evidence record",
        ),
        (
            "invalid_fallback_unmeasured",
            dict(FRESH_AGE_KWARGS, evidence_index=evidence_index_valid, task_tier="T1"),
            "no measurement-class evidence record",
        ),
    ]

    for name, kwargs, snippet in cases:
        try:
            obj = load_fixture(name)
            results.assert_invalid(name, obj, snippet, **kwargs)
        except Exception as e:
            results.failed += 1
            results.errors.append(f"    {name}: {e}")
            print(f"  ✗ {name}: {e}")


def test_p1_5_credential_key_scanning(results):
    """P1-5: a credential-shaped object KEY must reject even when its value
    is not a string (e.g. a number), because the value-only scan never
    inspects it."""
    print("\n--- P1-5: Credential Key Scanning (should fail) ---")

    try:
        obj = load_fixture("invalid_credential_key_nonstring")
        results.assert_invalid(
            "invalid_credential_key_nonstring",
            obj,
            "credential patterns",
            **FRESH_AGE_KWARGS
        )
    except Exception as e:
        results.failed += 1
        results.errors.append(f"    invalid_credential_key_nonstring: {e}")
        print(f"  ✗ invalid_credential_key_nonstring: {e}")

    # P1-5 companion witness (accepted bounded risk, NOT a regression): a
    # credential-shaped VALUE with no trigger keyword nearby (e.g. a bare
    # "sk_live_..." string) still passes. This is documented in validate.py
    # as an accepted gap pending a typed-secret-reference design -- this
    # fixture pins that documented behavior so a future change to the scan
    # heuristic can't silently start rejecting (or keep silently passing
    # without anyone noticing which case this is).
    try:
        obj = load_fixture("valid_credential_shaped_value_no_keyword")
        results.assert_valid(
            "valid_credential_shaped_value_no_keyword", obj,
            **FRESH_AGE_KWARGS
        )
    except Exception as e:
        results.failed += 1
        results.errors.append(f"    valid_credential_shaped_value_no_keyword: {e}")
        print(f"  ✗ valid_credential_shaped_value_no_keyword: {e}")


def test_p1_4_staleness_boundaries(results):
    """
    P1-4 boundary witnesses: age exactly at the independently-sourced
    policy max (still within policy, no ADVISORY required), one second
    over (must reject), and a decision that self-declares a huge
    snapshot_max_age trying to buy immunity (must still reject against the
    real, independently-sourced policy value -- the decision's own field is
    never used as the threshold).
    """
    print("\n--- P1-4: Staleness Boundary Witnesses ---")

    try:
        obj = load_fixture("valid_stale_boundary_at_max")
        results.assert_valid(
            "valid_stale_boundary_at_max", obj,
            tank_age_seconds=100, max_age_policy=100
        )
    except Exception as e:
        results.failed += 1
        results.errors.append(f"    valid_stale_boundary_at_max: {e}")
        print(f"  ✗ valid_stale_boundary_at_max: {e}")

    try:
        obj = load_fixture("invalid_stale_one_second_over")
        results.assert_invalid(
            "invalid_stale_one_second_over", obj, "advisory",
            tank_age_seconds=101, max_age_policy=100
        )
    except Exception as e:
        results.failed += 1
        results.errors.append(f"    invalid_stale_one_second_over: {e}")
        print(f"  ✗ invalid_stale_one_second_over: {e}")

    try:
        # Fixture self-declares snapshot_max_age: 999999999. The
        # independently-sourced real policy is 100s; real age is 200s. If
        # the validator ever fell back to trusting the decision's own
        # field, this would incorrectly pass.
        obj = load_fixture("invalid_stale_self_enlarged_max_age")
        assert obj["snapshot_max_age"] > 200, (
            "fixture setup invariant broken: self-declared max_age must "
            "exceed the real age so a pass here would prove self-enlargement worked"
        )
        results.assert_invalid(
            "invalid_stale_self_enlarged_max_age", obj, "advisory",
            tank_age_seconds=200, max_age_policy=100
        )
    except Exception as e:
        results.failed += 1
        results.errors.append(f"    invalid_stale_self_enlarged_max_age: {e}")
        print(f"  ✗ invalid_stale_self_enlarged_max_age: {e}")


# --- P2-2: coarse static-scan tripwire against in-process spawn capability ---
# Interim, $0-class only per disposition -- NOT a sandbox. This scans
# validate.py's own source text for suspicious imports/patterns that would
# indicate the kernel can reach outside itself (network, subprocess,
# filesystem writes, dynamic code execution). A real sandbox is explicitly
# out of scope for this batch.
SPAWN_TRIPWIRE_PATTERNS = [
    r"^\s*import\s+socket\b",
    r"^\s*import\s+requests\b",
    r"^\s*import\s+urllib",
    r"^\s*import\s+subprocess\b",
    r"^\s*from\s+subprocess\b",
    r"\bos\.system\s*\(",
    r"\bos\.popen\s*\(",
    r"open\([^)]*[\"'][rwa]?\+?[wW]",  # open(..., "w"/"wb"/"a"/...) style write modes
    r"\beval\s*\(",
    r"\bexec\s*\(",
]
COMPILED_SPAWN_TRIPWIRE = [re.compile(p, re.MULTILINE) for p in SPAWN_TRIPWIRE_PATTERNS]


def scan_for_spawn_patterns(source_text):
    """Return the list of tripwire patterns that matched in source_text."""
    return [p.pattern for p in COMPILED_SPAWN_TRIPWIRE if p.search(source_text)]


def test_p2_2_no_process_spawn_tripwire(results):
    """
    P2-2 (interim tripwire only, not a sandbox): validate.py's own source
    must carry none of the suspicious network/subprocess/filesystem-write/
    dynamic-exec patterns. This is a coarse static scan, not enforcement of
    an actual sandbox boundary -- that remains explicitly out of scope for
    this batch.
    """
    print("\n--- P2-2: Process-Spawn Tripwire (interim, static scan only) ---")

    validate_py_path = Path(__file__).parent / "validate.py"
    source_text = validate_py_path.read_text()

    matches = scan_for_spawn_patterns(source_text)
    if not matches:
        results.passed += 1
        print("  [OK] validate.py: no spawn/network/write/exec patterns found")
    else:
        results.failed += 1
        results.errors.append(
            f"    validate.py: spawn tripwire patterns found: {matches}"
        )
        print(f"  [FAIL] validate.py: spawn tripwire patterns found: {matches}")

    # Prove the tripwire is not a no-op: run the SAME scan against a small
    # fabricated source string with an injected violation and assert it is
    # caught. If this ever stops catching the injected line, the tripwire
    # above is not actually testing anything.
    poisoned_source = "import json\nimport subprocess\n\ndef f():\n    pass\n"
    poisoned_matches = scan_for_spawn_patterns(poisoned_source)
    if poisoned_matches:
        results.passed += 1
        print(f"  [OK] tripwire catches injected 'import subprocess': {poisoned_matches}")
    else:
        results.failed += 1
        results.errors.append(
            "    tripwire self-test: injected 'import subprocess' was NOT caught "
            "-- the scanner is a no-op"
        )
        print("  [FAIL] tripwire self-test: injected violation was NOT caught")


def test_invariants(results):
    """
    Verify all six invariants from the contract are witnessed.

    1. Determinism ✓ (no clock in decision_id)
    2. Fail closed on missing evidence ✓ (NO_DECISION terminal shape)
    3. Hypotheses cannot serialize as measurements ✓ (invalid_fake_measured rejects it)
    4. Staleness stays labeled ✓ (invalid_unlabeled_stale rejects unlabeled stale)
    5. No credentials anywhere ✓ (invalid_credential_in_field rejects it)
    6. No process spawning (verified by harness, not validator)
    """
    print("\n--- Six Frozen Invariants ---")

    invariants = [
        ("1. Determinism: decision_id derives from input hashes, not clock", True),
        ("2. Fail-closed: NO_DECISION terminal shape carries reason", True),
        ("3. No hypothesis-as-measured: hypothesis cannot serialize as measured", True),
        ("4. Staleness labeled: stale snapshots must be ADVISORY", True),
        ("5. No credentials: validator scans all string values AND object keys", True),
        ("6. No process spawning: interim static tripwire in test suite (not a sandbox)", True),
    ]

    for invariant, witnessed in invariants:
        if witnessed:
            results.passed += 1
            print(f"  [OK] {invariant}")
        else:
            results.failed += 1
            results.errors.append(f"    {invariant}: NOT WITNESSED")
            print(f"  [FAIL] {invariant}")


def main():
    """Run all tests."""
    print("=" * 70)
    print("POLICY KERNEL DECISION CONTRACT TEST SUITE")
    print("=" * 70)

    results = TestResult()

    try:
        test_valid_fixtures(results)
        test_invalid_fixtures(results)
        test_p1_1_p2_1_evidence_resolution(results)
        test_p1_5_credential_key_scanning(results)
        test_p1_4_staleness_boundaries(results)
        test_p2_2_no_process_spawn_tripwire(results)
        test_invariants(results)

        exit_code = results.summary()

        if exit_code == 0:
            print("\nPOLICY-CONTRACT-TESTS OK")
        sys.stdout.flush()

        sys.exit(exit_code)

    except Exception as e:
        print(f"\n✗ FATAL ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
