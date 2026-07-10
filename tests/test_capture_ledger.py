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


# ---- replay authenticity + identity (P1: closure depends on DISTINCT, ----
# ---- hash-bound, RE-ATTESTED replay events — not files with unique hashes) ----

import hashlib
import json as _json
import tempfile


def _sha(relpath):
    return hashlib.sha256((REPO / relpath).read_bytes()).hexdigest()


def _cset(hashes):
    return hashlib.sha256(("\n".join(sorted(hashes)) + "\n").encode()).hexdigest()


def _newrepo():
    return Path(tempfile.mkdtemp(prefix="captest_"))


def _put(repo, rel, data: bytes):
    fp = repo / rel
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_bytes(data)
    return rel, hashlib.sha256(data).hexdigest()


def _event(repo, wid, *, cand=b"print(1)\n", admin="adm1", grader="grader.py",
           artifact_rel="artifact.md"):
    """Create per-work-item evidence files + a matching structured receipt in
    repo, and return the ledger event that binds them (agreeing field-for-field)."""
    slug = wid.replace("/", "_").replace("@", "_")
    cand_p, cand_h = _put(repo, f"ev/{slug}/candidate.py", cand)
    g_p, g_h = _put(repo, f"ev/{slug}/grader_output.txt", b"SCORE 10/10\n")
    pk_p, pk_h = _put(repo, f"ev/{slug}/packet.md", b"packet:" + slug.encode() + b"\n")
    art_h = hashlib.sha256((repo / artifact_rel).read_bytes()).hexdigest()
    cset = _cset([cand_h])
    receipt = {"schema_version": "tier-bench/replay-receipt@1", "work_item_id": wid,
               "administration_id": admin, "grader_id": grader, "verdict": "pass",
               "packet_sha256": pk_h, "candidate_sha256": cand_h,
               "candidate_set_sha256": cset, "grader_output_sha256": g_h,
               "artifact_sha256": art_h}
    rb = (_json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    r_p, r_h = _put(repo, f"ev/{slug}/receipt.json", rb)
    return {"work_item_id": wid, "receipt_path": r_p, "receipt_sha256": r_h,
            "candidate_path": cand_p, "candidate_sha256": cand_h,
            "grader_output_path": g_p, "grader_output_sha256": g_h,
            "packet_path": pk_p, "packet_sha256": pk_h, "artifact_sha256": art_h,
            "grader_id": grader, "administration_id": admin,
            "candidate_set_sha256": cset, "description": "hash-bound replay event"}


def _rowrepo(n=1, artifact=b"ARTIFACT\n", **capkw):
    repo = _newrepo()
    _put(repo, "artifact.md", artifact)
    row = _capture(**capkw)
    row["captured_artifact"]["path"] = "artifact.md"
    row["replay_evidence"] = [_event(repo, f"wi/{k}") for k in range(n)]
    row["validated_replays"] = n
    return row, repo


# ---- the P1 masquerade control: arbitrary files are not receipts ----

def test_authentic_single_replay_passes():
    row, repo = _rowrepo(1)
    assert vc.validate_capture(row, WL, repo=repo) == []


def test_four_arbitrary_files_as_receipts_cannot_buy_closure():
    """THE adversarial control (reviewer's exploit): point each 'receipt' at an
    arbitrary unique evidence file instead of a structured receipt. None may
    count, so a four-replay projection cannot close."""
    row, repo = _rowrepo(1, capture_cost_usd=0.6805)   # break-even = 4
    ev = row["replay_evidence"][0]
    fakes = []
    for k, src in enumerate(("grader_output_path", "packet_path", "candidate_path")):
        e = _json.loads(_json.dumps(ev))
        e["work_item_id"] = f"fake/{k}"
        e["receipt_path"] = ev[src]                      # evidence file posing as receipt
        e["receipt_sha256"] = hashlib.sha256((repo / ev[src]).read_bytes()).hexdigest()
        fakes.append(e)
    e = _json.loads(_json.dumps(ev))                     # 4th: the artifact itself
    e["work_item_id"] = "fake/3"
    e["receipt_path"] = "artifact.md"
    e["receipt_sha256"] = hashlib.sha256((repo / "artifact.md").read_bytes()).hexdigest()
    fakes.append(e)
    row["replay_evidence"] = fakes
    row["validated_replays"] = 4
    row["status"] = "amortized"
    row["burden"]["closure_decision"] = "closed"
    row["break_even_reuse_count"] = 4
    errs = vc.validate_capture(row, WL, repo=repo)
    assert _has(errs, "reuses an evidence file")         # none is a distinct structured receipt
    assert _has(errs, "computed break-even of 4") or _has(errs, "redundant assertion")


def test_receipt_reusing_evidence_path_rejected():
    row, repo = _rowrepo(1)
    ev = row["replay_evidence"][0]
    ev["receipt_path"] = ev["grader_output_path"]
    ev["receipt_sha256"] = ev["grader_output_sha256"]
    assert _has(vc.validate_capture(row, WL, repo=repo), "reuses an evidence file")


def test_nonstructured_receipt_file_rejected():
    row, repo = _rowrepo(1)
    ev = row["replay_evidence"][0]
    bad, bad_h = _put(repo, "ev/not_a_receipt.txt", b"hello\n")
    ev["receipt_path"] = bad
    ev["receipt_sha256"] = bad_h
    assert _has(vc.validate_capture(row, WL, repo=repo), "not a parseable")


def test_receipt_field_mismatch_rejected():
    row, repo = _rowrepo(1)
    row["replay_evidence"][0]["packet_sha256"] = "0" * 64   # event now disagrees w/ receipt
    errs = vc.validate_capture(row, WL, repo=repo)
    assert _has(errs, "the bytes decide") or _has(errs, "bind field-for-field")


def test_receipt_verdict_must_be_pass():
    row, repo = _rowrepo(1)
    ev = row["replay_evidence"][0]
    # rewrite the receipt file with verdict=fail, keep the hash in sync
    rp = repo / ev["receipt_path"]
    obj = _json.loads(rp.read_text()); obj["verdict"] = "fail"
    rb = (_json.dumps(obj, indent=2, sort_keys=True) + "\n").encode()
    rp.write_bytes(rb); ev["receipt_sha256"] = hashlib.sha256(rb).hexdigest()
    assert _has(vc.validate_capture(row, WL, repo=repo), "verdict must be")


def test_dummy_receipts_cannot_buy_amortization():
    row = _capture(status="amortized", validated_replays=4,
                   replay_evidence=[{} for _ in range(4)])
    assert _has(vc.validate_capture(row, vc.waterline_task_ids()), "bare counter is not a receipt")


# ---- identity + closure arithmetic ----

def test_two_distinct_work_items_identical_candidates_count_twice():
    row, repo = _rowrepo(0, capture_cost_usd=0.05)
    a = _event(repo, "wi/a", cand=b"same\n")
    b = _event(repo, "wi/b", cand=b"same\n")   # identical candidate bytes, distinct wid + receipt
    row["replay_evidence"] = [a, b]
    row["validated_replays"] = 2
    assert vc.validate_capture(row, WL, repo=repo) == []


def test_duplicate_work_item_id_rejected():
    row, repo = _rowrepo(0)
    row["replay_evidence"] = [_event(repo, "wi/x"), _event(repo, "wi/x")]
    row["validated_replays"] = 2
    assert _has(vc.validate_capture(row, WL, repo=repo), "duplicate work_item_id")


def test_one_replay_cannot_close_a_four_replay_projection():
    row, repo = _rowrepo(1, capture_cost_usd=0.6805)   # break-even 4
    row["status"] = "amortized"
    row["burden"]["closure_decision"] = "closed"
    row["break_even_reuse_count"] = 4
    assert _has(vc.validate_capture(row, WL, repo=repo), "computed break-even of 4")


def test_legal_closure_at_computed_break_even_passes():
    row, repo = _rowrepo(3, capture_cost_usd=0.5)       # savings .187 -> break-even 3
    row["status"] = "amortized"
    row["burden"]["closure_decision"] = "closed"
    row["break_even_reuse_count"] = 3
    assert vc.validate_capture(row, WL, repo=repo) == []


def test_declared_validated_replays_mismatch_rejected():
    row, repo = _rowrepo(1)
    row["validated_replays"] = 3
    assert _has(vc.validate_capture(row, WL, repo=repo), "redundant assertion")


def test_break_even_must_stay_null_before_closure():
    row, repo = _rowrepo(1)
    row["break_even_reuse_count"] = 4
    assert _has(vc.validate_capture(row, WL, repo=repo), "null until closure")


def test_wrong_candidate_hash_rejected():
    row, repo = _rowrepo(1)
    row["replay_evidence"][0]["candidate_sha256"] = "0" * 64
    assert _has(vc.validate_capture(row, WL, repo=repo), "the bytes decide")


def test_validator_and_roi_share_one_calculation():
    import capture_math
    import capture_roi
    src_v = (REPO / "scripts/validate_capture_ledger.py").read_text()
    src_r = (REPO / "scripts/capture_roi.py").read_text()
    assert "from capture_math import" in src_v
    assert "from capture_math import" in src_r
    assert "math.ceil" not in src_v and "math.ceil" not in src_r
    assert capture_math.projected_break_even(0.6805, 0.04, 0.227) == 4


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
