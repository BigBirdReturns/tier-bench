"""Closed enum of machine-readable referee-kernel negative-witness reason codes.

Frozen against 010.100.TASK.md ("Frozen acceptance: negative witnesses") in
this crate. Each code binds to exactly one of the card's seven witnesses and
to the exact error text `tier_runner.core` already emits for that failure
class (verified against tier_runner/core.py, not guessed). "Specific
machine-readable reason" is only a guarantee if the vocabulary is closed:
do not add, rename, or repurpose a member without re-freezing the card.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable


class ReasonCode(Enum):
    ACCEPTANCE_COMMAND_MUTATED_POST_FREEZE = "acceptance_command_mutated_post_freeze"
    SCOPE_ESCAPE = "scope_escape"
    BASE_COMMIT_DRIFT = "base_commit_drift"
    EMPTY_PATCH_NOT_ACCEPTED = "empty_patch_not_accepted"
    ACCEPTANCE_FAILED_REJECTED = "acceptance_failed_rejected"
    VERIFIER_MUTATED_CANDIDATE = "verifier_mutated_candidate"
    CORRUPTED_RECEIPT_BINDING = "corrupted_receipt_binding"


# Card witness order (1-7), preserved for the run_witnesses.py report.
WITNESS_INDEX: dict[int, ReasonCode] = {
    1: ReasonCode.ACCEPTANCE_COMMAND_MUTATED_POST_FREEZE,
    2: ReasonCode.SCOPE_ESCAPE,
    3: ReasonCode.BASE_COMMIT_DRIFT,
    4: ReasonCode.EMPTY_PATCH_NOT_ACCEPTED,
    5: ReasonCode.ACCEPTANCE_FAILED_REJECTED,
    6: ReasonCode.VERIFIER_MUTATED_CANDIDATE,
    7: ReasonCode.CORRUPTED_RECEIPT_BINDING,
}

# Exact substrings tier_runner.core.{run_task,verify_run} emit for each
# reason (confirmed by reading core.py, one signature per witness so they
# cannot collide). classify() is the single place raw tier_runner text is
# turned into a closed code.
_SIGNATURES: dict[ReasonCode, tuple[str, ...]] = {
    ReasonCode.ACCEPTANCE_COMMAND_MUTATED_POST_FREEZE: (
        "dispatch acceptance_sha256 does not bind the final receipt",
    ),
    ReasonCode.SCOPE_ESCAPE: (
        "backend changed files outside --files scope",
    ),
    ReasonCode.BASE_COMMIT_DRIFT: (
        "is not committed at base",
    ),
    ReasonCode.EMPTY_PATCH_NOT_ACCEPTED: (
        "backend produced no repository changes",
    ),
    ReasonCode.ACCEPTANCE_FAILED_REJECTED: (
        "acceptance failed with rc=",
    ),
    ReasonCode.VERIFIER_MUTATED_CANDIDATE: (
        "acceptance command mutated the candidate",
    ),
    ReasonCode.CORRUPTED_RECEIPT_BINDING: (
        "dispatch arm does not bind the final receipt",
    ),
}


def classify(messages: str | Iterable[str]) -> ReasonCode | None:
    """Map tier_runner error text to exactly one closed reason code.

    Returns None when zero or more than one signature matches — an
    unrecognized or ambiguous failure is never coerced into a code; callers
    must treat None as WITNESS-BLOCKED, not as a pass.
    """
    if isinstance(messages, str):
        messages = [messages]
    blob = "\n".join(messages)
    matches = [
        code for code, signatures in _SIGNATURES.items()
        if any(signature in blob for signature in signatures)
    ]
    if len(matches) != 1:
        return None
    return matches[0]
