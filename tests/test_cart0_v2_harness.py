#!/usr/bin/env python3
"""Tests for the CART0 v2 harness — the manifest holds its invariants and the
runner captures custody, enforces the READY gate, and refuses a verdict on
incomplete/contaminated designs. Keyless (fake solver).
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
V2 = REPO / "experiments" / "breadth" / "cart0_abc_v2"
sys.path.insert(0, str(V2))

import runner as R  # noqa: E402
import validate_manifest as VM  # noqa: E402

MANIFEST = json.loads((V2 / "manifest.json").read_text(encoding="utf-8"))
SPEC = b"# count_matches spec (bare)\n"


def _grader(cand: bytes) -> dict:
    return {"passed": b"CORRECT" in cand, "detail": "marker"}


def _solver(*, rehearse=False, abort_turn=None, abort_arm=None, good=True):
    def solver(ctx):
        if ctx["turn"] == 1:
            if abort_turn == 1:
                return {"response": "", "candidate": None, "aborted": True}
            resp = "the backslash is a literal member inside a class" if rehearse else "READY"
            return {"response": resp, "candidate": None, "aborted": False,
                    "receipt": {"model": "fake", "usage_available": True}}
        if abort_turn == 2 and (abort_arm is None or ctx["arm"] == abort_arm):
            return {"response": "", "candidate": None, "aborted": True}
        body = b"def count_matches(p, w):\n    return 0  # CORRECT\n" if good else b"# wrong\n"
        return {"response": "0", "candidate": body, "aborted": False, "receipt": {"model": "fake"}}
    return solver


def _has(errs, needle):
    return any(needle in e for e in errs)


# ---- manifest validator (#3) ----

def test_committed_manifest_validates():
    assert VM.validate_manifest(MANIFEST) == []


def test_control_arm_resurfacing_rejected():
    m = copy.deepcopy(MANIFEST)
    m["arms"]["C"]["boundary_message"] = "remember: backslash is a literal member inside a class"
    assert _has(VM.validate_manifest(m), "must NOT resurface")


def test_missing_preservation_rejected():
    m = copy.deepcopy(MANIFEST)
    m["preservation_required"] = ["boot_prompt_bytes"]
    assert _has(VM.validate_manifest(m), "missing mandatory fields")


def test_k_zero_rejected():
    m = copy.deepcopy(MANIFEST)
    m["blocking"]["K"] = 0
    assert _has(VM.validate_manifest(m), "K must be an integer >= 1")


def test_planning_turn_rejected():
    m = copy.deepcopy(MANIFEST)
    m["protocol"]["no_planning_turn"] = False
    assert _has(VM.validate_manifest(m), "no_planning_turn")


def test_aborts_must_mint_neither():
    m = copy.deepcopy(MANIFEST)
    m["disposition"]["aborted_mints"] = "fail"
    assert _has(VM.validate_manifest(m), "must be 'neither'")


# ---- runner custody (#1) ----

def test_runner_produces_full_custody(tmp_path):
    rec = R.run_experiment(MANIFEST, _solver(), _grader, item_spec_bytes=SPEC, out_dir=tmp_path)
    K = MANIFEST["blocking"]["K"]
    rows = [json.loads(x) for x in (tmp_path / "administration.jsonl").read_text().splitlines()]
    assert len(rows) == K * 3                                   # balanced blocks
    assert (tmp_path / "boot_prompt.txt").exists()              # boot bytes preserved
    assert all(len(r["transcript"]) == 2 for r in rows)        # every message+response
    assert all("boot_prompt_sha256" in r for r in rows)
    assert len(list((tmp_path / "candidates").glob("*.py"))) == K * 3  # sealed candidates
    assert rec["readout"]["state"] == "complete"
    assert all(rec["readout"]["per_arm"][a]["pass"] == K for a in ("A", "B", "C"))
    # balanced-block order preserved
    assert [r["arm"] for r in rows[:3]] == ["A", "B", "C"]


def test_ready_gate_contaminates_rehearsal_without_losing_custody(tmp_path):
    rec = R.run_experiment(MANIFEST, _solver(rehearse=True), _grader, item_spec_bytes=SPEC, out_dir=tmp_path)
    rows = [json.loads(x) for x in (tmp_path / "administration.jsonl").read_text().splitlines()]
    assert all(r["outcome"] == "contaminated" for r in rows)   # rehearsal caught structurally
    assert all(r["transcript"] for r in rows)                  # custody NOT lost
    assert rec["readout"]["state"] == "NO_VERDICT"


def test_abort_mints_neither(tmp_path):
    rec = R.run_experiment(MANIFEST, _solver(abort_turn=2), _grader, item_spec_bytes=SPEC, out_dir=tmp_path)
    rows = [json.loads(x) for x in (tmp_path / "administration.jsonl").read_text().splitlines()]
    assert all(r["outcome"] in ("ineligible", "aborted") for r in rows)
    assert rec["readout"]["state"] == "NO_VERDICT"


def test_incomplete_block_is_no_verdict(tmp_path):
    m = copy.deepcopy(MANIFEST)
    m["blocking"]["K"] = 1
    rec = R.run_experiment(m, _solver(abort_turn=2, abort_arm="B"), _grader, item_spec_bytes=SPEC, out_dir=tmp_path)
    assert rec["readout"]["state"] == "NO_VERDICT"
    assert "not eligible" in rec["readout"]["reason"]


def _run_standalone() -> int:
    import tempfile
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            if fn.__code__.co_argcount:
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
                fn()
            print(f"  ok  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
