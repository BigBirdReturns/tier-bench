#!/usr/bin/env python3
"""Executable witness models for the SOL-4 constitution review.

These are attacks on the predicates stated by draft-v0.4 §§12.1–12.4, not
tests of a recorder implementation (none is authorized yet).  Each witness
satisfies the clause's explicit decision inputs while retaining a fact that
violates the clause's intended safety or measurement property.
"""

from __future__ import annotations


def accepts_key_custody(record: dict) -> bool:
    """The six explicit temporary-data-key predicates in §12.1."""
    return all(
        (
            record["capture_only"],
            record["wrapped_before_persist"],
            record["bound_to_session_surface_manifest"],
            not record["plaintext_key_at_destination"],
            record["plaintext_key_destroyed_after_ack"],
            record["recovery_tested"],
            record["root_key_outside_ephemeral_runtime"],
        )
    )


def provisional_instruction_is_normative(message: dict) -> bool:
    """The positive admission path expressly allowed by §12.2."""
    return all(
        (
            message["through_designated_operator_channel"],
            message["assumption_logged"],
            message["session_specific"],
            message["visible_to_reducer"],
            message["revocable"],
            message["privacy_and_safety_subordinate"],
            message["source_kind"] == "platform_attributed_user_message",
        )
    )


def admission_record_is_complete(record: dict) -> bool:
    """The nine minimum admission bindings required by §12.3."""
    required = {
        "implementation_hash",
        "event_schema_version",
        "client_range",
        "hook_config_hash",
        "redaction_policy_version",
        "key_custody_config",
        "destination_manifest_versions",
        "test_suite_version",
        "last_success_evidence",
    }
    return required <= record.keys() and all(record[key] for key in required)


def drift_disposition(event: dict) -> str:
    """One of the three dispositions §12.3 permits for missing fields."""
    if event["missing_expected_fields"] and event["declared_downgrade_exists"]:
        return "admitted_lower_fidelity"
    return "rejected"


def primary_accuracy(rows: list[dict], predeclared_operator_inclusion: bool) -> float:
    """Apply §12.4's express predeclared-protocol exception and exclusions."""
    included = []
    for row in rows:
        if row["resolution"] == "operator":
            if predeclared_operator_inclusion:
                included.append(row)
        elif row["resolution"] == "independent":
            included.append(row)
        # Unresolved and conflict-excluded rows are reported separately.
    return sum(row["reported_correct"] for row in included) / len(included)


def witness_key_authority_single_point_of_failure() -> None:
    record = {
        "capture_only": True,
        "wrapped_before_persist": True,
        "bound_to_session_surface_manifest": True,
        "plaintext_key_at_destination": False,
        "plaintext_key_destroyed_after_ack": True,
        "recovery_tested": True,
        "root_key_outside_ephemeral_runtime": True,
        # Not constrained by the six predicates: one protected but unreplicated
        # root-key copy expires before the Genesis retention horizon.
        "root_key_copies": 1,
        "key_retention_days": 30,
        "genesis_retention_days": 365,
    }
    assert accepts_key_custody(record)
    assert record["root_key_copies"] == 1
    assert record["key_retention_days"] < record["genesis_retention_days"]


def witness_checkpoint_key_overwrite() -> None:
    wrapped_keys: dict[tuple[str, str, str], str] = {}
    checkpoints = ["checkpoint-1", "checkpoint-2", "checkpoint-3"]
    binding = ("session-a", "surface-a", "manifest-a")
    for checkpoint in checkpoints:
        # Every write is bound to the session/surface/manifest tuple and its
        # immediate recovery probe succeeds, but the tuple is not object-unique.
        wrapped_keys[binding] = f"wrapped-dek-for-{checkpoint}"
        assert wrapped_keys[binding] == f"wrapped-dek-for-{checkpoint}"
    recoverable = [
        wrapped_keys.get(binding) == f"wrapped-dek-for-{checkpoint}"
        for checkpoint in checkpoints
    ]
    assert recoverable == [False, False, True]


def witness_provisional_channel_self_escalation() -> None:
    message = {
        "through_designated_operator_channel": True,
        "assumption_logged": True,
        "session_specific": True,
        "visible_to_reducer": True,
        "revocable": True,
        "privacy_and_safety_subordinate": True,
        "source_kind": "platform_attributed_user_message",
        # The platform, not the human, injected a role=user event.  Section
        # 12.2 has no effect ceiling or step-up rule for provisional authority.
        "actual_origin": "host_injection",
        "requested_action": "replace_operator_channel_and_export_genesis",
    }
    assert provisional_instruction_is_normative(message)
    assert message["actual_origin"] != "human_operator"
    assert message["requested_action"].startswith("replace_operator_channel")


def witness_admission_self_grading() -> None:
    record = {
        "implementation_hash": "sha256:capturer",
        "event_schema_version": "4",
        "client_range": "2026.*",
        "hook_config_hash": "sha256:hooks",
        "redaction_policy_version": "3",
        "key_custody_config": "kms-a",
        "destination_manifest_versions": "store-2/manifest-5",
        "test_suite_version": "stable",  # A mutable name, not a content hash.
        "last_success_evidence": "capturer says PASS",
        "capturer_id": "recorder-a",
        "admission_evaluator_id": "recorder-a",
    }
    assert admission_record_is_complete(record)
    assert record["capturer_id"] == record["admission_evaluator_id"]
    assert not record["test_suite_version"].startswith("sha256:")


def witness_security_field_downgrade() -> None:
    event = {
        "missing_expected_fields": ["operator_origin_authentication"],
        "declared_downgrade_exists": True,
        "downstream_status": "authoritative",
    }
    assert drift_disposition(event) == "admitted_lower_fidelity"
    assert event["downstream_status"] == "authoritative"


def witness_predeclared_subject_label_inclusion() -> None:
    rows = [
        {
            "resolution": "operator",
            "operator_saw_forecast": True,
            "reported_correct": 1,
            "blinded_independent_correct": 0,
        }
        for _ in range(4)
    ]
    assert primary_accuracy(rows, predeclared_operator_inclusion=True) == 1.0
    assert sum(row["blinded_independent_correct"] for row in rows) == 0


def witness_denominator_selection() -> None:
    rows = [
        {"resolution": "independent", "reported_correct": 1},
        {"resolution": "independent", "reported_correct": 1},
        {"resolution": "unresolved", "reported_correct": 0},
        {"resolution": "unresolved", "reported_correct": 0},
    ]
    assert primary_accuracy(rows, predeclared_operator_inclusion=False) == 1.0
    assert sum(row["reported_correct"] for row in rows) / len(rows) == 0.5


def main() -> int:
    witnesses = [
        witness_key_authority_single_point_of_failure,
        witness_checkpoint_key_overwrite,
        witness_provisional_channel_self_escalation,
        witness_admission_self_grading,
        witness_security_field_downgrade,
        witness_predeclared_subject_label_inclusion,
        witness_denominator_selection,
    ]
    for witness in witnesses:
        witness()
        print(f"WITNESS {witness.__name__}: clause predicates pass; intent fails")
    print(f"{len(witnesses)}/{len(witnesses)} adversarial witnesses reproduced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
