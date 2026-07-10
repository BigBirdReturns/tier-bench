#!/usr/bin/env python3
"""Tests for scripts/validate_capture_ledger.py — the closure rules must bite.

Runs under pytest or standalone (`python tests/test_capture_ledger.py`), stdlib
only. Happy path = the committed ledger validates; failure cases prove each
burden/closure rule rejects.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import validate_capture_ledger as vc  # noqa: E402

WL = {"task02_wildcard", "task01_parse_duration"}


def _capture(**over):
    """A valid baseline capture row; override fields to build failure cases."""
    row = {
        "record_type": "capture",
        "capture_id": "example_capture",
        "source_task_id": "task02_wildcard",
        "driver_model": "claude-sonnet-5",
        "driver_role": "residue_resolver",
        "capture_cost_usd": 0.5,
        "cost_basis": "real-billed",
        "captured_artifact": {
            "type": "edge_family",
            "path": "experiments/breadth/run/task02_edge_family.md",  # really exists
            "description": "a rule commitment",
        },
        "old_path": {"model": "claude-haiku-4-5", "status": "unstable", "success": "3/5",
                     "cost_usd_per_trial": 0.04, "cost_basis": "shadow-estimated"},
        "new_path": {"model": "claude-sonnet-5", "status": "cleared", "success": "3/3",
                     "cost_usd_per_trial": 0.227, "cost_basis": "real-billed"},
        "break_even_reuse_count": None,
        "validated_replays": 0,
        "replay_evidence": [],
        "waterline_effect": "moved to named residue",
        "status": "captured_not_yet_amortized",
        "burden": {
            "requested_outcome": "treat judgment as captured machinery",
            "claimant": "breadth self-run",
            "authority": "task02 hidden grader",
            "predicates": ["artifact exists", "floor+artifact clears hidden grader (not yet run)"],
            "burden_holder": "replay runner",
            "evidence": ["ledger.jsonl sonnet rows"],
            "verifier": "scripts/validate_capture_ledger.py + hidden grader",
            "gap": "zero validated replays",
            "closure_decision": "needs_replay",
            "failure_default": "stays non-closed; projection never promoted",
        },
    }
    row = copy.deepcopy(row)
    row.update(copy.deepcopy(over))
    return row


def _has(errs, needle):
    return any(needle in e for e in errs)


# ---- happy paths ----

def test_committed_ledger_is_valid():
    files = sorted((REPO / "data/capture").glob("*.jsonl"))
    assert files, "expected at least the task02 worked example"
    wl = vc.waterline_task_ids()
    for f in files:
        errs, n_cap, n_delta = vc.validate_file(f, wl)
        assert errs == [], f"{f.name} should be clean, got:\n" + "\n".join(errs)
    # the worked example specifically
    errs, n_cap, n_delta = vc.validate_file(
        REPO / "data/capture/task02_escape_class_boundary.jsonl", wl)
    assert n_cap == 1 and n_delta == 1


def test_valid_capture_passes():
    assert vc.validate_capture(_capture(), WL) == []


def test_independent_of_data_results():
    # The capture pipeline has its own door: nothing in the validator reads
    # data/results (contribute.py's domain). Source-level check.
    src = (REPO / "scripts/validate_capture_ledger.py").read_text()
    assert "data/results" not in src


# ---- closure rules must reject ----

def test_amortized_without_replays_fails():
    errs = vc.validate_capture(_capture(status="amortized"), WL)
    assert _has(errs, "zero validated replays")


def test_closed_decision_without_replays_fails():
    row = _capture()
    row["burden"]["closure_decision"] = "closed"
    errs = vc.validate_capture(row, WL)
    assert _has(errs, "'closed' with zero validated replays")


def test_break_even_stored_without_replays_fails():
    errs = vc.validate_capture(_capture(break_even_reuse_count=4), WL)
    assert _has(errs, "null until closure")


def test_replays_without_evidence_fails():
    errs = vc.validate_capture(_capture(validated_replays=2, replay_evidence=[]), WL)
    assert _has(errs, "fabricated receipt")


def test_missing_artifact_path_fails():
    row = _capture()
    row["captured_artifact"]["path"] = "no/such/file.md"
    errs = vc.validate_capture(row, WL)
    assert _has(errs, "does not exist")


def test_invalid_cost_basis_fails():
    errs = vc.validate_capture(_capture(cost_basis="vibes"), WL)
    assert _has(errs, "invalid cost_basis")


def test_all_four_evidence_classes_accepted():
    for basis in ("real-billed", "shadow-estimated", "subscription-derived",
                  "repaired-transport-adjudicated"):
        errs = vc.validate_capture(_capture(cost_basis=basis), WL)
        assert errs == [], f"basis {basis} should be legal, got: {errs}"


def test_missing_burden_field_fails():
    row = _capture()
    del row["burden"]["failure_default"]
    errs = vc.validate_capture(row, WL)
    assert _has(errs, "burden.failure_default")


def test_waterline_effect_with_unresolvable_task_fails():
    errs = vc.validate_capture(_capture(source_task_id="task_unknown"), WL)
    assert _has(errs, "resolves to no waterline cell")


def test_validator_never_writes_waterline():
    src = (REPO / "scripts/validate_capture_ledger.py").read_text()
    assert "waterline.json" in src  # it reads it...
    # ...but only ever via read_text; no write API appears anywhere.
    assert "write_text" not in src and "json.dump(" not in src


# ---- replay identity rules (P1 remediation 2026-07-10: closure depends on ----
# ---- distinct hash-bound replay events, never list length or assertions)  ----

import hashlib


def _sha(relpath):
    return hashlib.sha256((REPO / relpath).read_bytes()).hexdigest()


_RECEIPT = "experiments/breadth/run/replays/task02_wildcard/replay_receipt_20260710.md"
_CAND = "experiments/breadth/run/replays/task02_wildcard/replay01_candidate.py"
_GRADE = "experiments/breadth/run/replays/task02_wildcard/grader_output_20260710.txt"
_PACKET = "experiments/breadth/run/replays/task02_wildcard/scaffold_packet_20260710.md"
_ARTIFACT = "experiments/breadth/run/task02_edge_family.md"


def _replay_item(**over):
    item = {
        "work_item_id": "task02_wildcard@haiku+scaffold_packet/20260710",
        "receipt_path": _RECEIPT, "receipt_sha256": _sha(_RECEIPT),
        "candidate_path": _CAND, "candidate_sha256": _sha(_CAND),
        "grader_output_path": _GRADE, "grader_output_sha256": _sha(_GRADE),
        "packet_path": _PACKET, "packet_sha256": _sha(_PACKET),
        "artifact_sha256": _sha(_ARTIFACT),
        "description": "hash-bound replay event",
    }
    item.update(over)
    return item


def test_structured_replay_item_passes():
    row = _capture(validated_replays=1, replay_evidence=[_replay_item()])
    assert vc.validate_capture(row, WL) == []


def test_dummy_receipts_cannot_buy_amortization():
    row = _capture(status="amortized", validated_replays=4,
                   replay_evidence=[{} for _ in range(4)])
    errs = vc.validate_capture(row, vc.waterline_task_ids())
    assert _has(errs, "bare counter is not a receipt")


def test_receipt_pointing_at_nothing_fails():
    row = _capture(validated_replays=1,
                   replay_evidence=[_replay_item(
                       receipt_path="experiments/breadth/run/DOES_NOT_EXIST.md")])
    errs = vc.validate_capture(row, vc.waterline_task_ids())
    assert _has(errs, "validates nothing")


def test_one_replay_cannot_close_a_four_replay_projection():
    # capture_cost 0.5 over savings 0.187 -> computed break-even 3; use costs
    # that project 4 to mirror the committed row: 0.6805 / 0.187 -> 4
    row = _capture(capture_cost_usd=0.6805, status="amortized",
                   validated_replays=1, replay_evidence=[_replay_item()])
    row["burden"]["closure_decision"] = "closed"
    row["break_even_reuse_count"] = 4
    errs = vc.validate_capture(row, WL)
    assert _has(errs, "computed break-even of 4")


def test_same_receipt_bytes_cannot_credit_twice_under_different_labels():
    row = _capture(validated_replays=2, replay_evidence=[
        _replay_item(),
        _replay_item(work_item_id="a_different_label"),
    ])
    errs = vc.validate_capture(row, WL)
    assert _has(errs, "cannot buy two replays")


def test_duplicate_work_item_id_rejected():
    row = _capture(validated_replays=2, replay_evidence=[
        _replay_item(),
        _replay_item(receipt_path=_GRADE, receipt_sha256=_sha(_GRADE)),
    ])
    errs = vc.validate_capture(row, WL)
    assert _has(errs, "duplicate work_item_id")


def test_declared_validated_replays_mismatch_rejected():
    row = _capture(validated_replays=3, replay_evidence=[_replay_item()])
    errs = vc.validate_capture(row, WL)
    assert _has(errs, "redundant assertion")


def test_wrong_hash_rejected():
    row = _capture(validated_replays=1,
                   replay_evidence=[_replay_item(candidate_sha256="0" * 64)])
    errs = vc.validate_capture(row, WL)
    assert _has(errs, "the bytes decide")


def test_artifact_binding_enforced():
    row = _capture(validated_replays=1,
                   replay_evidence=[_replay_item(artifact_sha256="0" * 64)])
    errs = vc.validate_capture(row, WL)
    assert _has(errs, "carried THIS artifact")


def test_identical_candidate_bytes_are_two_replays_when_identities_distinct():
    # distinct work items + distinct receipts, same candidate bytes: eligible x2
    row = _capture(validated_replays=2, replay_evidence=[
        _replay_item(),
        _replay_item(work_item_id="task02_variant_b/20260710",
                     receipt_path=_GRADE, receipt_sha256=_sha(_GRADE)),
    ])
    assert vc.validate_capture(row, WL) == []


def test_asserted_break_even_mismatch_rejected_at_closure():
    # computed break-even for these costs is 3 (0.5 / 0.187 -> ceil = 3)
    row = _capture(status="amortized", validated_replays=3, replay_evidence=[
        _replay_item(),
        _replay_item(work_item_id="b", receipt_path=_GRADE, receipt_sha256=_sha(_GRADE)),
        _replay_item(work_item_id="c", receipt_path=_PACKET, receipt_sha256=_sha(_PACKET)),
    ])
    row["burden"]["closure_decision"] = "closed"
    row["break_even_reuse_count"] = 99
    errs = vc.validate_capture(row, WL)
    assert _has(errs, "must equal the computed threshold (3)")


def test_legal_closure_at_computed_break_even_passes():
    row = _capture(status="amortized", validated_replays=3, replay_evidence=[
        _replay_item(),
        _replay_item(work_item_id="b", receipt_path=_GRADE, receipt_sha256=_sha(_GRADE)),
        _replay_item(work_item_id="c", receipt_path=_PACKET, receipt_sha256=_sha(_PACKET)),
    ])
    row["burden"]["closure_decision"] = "closed"
    row["break_even_reuse_count"] = 3
    assert vc.validate_capture(row, WL) == []


def test_break_even_must_stay_null_before_closure():
    row = _capture(validated_replays=1, replay_evidence=[_replay_item()],
                   break_even_reuse_count=4)
    errs = vc.validate_capture(row, WL)
    assert _has(errs, "null until closure")


def test_validator_and_roi_share_one_calculation():
    import capture_math
    import capture_roi
    src_v = (REPO / "scripts/validate_capture_ledger.py").read_text()
    src_r = (REPO / "scripts/capture_roi.py").read_text()
    assert "from capture_math import" in src_v
    assert "from capture_math import" in src_r
    assert "math.ceil" not in src_v and "math.ceil" not in src_r
    assert capture_math.projected_break_even(0.6805, 0.04, 0.227) == 4
    rep = capture_roi.roi_for({"capture_id": "x", "capture_cost_usd": 0.6805,
                               "cost_basis": "real-billed", "validated_replays": 0,
                               "old_path": {"cost_usd_per_trial": 0.04},
                               "new_path": {"cost_usd_per_trial": 0.227}})
    assert rep["projected_break_even_replays"] == 4


# ---- delta rules ----

def test_valid_delta_passes():
    d = {"record_type": "delta_observation", "from_model": "a", "to_model": "b",
         "task_id": "t", "delta_types": ["edge_delta"], "what_lower_missed": "x",
         "what_higher_added": "y", "capturable": True, "captured_as": "edge_family",
         "measured": False}
    assert vc.validate_delta(d) == []


def test_capturable_without_captured_as_fails():
    d = {"record_type": "delta_observation", "from_model": "a", "to_model": "b",
         "task_id": "t", "delta_types": ["edge_delta"], "what_lower_missed": "x",
         "what_higher_added": "y", "capturable": True, "measured": False}
    assert _has(vc.validate_delta(d), "captured_as")


def test_invalid_delta_type_fails():
    d = {"record_type": "delta_observation", "from_model": "a", "to_model": "b",
         "task_id": "t", "delta_types": ["vibes_delta"], "what_lower_missed": "x",
         "what_higher_added": "y", "capturable": False, "measured": False}
    assert _has(vc.validate_delta(d), "invalid delta_type")


def test_delta_without_measured_flag_fails():
    d = {"record_type": "delta_observation", "from_model": "a", "to_model": "b",
         "task_id": "t", "delta_types": ["edge_delta"], "what_lower_missed": "x",
         "what_higher_added": "y", "capturable": False}
    assert _has(vc.validate_delta(d), "measured")


def test_measured_delta_requires_resolvable_evidence_layer():
    d = {"record_type": "delta_observation", "from_model": "a", "to_model": "b",
         "task_id": "t", "delta_types": ["edge_delta"], "what_lower_missed": "x",
         "what_higher_added": "y", "capturable": False, "measured": True}
    assert _has(vc.validate_delta(d), "evidence_layer")
    d["evidence_layer"] = "no-such-layer"
    assert _has(vc.validate_delta(d, vc.corner_layers()), "does not resolve")
    d["evidence_layer"] = "model-ladder-task02-20260708"
    assert vc.validate_delta(d, vc.corner_layers()) == []


def _run_standalone() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
