"""Deterministic driver-boundary pilot administration tests; zero model calls."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tier_runner.pilot import (
    ARMS,
    CLOSEOUT_SCHEMA,
    EVIDENCE_SCHEMA,
    PLAN_SCHEMA,
    RESIDUAL_ORDERS,
    PilotError,
    audit_label,
    canonical_json,
    close_pilot,
    derive_schedule,
    sha256_bytes,
    sha256_file,
    validate_plan,
)


PROTOCOL = "0" * 39 + "1"
BACKEND = "b" * 64
BASE = "a" * 40
SEED = bytes(range(32))
UTC = timezone.utc


def _write(path: Path, raw: bytes) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"path": path.as_posix(), "sha256": sha256_bytes(raw)}


def _relative_artifact(root: Path, relative: str, raw: bytes) -> dict:
    artifact = _write(root / relative, raw)
    artifact["path"] = relative
    return artifact


def _plan() -> dict:
    tasks = [
        {
            "task_id": f"real-{index:02d}",
            "base_commit": BASE,
            "task": f"Make deterministic change {index}",
            "files": [f"src/item_{index}.py"],
            "acceptance_command": f"pytest tests/test_item_{index}.py -q",
            "withheld_audit_sha256": sha256_bytes(canonical_json({"audit": index})),
        }
        for index in range(1, 11)
    ]
    plan = {
        "schema": PLAN_SCHEMA,
        "pilot_id": "axm-core-feasibility-001",
        "protocol_commit": PROTOCOL,
        "backend_manifest_sha256": BACKEND,
        "intervention_log_path": "pilot/interventions.jsonl",
        "follow_up_days": 14,
        "audit_label_seed_commitment_sha256": sha256_bytes(SEED),
        "residual_order_enumeration": list(RESIDUAL_ORDERS),
        "tasks": tasks,
        "schedule": [],
    }
    plan["schedule"] = derive_schedule(tasks, PROTOCOL)
    return plan


def _call(
    task_id: str,
    arm: str,
    dispatch_sha: str,
    *,
    cost_basis: str = "subscription-derived",
) -> dict:
    return {
        "ts": "2026-01-01T00:00:00Z",
        "account": "pilot-subscription" if cost_basis != "real-billed" else "pilot-api",
        "model": "fixture-model",
        "tier": "fixture",
        "task_id": task_id,
        "phase": arm,
        "outcome": "pass",
        "effort": "low",
        "input_tokens": 1,
        "output_tokens": 1,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": 0.0 if cost_basis != "real-billed" else 0.25,
        "latency_ms": 1,
        "trial": 1,
        "note": cost_basis,
        "extra": {
            "backend_manifest_sha256": BACKEND,
            "backend_surface": "fixture",
            "cost_basis": cost_basis,
            "dispatch_receipt_sha256": dispatch_sha,
            "prompt_template_sha256": "c" * 64,
            "runtime_model_id": "fixture-model",
            "session_id": f"session-{task_id}-{arm}",
            "telemetry_complete": True,
            "tool_versions": {"fixture": "1"},
        },
    }


def _audit(
    plan: dict, task_id: str, final_seal: datetime, withheld_audit: dict
) -> dict:
    label_map = {
        arm: audit_label(SEED, plan["pilot_id"], task_id, arm) for arm in ARMS
    }
    scores = sorted(
        [
            {
                "opaque_label": label_map[arm],
                "repository_ci": True,
                "scope_ok": True,
                "operator_accepted": True,
                "escaped_defects": 0,
            }
            for arm in ARMS
        ],
        key=lambda row: row["opaque_label"],
    )
    closes = final_seal + timedelta(days=14)
    return {
        "task_id": task_id,
        "withheld_audit": withheld_audit,
        "final_arm_sealed_at": final_seal.isoformat().replace("+00:00", "Z"),
        "followup_closes_at": closes.isoformat().replace("+00:00", "Z"),
        "scores": scores,
        "scores_sha256": sha256_bytes(canonical_json(scores)),
        "scores_sealed_at": (closes + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        "unblinded_at": (closes + timedelta(seconds=2)).isoformat().replace("+00:00", "Z"),
        "label_map": label_map,
    }


def _fixture(root: Path, *, real_billed: bool = False) -> tuple[Path, Path, dict, dict]:
    root.mkdir(parents=True, exist_ok=True)
    plan = _plan()
    plan_path = root / "plan.json"
    plan_raw = canonical_json(plan)
    plan_path.write_bytes(plan_raw)
    interventions = root / plan["intervention_log_path"]
    interventions.parent.mkdir(parents=True, exist_ok=True)
    interventions.write_bytes(b"")
    arm_runs = []
    task_by_id = {task["task_id"]: task for task in plan["tasks"]}
    seals_by_task: dict[str, list[datetime]] = {task_id: [] for task_id in task_by_id}
    for schedule_index, scheduled in enumerate(plan["schedule"]):
        task = task_by_id[scheduled["task_id"]]
        arm = scheduled["arm"]
        prefix = f"artifacts/{task['task_id']}/{arm}"
        dispatch = _relative_artifact(
            root,
            f"{prefix}/dispatch.json",
            canonical_json({"task_id": task["task_id"], "arm": arm}),
        )
        basis = "real-billed" if real_billed and schedule_index == 0 else "subscription-derived"
        ledger_raw = canonical_json(
            _call(task["task_id"], arm, dispatch["sha256"], cost_basis=basis)
        )
        ledger = _relative_artifact(root, f"{prefix}/ledger.jsonl", ledger_raw)
        seal_time = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(
            minutes=scheduled["sequence"]
        )
        seals_by_task[task["task_id"]].append(seal_time)
        arm_runs.append({
            "task_id": task["task_id"],
            "arm": arm,
            "sequence": scheduled["sequence"],
            "position": scheduled["position"],
            "base_commit": task["base_commit"],
            "sealed_at": seal_time.isoformat().replace("+00:00", "Z"),
            "final_state": "ACCEPTED",
            "protocol_valid": True,
            "seal_sha256": hashlib.sha256(f"{task['task_id']}:{arm}".encode()).hexdigest(),
            "dispatch_receipts": [dispatch],
            "ledger": ledger,
        })
    audits = []
    for task_index, task in enumerate(plan["tasks"], 1):
        withheld = _relative_artifact(
            root,
            f"audits/{task['task_id']}.json",
            canonical_json({"audit": task_index}),
        )
        audits.append(_audit(plan, task["task_id"], max(seals_by_task[task["task_id"]]), withheld))
    authorization_payload = {
        "schema": "tier-bench/tier-pilot-authorization@1",
        "pilot_id": plan["pilot_id"],
        "plan_sha256": sha256_bytes(plan_raw),
        "backend_manifest_sha256": BACKEND,
        "protocol_commit": plan["protocol_commit"],
        "authority": "operator",
        "authorized": True,
        "ratified_at": "2025-12-31T23:59:00Z",
    }
    authorization = _relative_artifact(
        root, "pilot/operator-authorization.json", canonical_json(authorization_payload)
    )
    evidence = {
        "schema": EVIDENCE_SCHEMA,
        "pilot_id": plan["pilot_id"],
        "plan_sha256": sha256_bytes(plan_raw),
        "backend_manifest_sha256": BACKEND,
        "intervention_log": {
            "path": plan["intervention_log_path"],
            "sha256": sha256_file(interventions),
            "head_sha256": None,
        },
        "arm_runs": arm_runs,
        "voids": [],
        "audit_seed_reveal_hex": SEED.hex(),
        "audits": audits,
        "operator_authorization": authorization,
        "cost_reconciliation": [
            {"account": "pilot-api", "billed_usd": 0.25, "tolerance_fraction": 0.01}
        ] if real_billed else [],
    }
    evidence_path = root / "evidence.json"
    evidence_path.write_bytes(canonical_json(evidence))
    return plan_path, evidence_path, plan, evidence


def _rewrite(path: Path, value: dict) -> None:
    path.write_bytes(canonical_json(value))


def _must_refuse(
    plan_path: Path,
    evidence_path: Path,
    needle: str,
    *,
    as_of: datetime = datetime(2026, 1, 20, tzinfo=UTC),
) -> None:
    try:
        close_pilot(plan_path, evidence_path, as_of=as_of)
    except PilotError as exc:
        assert needle in str(exc), str(exc)
    else:
        raise AssertionError(f"closeout accepted evidence expected to fail with {needle!r}")


def test_schedule_is_exact_and_balanced(_: Path) -> None:
    plan = _plan()
    assert validate_plan(plan) == []
    rows = plan["schedule"]
    assert len(rows) == 30
    for task_id in sorted(task["task_id"] for task in plan["tasks"]):
        task_rows = [row for row in rows if row["task_id"] == task_id]
        assert {row["arm"] for row in task_rows} == set(ARMS)
        assert {row["base_commit"] for row in task_rows} == {BASE}
    first_nine = sorted(plan["tasks"], key=lambda row: row["task_id"])[:9]
    for index, task in enumerate(first_nine):
        task_rows = [row for row in rows if row["task_id"] == task["task_id"]]
        assert "".join(arm[-1].upper() for arm in [row["arm"] for row in task_rows]) == (
            "ABC", "BCA", "CAB"
        )[index % 3]


def test_plan_refuses_wrong_count_and_enumeration(_: Path) -> None:
    plan = _plan()
    plan["tasks"].pop()
    errors = validate_plan(plan)
    assert any("exactly 10" in error for error in errors)
    plan = _plan()
    plan["residual_order_enumeration"] = list(reversed(RESIDUAL_ORDERS))
    errors = validate_plan(plan)
    assert any("GATED proposal" in error for error in errors)


def test_plan_refuses_hand_edited_schedule(_: Path) -> None:
    plan = _plan()
    plan["schedule"][0]["arm"] = "arm_c"
    assert any("does not equal" in error for error in validate_plan(plan))


def test_complete_closeout_mints_no_scientific_verdict(root: Path) -> None:
    plan_path, evidence_path, _, _ = _fixture(root)
    receipt = close_pilot(
        plan_path, evidence_path, as_of=datetime(2026, 1, 20, tzinfo=UTC)
    )
    assert receipt["schema"] == CLOSEOUT_SCHEMA
    assert receipt["administrative_state"] == "ADMINISTRATIVELY_COMPLETE"
    assert receipt["completed_tasks"] == 10
    assert receipt["scientific_verdict_minted"] is False
    assert receipt["feasibility_readout_permitted"] is True
    assert receipt["equivalence_claim_permitted"] is False
    assert receipt["noninferiority_claim_permitted"] is False


def test_four_atomic_voids_demote_to_partial_without_replacement(root: Path) -> None:
    plan_path, evidence_path, _, evidence = _fixture(root)
    voided = {f"real-{index:02d}" for index in range(1, 5)}
    evidence["arm_runs"] = [
        row for row in evidence["arm_runs"] if row["task_id"] not in voided
    ]
    evidence["audits"] = [row for row in evidence["audits"] if row["task_id"] not in voided]
    for task_id in sorted(voided):
        artifact = _relative_artifact(
            root, f"voids/{task_id}.json", canonical_json({"reason": "fixture fault"})
        )
        evidence["voids"].append({
            "task_id": task_id,
            "reason_code": "other_protocol_fault",
            "detail": "fixture protocol fault",
            "recorded_at": "2026-01-01T01:00:00Z",
            "evidence": artifact,
        })
    _rewrite(evidence_path, evidence)
    receipt = close_pilot(
        plan_path, evidence_path, as_of=datetime(2026, 1, 20, tzinfo=UTC)
    )
    assert receipt["administrative_state"] == "PARTIAL"
    assert receipt["completed_tasks"] == 6
    assert receipt["voided_tasks"] == 4
    assert receipt["tasks_total"] == 10
    assert receipt["no_replacement"] is True
    assert receipt["feasibility_readout_permitted"] is False


def test_missing_arm_without_void_fails_closed(root: Path) -> None:
    plan_path, evidence_path, _, evidence = _fixture(root)
    evidence["arm_runs"].pop()
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "does not have all three arm seals")


def test_protocol_invalid_arm_requires_whole_task_void(root: Path) -> None:
    plan_path, evidence_path, _, evidence = _fixture(root)
    evidence["arm_runs"][0]["protocol_valid"] = False
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "atomically void")


def test_dispatch_ledger_completeness_is_bidirectional(root: Path) -> None:
    plan_path, evidence_path, _, evidence = _fixture(root)
    extra = _relative_artifact(
        root, "artifacts/real-01/arm_a/extra-dispatch.json", canonical_json({"extra": True})
    )
    evidence["arm_runs"][0]["dispatch_receipts"].append(extra)
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "completeness is not bidirectional")


def test_arm_run_must_follow_frozen_schedule(root: Path) -> None:
    plan_path, evidence_path, _, evidence = _fixture(root)
    evidence["arm_runs"][0]["position"] = 3
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "deviates from the frozen schedule")


def test_withheld_audit_commitment_must_open(root: Path) -> None:
    plan_path, evidence_path, _, evidence = _fixture(root)
    replacement = _relative_artifact(
        root, "audits/replacement.json", canonical_json({"audit": "different"})
    )
    evidence["audits"][0]["withheld_audit"] = replacement
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "does not open the task commitment")


def test_operator_authorization_binds_exact_plan(root: Path) -> None:
    plan_path, evidence_path, _, evidence = _fixture(root)
    authorization = {
        "schema": "tier-bench/tier-pilot-authorization@1",
        "pilot_id": evidence["pilot_id"],
        "plan_sha256": "0" * 64,
        "backend_manifest_sha256": BACKEND,
        "protocol_commit": PROTOCOL,
        "authority": "operator",
        "authorized": True,
        "ratified_at": "2025-12-31T23:59:00Z",
    }
    evidence["operator_authorization"] = _relative_artifact(
        root, "pilot/tampered-authorization.json", canonical_json(authorization)
    )
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "plan_sha256 is not ratified")


def test_audit_mapping_and_followup_are_fail_closed(root: Path) -> None:
    plan_path, evidence_path, _, evidence = _fixture(root)
    evidence["audits"][0]["label_map"]["arm_a"] = "audit-" + "0" * 20
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "does not match the committed seed")
    _, evidence_path, _, evidence = _fixture(root / "early")
    _must_refuse(
        root / "early" / "plan.json",
        evidence_path,
        "follow-up window is still open",
        as_of=datetime(2026, 1, 10, tzinfo=UTC),
    )


def test_real_billed_rows_reconcile_and_drift_refuses(root: Path) -> None:
    plan_path, evidence_path, _, evidence = _fixture(root, real_billed=True)
    receipt = close_pilot(
        plan_path, evidence_path, as_of=datetime(2026, 1, 20, tzinfo=UTC)
    )
    assert receipt["administrative_state"] == "ADMINISTRATIVELY_COMPLETE"
    evidence["cost_reconciliation"][0]["billed_usd"] = 1.0
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "does not reconcile")


def test_canonical_intervention_path_is_bound(root: Path) -> None:
    plan_path, evidence_path, _, evidence = _fixture(root)
    evidence["intervention_log"]["path"] = "pilot/another.jsonl"
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "differs from the canonical plan path")


def main() -> int:
    tests = [
        test_schedule_is_exact_and_balanced,
        test_plan_refuses_wrong_count_and_enumeration,
        test_plan_refuses_hand_edited_schedule,
        test_complete_closeout_mints_no_scientific_verdict,
        test_four_atomic_voids_demote_to_partial_without_replacement,
        test_missing_arm_without_void_fails_closed,
        test_protocol_invalid_arm_requires_whole_task_void,
        test_dispatch_ledger_completeness_is_bidirectional,
        test_arm_run_must_follow_frozen_schedule,
        test_withheld_audit_commitment_must_open,
        test_operator_authorization_binds_exact_plan,
        test_audit_mapping_and_followup_are_fail_closed,
        test_real_billed_rows_reconcile_and_drift_refuses,
        test_canonical_intervention_path_is_bound,
    ]
    parent = Path(tempfile.mkdtemp(prefix="tier-pilot-admin-tests-"))
    try:
        for index, test in enumerate(tests):
            case = parent / f"case-{index}"
            case.mkdir()
            test(case)
        print(f"OK — {len(tests)}/{len(tests)} pilot-admin tests passed; zero model calls")
        return 0
    finally:
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
