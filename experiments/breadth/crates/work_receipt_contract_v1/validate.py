#!/usr/bin/env python3
"""Work receipt contract validator (fail-closed).

Implements 7 rejection classes for the work_receipt_contract_v1.
"""

import json
import re
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass


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
        """Validate a single receipt against all 7 rejection classes.

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
        """Rejection class 3: Contradictory terminal states in one receipt."""
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

        return ValidationResult(valid=True)

    def _check_duplicate_terminal_receipt(self, receipt: Dict,
                                         all_receipts_for_attempt: List[Dict]) -> ValidationResult:
        """Rejection class 4: Duplicate terminal receipts for one attempt_id."""
        terminal_state = receipt.get("terminal_state")

        # Count terminal receipts in the provided list
        terminal_count = sum(
            1 for r in all_receipts_for_attempt
            if r.get("terminal_state") in ["ACCEPTED", "REJECTED", "ERROR"]
        )

        # If this is a terminal receipt and there's already one (or more) in the list, it's a duplicate
        if terminal_state in ["ACCEPTED", "REJECTED", "ERROR"] and terminal_count > 1:
            return ValidationResult(
                valid=False,
                reason=f"Duplicate terminal receipt for attempt_id (found {terminal_count} terminal receipts)",
                rejection_class="DUPLICATE_TERMINAL_RECEIPT"
            )

        return ValidationResult(valid=True)

    def _check_unverified_predecessor(self, receipt: Dict,
                                     known_receipts: Dict[str, Dict]) -> ValidationResult:
        """Rejection class 5: Nonexistent predecessor references (UNVERIFIED_PREDECESSOR).

        The validator checks hash-linkage against ONLY the receipts presented to it.
        Unpresented predecessors degrade to labeled UNVERIFIED_PREDECESSOR, never silent pass.
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

        return ValidationResult(valid=True)

    def _check_malformed_scheduler_effects(self, receipt: Dict) -> ValidationResult:
        """Rejection class 6: Malformed scheduler effects (unlocks/blocks not resolvable to task_ids)."""
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

        An external_ref carrying a verdict field = rejection.
        external_refs are DESCRIPTIVE and never authoritative.
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

        return ValidationResult(valid=True)
