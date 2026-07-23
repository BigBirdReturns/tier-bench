#!/usr/bin/env python3
"""Work receipt contract validator (fail-closed).

Implements the 7 card-frozen rejection classes for work_receipt_contract_v1,
plus two cross-cutting additions from KERNEL-REFUTATION-DISPOSITION-1 batch 1
(SCHEMA_VIOLATION: wire schema.json into the validator; SCOPE_UNBOUND: reject
malformed repository-relative path scoping when scope.allowed_paths is
presented).
"""

import json
import re
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass

SCHEMA_PATH = Path(__file__).parent / "schema.json"


def _load_schema() -> Dict[str, Any]:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _schema_violation(instance: Any, schema: Dict[str, Any], path: str = "$") -> Optional[str]:
    """Dependency-free draft-2020-12-subset schema check, covering exactly the
    constructs schema.json actually uses (type/required/properties/
    additionalProperties/pattern/enum/const/minLength/minItems/items/minimum/
    format). Used as the fail-closed fallback when the `jsonschema` package is
    unavailable, so schema enforcement is never silently skipped either way.
    Returns the first violation message, or None if the instance conforms.
    """
    if "const" in schema:
        if instance != schema["const"]:
            return f"{path}: expected const {schema['const']!r}, got {instance!r}"
        return None

    schema_type = schema.get("type")

    if schema_type == "object":
        if not isinstance(instance, dict):
            return f"{path}: expected object, got {type(instance).__name__}"
        for required_key in schema.get("required", []):
            if required_key not in instance:
                return f"{path}: missing required property {required_key!r}"
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in properties:
                    return f"{path}: additional property {key!r} not allowed"
        for key, subschema in properties.items():
            if key in instance:
                violation = _schema_violation(instance[key], subschema, f"{path}.{key}")
                if violation:
                    return violation
        return None

    if schema_type == "array":
        if not isinstance(instance, list):
            return f"{path}: expected array, got {type(instance).__name__}"
        if "minItems" in schema and len(instance) < schema["minItems"]:
            return f"{path}: expected at least {schema['minItems']} items"
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(instance):
                violation = _schema_violation(item, item_schema, f"{path}[{i}]")
                if violation:
                    return violation
        return None

    if schema_type == "string":
        if not isinstance(instance, str):
            return f"{path}: expected string, got {type(instance).__name__}"
        if "minLength" in schema and len(instance) < schema["minLength"]:
            return f"{path}: shorter than minLength {schema['minLength']}"
        if "enum" in schema and instance not in schema["enum"]:
            return f"{path}: {instance!r} not in enum {schema['enum']}"
        if "pattern" in schema and not re.match(schema["pattern"], instance):
            return f"{path}: {instance!r} does not match pattern {schema['pattern']}"
        if schema.get("format") == "date-time" and not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", instance):
            return f"{path}: {instance!r} is not a date-time"
        return None

    if schema_type == "integer":
        if not isinstance(instance, int) or isinstance(instance, bool):
            return f"{path}: expected integer, got {type(instance).__name__}"
        if "minimum" in schema and instance < schema["minimum"]:
            return f"{path}: below minimum {schema['minimum']}"
        return None

    return None


@dataclass
class ValidationResult:
    """Result of a validation check."""
    valid: bool
    reason: Optional[str] = None
    rejection_class: Optional[str] = None


class WorkReceiptValidator:
    """Fail-closed validator for work receipt contracts."""

    # SHA256 pattern (64 hex chars)
    SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
    # Git commit pattern (40 hex chars)
    GIT_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")

    _schema_cache: Optional[Dict[str, Any]] = None

    def __init__(self, all_task_ids: Optional[List[str]] = None):
        """Initialize validator.

        Args:
            all_task_ids: List of valid task_ids for scheduler effect resolution.
                         If None, scheduler effects are not validated for resolution.
        """
        self.all_task_ids = set(all_task_ids) if all_task_ids else set()

    def validate_receipt(self, receipt: Dict[str, Any],
                        known_receipts: Optional[Dict[str, Dict]] = None,
                        all_receipts_for_attempt: Optional[List[Dict]] = None) -> ValidationResult:
        """Validate a single receipt against all rejection classes.

        Args:
            receipt: The receipt to validate.
            known_receipts: Dict mapping receipt SHA256 -> receipt content for predecessor verification.
            all_receipts_for_attempt: All receipts with the same attempt_id (for duplicate detection).

        Returns:
            ValidationResult with valid=True if all checks pass, False otherwise.
        """
        known_receipts = known_receipts or {}
        all_receipts_for_attempt = all_receipts_for_attempt or []

        # 1. Check for orphaned decision
        result = self._check_orphaned_decision(receipt)
        if not result.valid:
            return result

        # 2. Check missing content binding
        result = self._check_missing_content_binding(receipt)
        if not result.valid:
            return result

        # 3. Check contradictory terminal states
        result = self._check_contradictory_terminal_states(receipt)
        if not result.valid:
            return result

        # 4. Check duplicate terminal receipts
        result = self._check_duplicate_terminal_receipt(receipt, all_receipts_for_attempt)
        if not result.valid:
            return result

        # 5. Check unverified predecessors
        result = self._check_unverified_predecessor(receipt, known_receipts)
        if not result.valid:
            return result

        # 6. Check malformed scheduler effects
        result = self._check_malformed_scheduler_effects(receipt)
        if not result.valid:
            return result

        # 7. Check external override verdict
        result = self._check_external_override_verdict(receipt)
        if not result.valid:
            return result

        # 8. Check scope binding (allowed_paths well-formedness, when presented)
        result = self._check_scope_binding(receipt)
        if not result.valid:
            return result

        # 9. Full schema conformance (run last so the 7 card-frozen classes above
        #    keep reporting their own specific reason; schema closes everything
        #    those checks don't already read: task_id/attempt_id/scope/
        #    runtime_evidence/created_at presence, additionalProperties, nested
        #    required fields). Fails closed if jsonschema is unavailable.
        result = self._check_schema_conformance(receipt)
        if not result.valid:
            return result

        return ValidationResult(valid=True)

    def _check_orphaned_decision(self, receipt: Dict) -> ValidationResult:
        """Rejection class 1: Orphaned decision (receipt citing no known decision hash)."""
        if "decision_receipt_sha256" not in receipt:
            return ValidationResult(
                valid=False,
                reason="Missing decision_receipt_sha256",
                rejection_class="ORPHANED_DECISION"
            )

        decision_hash = receipt.get("decision_receipt_sha256")
        if not isinstance(decision_hash, str) or not self.SHA256_PATTERN.match(decision_hash):
            return ValidationResult(
                valid=False,
                reason=f"Invalid decision_receipt_sha256 format: {decision_hash}",
                rejection_class="ORPHANED_DECISION"
            )

        return ValidationResult(valid=True)

    def _check_missing_content_binding(self, receipt: Dict) -> ValidationResult:
        """Rejection class 2: Missing content binding (any *_sha256 absent or unverifiable)."""
        sha256_fields = [
            "decision_receipt_sha256",
            "task_envelope_sha256",
            "cartridge_manifest_sha256",
            "patch_sha256",
            "referee_spec_sha256"
        ]

        for field in sha256_fields:
            if field not in receipt:
                return ValidationResult(
                    valid=False,
                    reason=f"Missing {field}",
                    rejection_class="MISSING_CONTENT_BINDING"
                )

            value = receipt.get(field)
            if not isinstance(value, str) or not self.SHA256_PATTERN.match(value):
                return ValidationResult(
                    valid=False,
                    reason=f"Invalid {field} format: {value}",
                    rejection_class="MISSING_CONTENT_BINDING"
                )

        # Check base_commit format (40 hex chars)
        if "base_commit" not in receipt:
            return ValidationResult(
                valid=False,
                reason="Missing base_commit",
                rejection_class="MISSING_CONTENT_BINDING"
            )

        base_commit = receipt.get("base_commit")
        if not isinstance(base_commit, str) or not self.GIT_COMMIT_PATTERN.match(base_commit):
            return ValidationResult(
                valid=False,
                reason=f"Invalid base_commit format: {base_commit}",
                rejection_class="MISSING_CONTENT_BINDING"
            )

        return ValidationResult(valid=True)

    def _check_contradictory_terminal_states(self, receipt: Dict) -> ValidationResult:
        """Rejection class 3: Contradictory terminal states in one receipt.

        Closed truth table (P2-4): ACCEPTED<->PASS, REJECTED<->FAIL, and ERROR
        may never pair with PASS (an errored attempt cannot have been passed).
        """
        terminal_state = receipt.get("terminal_state")
        referee_result = receipt.get("referee_result")

        if terminal_state not in ["ACCEPTED", "REJECTED", "ERROR"]:
            return ValidationResult(
                valid=False,
                reason=f"Invalid terminal_state: {terminal_state}",
                rejection_class="CONTRADICTORY_TERMINAL_STATES"
            )

        if referee_result not in ["PASS", "FAIL"]:
            return ValidationResult(
                valid=False,
                reason=f"Invalid referee_result: {referee_result}",
                rejection_class="CONTRADICTORY_TERMINAL_STATES"
            )

        # Check logical consistency between terminal_state and referee_result
        if terminal_state == "ACCEPTED" and referee_result != "PASS":
            return ValidationResult(
                valid=False,
                reason=f"Contradiction: terminal_state={terminal_state} but referee_result={referee_result}",
                rejection_class="CONTRADICTORY_TERMINAL_STATES"
            )

        if terminal_state == "REJECTED" and referee_result != "FAIL":
            return ValidationResult(
                valid=False,
                reason=f"Contradiction: terminal_state={terminal_state} but referee_result={referee_result}",
                rejection_class="CONTRADICTORY_TERMINAL_STATES"
            )

        if terminal_state == "ERROR" and referee_result == "PASS":
            return ValidationResult(
                valid=False,
                reason="Contradiction: terminal_state=ERROR cannot carry referee_result=PASS",
                rejection_class="CONTRADICTORY_TERMINAL_STATES"
            )

        return ValidationResult(valid=True)

    def _check_duplicate_terminal_receipt(self, receipt: Dict,
                                         all_receipts_for_attempt: List[Dict]) -> ValidationResult:
        """Rejection class 4: Duplicate terminal receipts for one attempt_id.

        P1-22: count only receipts sharing THIS receipt's exact attempt_id —
        an unrelated-attempt terminal receipt in the presented list must never
        false-flag this one.
        """
        terminal_state = receipt.get("terminal_state")
        attempt_id = receipt.get("attempt_id")

        # Count terminal receipts in the provided list that share this attempt_id
        terminal_count = sum(
            1 for r in all_receipts_for_attempt
            if r.get("attempt_id") == attempt_id
            and r.get("terminal_state") in ["ACCEPTED", "REJECTED", "ERROR"]
        )

        # If this is a terminal receipt and there's already one (or more) in the list, it's a duplicate
        if terminal_state in ["ACCEPTED", "REJECTED", "ERROR"] and terminal_count > 1:
            return ValidationResult(
                valid=False,
                reason=f"Duplicate terminal receipt for attempt_id {attempt_id} (found {terminal_count} terminal receipts)",
                rejection_class="DUPLICATE_TERMINAL_RECEIPT"
            )

        return ValidationResult(valid=True)

    def _detect_predecessor_cycle(self, start_hashes: List[str],
                                 known_receipts: Dict[str, Dict]) -> Optional[str]:
        """Walk predecessor_receipts links within the PRESENTED known_receipts
        graph only (never a global store, per the card's frozen scoping) and
        return the first hash revisited, or None if acyclic."""
        visited: set = set()
        stack = list(start_hashes)
        while stack:
            h = stack.pop()
            if h in visited:
                return h
            visited.add(h)
            node = known_receipts.get(h)
            if not isinstance(node, dict):
                continue
            preds = node.get("predecessor_receipts", [])
            if isinstance(preds, list):
                for p in preds:
                    if isinstance(p, str):
                        stack.append(p)
        return None

    def _check_unverified_predecessor(self, receipt: Dict,
                                     known_receipts: Dict[str, Dict]) -> ValidationResult:
        """Rejection class 5: Nonexistent predecessor references (UNVERIFIED_PREDECESSOR).

        The validator checks hash-linkage against ONLY the receipts presented to it.
        Unpresented predecessors degrade to labeled UNVERIFIED_PREDECESSOR, never
        silent pass. P1-21: also reject cycles (self-cycle or multi-node) formed
        entirely within the presented set.
        """
        predecessor_receipts = receipt.get("predecessor_receipts", [])

        if not isinstance(predecessor_receipts, list):
            return ValidationResult(
                valid=False,
                reason="predecessor_receipts must be an array",
                rejection_class="UNVERIFIED_PREDECESSOR"
            )

        for pred_hash in predecessor_receipts:
            if not isinstance(pred_hash, str) or not self.SHA256_PATTERN.match(pred_hash):
                return ValidationResult(
                    valid=False,
                    reason=f"Invalid predecessor hash format: {pred_hash}",
                    rejection_class="UNVERIFIED_PREDECESSOR"
                )

            # Check if predecessor is in known_receipts
            if pred_hash not in known_receipts:
                return ValidationResult(
                    valid=False,
                    reason=f"Unpresented predecessor: {pred_hash}",
                    rejection_class="UNVERIFIED_PREDECESSOR"
                )

        cycle_hash = self._detect_predecessor_cycle(predecessor_receipts, known_receipts)
        if cycle_hash is not None:
            return ValidationResult(
                valid=False,
                reason=f"Predecessor cycle detected (revisits {cycle_hash})",
                rejection_class="UNVERIFIED_PREDECESSOR"
            )

        return ValidationResult(valid=True)

    def _check_malformed_scheduler_effects(self, receipt: Dict) -> ValidationResult:
        """Rejection class 6: Malformed scheduler effects (unlocks/blocks not resolvable to task_ids).

        P1-24 (partial, batch-1 subset): reject a receipt that lists its own
        task_id as one of its own effects, and reject any unlocks on a
        non-ACCEPTED terminal receipt (a REJECTED/ERROR attempt authorizes no
        downstream work). Overlap/duplicate-within-list checks and a mandatory
        authoritative task-envelope set remain out of scope for this batch —
        see the repair report.
        """
        task_id = receipt.get("task_id")
        unlocks = receipt.get("unlocks", [])
        blocks = receipt.get("blocks", [])

        if not isinstance(unlocks, list):
            return ValidationResult(
                valid=False,
                reason="unlocks must be an array",
                rejection_class="MALFORMED_SCHEDULER_EFFECTS"
            )

        if not isinstance(blocks, list):
            return ValidationResult(
                valid=False,
                reason="blocks must be an array",
                rejection_class="MALFORMED_SCHEDULER_EFFECTS"
            )

        if isinstance(task_id, str) and (task_id in unlocks or task_id in blocks):
            return ValidationResult(
                valid=False,
                reason=f"Receipt for task_id {task_id} names itself in its own unlocks/blocks",
                rejection_class="MALFORMED_SCHEDULER_EFFECTS"
            )

        if receipt.get("terminal_state") != "ACCEPTED" and len(unlocks) > 0:
            return ValidationResult(
                valid=False,
                reason=f"terminal_state={receipt.get('terminal_state')} receipt may not unlock downstream work",
                rejection_class="MALFORMED_SCHEDULER_EFFECTS"
            )

        # If all_task_ids is provided, validate that unlocks/blocks reference valid task_ids
        if self.all_task_ids:
            for task_id in unlocks:
                if not isinstance(task_id, str) or len(task_id) == 0:
                    return ValidationResult(
                        valid=False,
                        reason=f"Invalid task_id in unlocks: {task_id}",
                        rejection_class="MALFORMED_SCHEDULER_EFFECTS"
                    )
                if task_id not in self.all_task_ids:
                    return ValidationResult(
                        valid=False,
                        reason=f"Unresolvable task_id in unlocks: {task_id}",
                        rejection_class="MALFORMED_SCHEDULER_EFFECTS"
                    )

            for task_id in blocks:
                if not isinstance(task_id, str) or len(task_id) == 0:
                    return ValidationResult(
                        valid=False,
                        reason=f"Invalid task_id in blocks: {task_id}",
                        rejection_class="MALFORMED_SCHEDULER_EFFECTS"
                    )
                if task_id not in self.all_task_ids:
                    return ValidationResult(
                        valid=False,
                        reason=f"Unresolvable task_id in blocks: {task_id}",
                        rejection_class="MALFORMED_SCHEDULER_EFFECTS"
                    )

        return ValidationResult(valid=True)

    def _check_external_override_verdict(self, receipt: Dict) -> ValidationResult:
        """Rejection class 7: External system claiming to override referee verdict.

        An external_ref carrying a verdict field = rejection. external_refs are
        DESCRIPTIVE and never authoritative. P1-23: also reject a string-encoded
        override smuggled as plain text (e.g. "verdict:ACCEPTED") in any of the
        four external_refs fields, closing the alternate-key/string-encoded
        variant the nested-dict-only check missed.
        """
        external_refs = receipt.get("external_refs", {})

        if not isinstance(external_refs, dict):
            return ValidationResult(
                valid=False,
                reason="external_refs must be an object",
                rejection_class="EXTERNAL_OVERRIDE_VERDICT"
            )

        # Check if any external_ref has a 'verdict' field (which would be an override)
        for key, value in external_refs.items():
            if isinstance(value, dict) and "verdict" in value:
                return ValidationResult(
                    valid=False,
                    reason=f"External ref {key} attempting to override verdict",
                    rejection_class="EXTERNAL_OVERRIDE_VERDICT"
                )
            if isinstance(value, str) and re.search(r"verdict", value, re.IGNORECASE):
                return ValidationResult(
                    valid=False,
                    reason=f"External ref {key} carries a string-encoded verdict override: {value}",
                    rejection_class="EXTERNAL_OVERRIDE_VERDICT"
                )

        return ValidationResult(valid=True)

    def _check_scope_binding(self, receipt: Dict) -> ValidationResult:
        """P1-20 (batch-1 subset): when scope.allowed_paths is presented, it
        must be a non-empty array of unique, repository-relative paths with no
        absolute roots and no '..' escape. This does not yet verify the patch
        actually stays within allowed_paths (requires patch bytes, out of this
        validator's current input surface) — see the repair report.
        """
        scope = receipt.get("scope")
        if not isinstance(scope, dict):
            return ValidationResult(valid=True)

        allowed_paths = scope.get("allowed_paths")
        if allowed_paths is None:
            return ValidationResult(valid=True)

        if not isinstance(allowed_paths, list) or len(allowed_paths) == 0:
            return ValidationResult(
                valid=False,
                reason="scope.allowed_paths must be a non-empty array when present",
                rejection_class="SCOPE_UNBOUND"
            )

        seen = set()
        for path in allowed_paths:
            if not isinstance(path, str) or not path:
                return ValidationResult(
                    valid=False,
                    reason=f"Invalid scope.allowed_paths entry: {path!r}",
                    rejection_class="SCOPE_UNBOUND"
                )
            normalized = path.replace("\\", "/")
            if normalized in seen:
                return ValidationResult(
                    valid=False,
                    reason=f"Duplicate scope.allowed_paths entry: {path}",
                    rejection_class="SCOPE_UNBOUND"
                )
            seen.add(normalized)
            if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
                return ValidationResult(
                    valid=False,
                    reason=f"scope.allowed_paths entry is not repository-relative: {path}",
                    rejection_class="SCOPE_UNBOUND"
                )
            if any(segment == ".." for segment in normalized.split("/")):
                return ValidationResult(
                    valid=False,
                    reason=f"scope.allowed_paths entry escapes the repository via '..': {path}",
                    rejection_class="SCOPE_UNBOUND"
                )

        return ValidationResult(valid=True)

    def _check_schema_conformance(self, receipt: Dict) -> ValidationResult:
        """P1-16: wire schema.json into the validator. Run last so the 7
        card-frozen checks above keep reporting their own specific
        rejection_class for the violations they already cover; this closes
        everything they don't: task_id/attempt_id/scope/runtime_evidence/
        created_at presence and shape, nested required fields, and
        additionalProperties anywhere.

        Fail-closed on missing dependency means schema enforcement must never
        be silently skipped — not that every receipt must be rejected because
        a package happens to be absent. `jsonschema` is not a pinned
        dependency anywhere in this repo (no requirements/pyproject entry, no
        CI install step), so unconditionally requiring it would make this
        check's availability, and therefore every receipt's verdict, depend on
        host environment drift. Prefer the real draft-2020-12 validator when
        present; otherwise fall back to the dependency-free `_schema_violation`
        walker above, which enforces the same required/additionalProperties/
        pattern/enum constructs this schema.json actually uses. Either path
        enforces; neither path is a bypass.
        """
        if WorkReceiptValidator._schema_cache is None:
            WorkReceiptValidator._schema_cache = _load_schema()
        schema = WorkReceiptValidator._schema_cache

        try:
            import jsonschema
        except ImportError:
            violation = _schema_violation(receipt, schema)
            if violation:
                return ValidationResult(
                    valid=False,
                    reason=f"Schema violation (dependency-free check): {violation}",
                    rejection_class="SCHEMA_VIOLATION"
                )
            return ValidationResult(valid=True)

        try:
            jsonschema.validate(receipt, schema)
        except jsonschema.exceptions.ValidationError as e:
            return ValidationResult(
                valid=False,
                reason=f"Schema violation: {e.message}",
                rejection_class="SCHEMA_VIOLATION"
            )
        except jsonschema.exceptions.SchemaError as e:
            return ValidationResult(
                valid=False,
                reason=f"Invalid schema.json: {e.message}",
                rejection_class="SCHEMA_VIOLATION"
            )

        return ValidationResult(valid=True)
