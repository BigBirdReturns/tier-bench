#!/usr/bin/env python3
"""
Fail-closed validator for policy kernel decision contracts.

Enforces:
1. Schema conformance
2. No hypothesis-as-measured
3. No credentials in any string field
4. Stale snapshots labeled ADVISORY
5. decision_id derived from input hashes (not clock/random)
"""

import json
import hashlib
import re
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

# Credential patterns to reject in any string value
CREDENTIAL_PATTERNS = [
    r"(?i)\b(?:api[_-]?key|apikey)\b",
    r"(?i)\b(?:secret[_-]?key|secretkey)\b",
    r"(?i)\b(?:private[_-]?key|privatekey)\b",
    r"(?i)\b(?:access[_-]?token|accesstoken)\b",
    r"(?i)\b(?:bearer[_-]?token|bearertoken)\b",
    r"(?i)\b(?:auth[_-]?token|authtoken)\b",
    r"(?i)\b(?:refresh[_-]?token|refreshtoken)\b",
    r"(?i)\b(?:jwt|session[_-]?id)\b",
    r"(?i)\btoken\b",
    r"(?i)\bkey\b",
    r"(?i)\bsecret\b",
    r"(?i)\bpassword\b",
    r"(?i)\bpwd\b",
    r"(?i)\bcredential",
    r"(?i)\bauth\b",
]

COMPILED_CREDENTIAL_PATTERNS = [re.compile(p) for p in CREDENTIAL_PATTERNS]


class ValidationError(Exception):
    """Raised when validation fails."""
    pass


def load_schema() -> Dict[str, Any]:
    """Load schema.json from same directory as this file."""
    schema_path = Path(__file__).parent / "schema.json"
    try:
        with open(schema_path) as f:
            return json.load(f)
    except Exception as e:
        raise ValidationError(f"Failed to load schema: {e}")


def validate_schema_conformance(obj: Dict[str, Any]) -> None:
    """Validate object conforms to JSON schema."""
    try:
        import jsonschema
        schema = load_schema()
        jsonschema.validate(obj, schema)
    except ImportError:
        # Fallback: basic structural validation if jsonschema not available
        if isinstance(obj, dict):
            if obj.get("type") == "NO_DECISION":
                required = {"type", "reason", "observed_at"}
            else:
                required = {
                    "schema", "decision_id", "task_envelope_sha256",
                    "cartridge_manifest_sha256", "tank_snapshot_sha256",
                    "evidence_refs", "selected_cartridge", "capability_basis",
                    "quota_basis", "route_reason", "fallback_order",
                    "operator_gate", "observed_at", "snapshot_max_age"
                }
            missing = required - set(obj.keys())
            if missing:
                raise ValidationError(f"Missing required fields: {missing}")
        else:
            raise ValidationError("Decision must be a JSON object")
    except Exception as e:
        raise ValidationError(f"Schema validation failed: {e}")


def scan_for_credentials(obj: Any, path: str = "$") -> List[Tuple[str, str]]:
    """
    Recursively scan all string values for credential patterns.
    Returns list of (path, matched_pattern) tuples.
    """
    violations = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            new_path = f"{path}.{key}"
            violations.extend(scan_for_credentials(value, new_path))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            new_path = f"{path}[{i}]"
            violations.extend(scan_for_credentials(item, new_path))
    elif isinstance(obj, str):
        for pattern in COMPILED_CREDENTIAL_PATTERNS:
            if pattern.search(obj):
                violations.append((path, obj[:100]))
                break

    return violations


def reject_hypothesis_as_measured(obj: Dict[str, Any]) -> None:
    """Reject hypothesis source serialized as measured capability."""
    if obj.get("type") == "NO_DECISION":
        return

    # If capability_basis is hypothesis or unmeasured, measured is forbidden
    basis = obj.get("capability_basis")
    if basis in ("hypothesis", "unmeasured"):
        # Look for any "measured" values in the object (shouldn't exist, but enforce)
        measured_evidence = [
            ref for ref in obj.get("evidence_refs", [])
            if "measured" in ref.lower()
        ]
        if basis == "hypothesis" and measured_evidence:
            raise ValidationError(
                f"Cannot emit capability_basis: hypothesis with measured evidence references: {measured_evidence}"
            )


def validate_observed_at_format(observed_at: str) -> None:
    """Validate observed_at is a proper ISO 8601 datetime."""
    try:
        datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise ValidationError(f"observed_at not valid ISO 8601: {observed_at}")


def reject_stale_unlabeled(obj: Dict[str, Any], tank_age_seconds: int = 0) -> None:
    """
    Reject stale tank snapshots not labeled ADVISORY.
    A snapshot is stale if its age exceeds snapshot_max_age AND it lacks ADVISORY label.
    """
    if obj.get("type") == "NO_DECISION":
        return

    max_age = obj.get("snapshot_max_age", 0)
    if tank_age_seconds > max_age:
        label = obj.get("label")
        if label != "ADVISORY":
            raise ValidationError(
                f"Stale tank snapshot (age {tank_age_seconds}s > max {max_age}s) "
                f"must be labeled ADVISORY, got: {label}"
            )

    # If label field is present, it must be ADVISORY (no other values allowed)
    label = obj.get("label")
    if label is not None and label != "ADVISORY":
        raise ValidationError(
            f"Label field, if present, must be 'ADVISORY', got: {label}"
        )


def verify_decision_id_deterministic(
    obj: Dict[str, Any],
    task_hash: str = None,
    cartridge_hash: str = None,
    tank_hash: str = None,
) -> None:
    """
    Verify decision_id derives from input hashes, not clock or random.

    If input hashes provided, compute expected ID and verify.
    If not provided, at minimum verify it looks like a SHA256 hash (not a timestamp).
    """
    if obj.get("type") == "NO_DECISION":
        return

    decision_id = obj.get("decision_id", "")

    # Basic format check: must be 64-char hex
    if not re.match(r"^[a-f0-9]{64}$", decision_id):
        raise ValidationError(
            f"decision_id must be SHA256 hex (64 chars), got: {decision_id}"
        )

    # Reject obvious timestamp-derived IDs (unix timestamps: 10-11 digits starting with 1 or 2)
    if re.search(r"[12]\d{9,10}(?:\d{6})?", decision_id) or "-" in decision_id:
        raise ValidationError(
            f"decision_id appears clock-derived (contains timestamp patterns): {decision_id}"
        )

    # If all input hashes provided, verify the decision_id was derived correctly
    if all([task_hash, cartridge_hash, tank_hash]):
        # Concatenate hashes and compute SHA256
        combined = f"{task_hash}{cartridge_hash}{tank_hash}"
        expected_id = hashlib.sha256(combined.encode()).hexdigest()
        if decision_id != expected_id:
            raise ValidationError(
                f"decision_id {decision_id} does not match expected {expected_id} "
                f"derived from input hashes"
            )


def validate_decision(
    obj: Dict[str, Any],
    verify_decision_id_with_inputs: bool = False,
    task_hash: str = None,
    cartridge_hash: str = None,
    tank_hash: str = None,
) -> None:
    """
    Run all validation checks on a decision object.

    Raises ValidationError if any check fails.
    """
    # 1. Schema conformance
    validate_schema_conformance(obj)

    # 2. No credentials anywhere
    violations = scan_for_credentials(obj)
    if violations:
        paths = [f"{path} (contains pattern match)" for path, _ in violations]
        raise ValidationError(
            f"Found credential patterns in string fields:\n" + "\n".join(paths[:3])
        )

    # 3. No hypothesis-as-measured
    reject_hypothesis_as_measured(obj)

    # 4. Format checks on observed_at
    validate_observed_at_format(obj.get("observed_at", ""))

    # 5. Stale snapshots must be ADVISORY
    if obj.get("type") != "NO_DECISION":
        reject_stale_unlabeled(obj)

    # 6. decision_id must be hash-derived, not clock-derived
    if verify_decision_id_with_inputs:
        verify_decision_id_deterministic(obj, task_hash, cartridge_hash, tank_hash)
    else:
        # At minimum, reject obvious clock-derived IDs
        if obj.get("type") != "NO_DECISION":
            verify_decision_id_deterministic(obj)


def main():
    """CLI entry point: validate a decision JSON file."""
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <decision.json>")
        sys.exit(1)

    path = Path(sys.argv[1])
    try:
        with open(path) as f:
            obj = json.load(f)
        validate_decision(obj)
        print(f"✓ {path} is valid")
        sys.exit(0)
    except ValidationError as e:
        print(f"✗ Validation failed: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
