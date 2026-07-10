#!/usr/bin/env python3
"""Tests for scripts/capture_roi.py — projection math and its discipline.

Runs under pytest or standalone, stdlib only.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import capture_roi as roi  # noqa: E402


def _cap(**over):
    c = {
        "capture_id": "x",
        "capture_cost_usd": 0.6805,
        "cost_basis": "real-billed",
        "old_path": {"cost_usd_per_trial": 0.04, "cost_basis": "shadow-estimated"},
        "new_path": {"cost_usd_per_trial": 0.227, "cost_basis": "real-billed"},
        "validated_replays": 0,
    }
    c.update(over)
    return c


def test_worked_example_break_even_is_4():
    # savings 0.187/replay; 0.6805 / 0.187 = 3.639 -> ceil 4
    r = roi.roi_for(_cap())
    assert r["projected_break_even_replays"] == 4
    assert abs(r["savings_per_replay_usd"] - 0.187) < 1e-9
    assert r["roi_state"] == "needs_replay"
    assert "projection only" in r["note"]


def test_mixed_basis_is_named():
    r = roi.roi_for(_cap())
    assert "MIXED" in r["basis_caveat"]
    assert r["cost_basis_mix"] == ["real-billed", "shadow-estimated"]


def test_uniform_basis_is_named():
    r = roi.roi_for(_cap(cost_basis="real-billed",
                         old_path={"cost_usd_per_trial": 0.04, "cost_basis": "real-billed"},
                         new_path={"cost_usd_per_trial": 0.227, "cost_basis": "real-billed"}))
    assert r["basis_caveat"] == "uniform"


def test_missing_costs_is_unmeasured_not_guessed():
    r = roi.roi_for(_cap(old_path={"model": "m"}))
    assert r["roi_state"] == "UNMEASURED"
    assert "projected_break_even_replays" not in r


def test_no_savings_cannot_amortize():
    r = roi.roi_for(_cap(old_path={"cost_usd_per_trial": 0.30},
                         new_path={"cost_usd_per_trial": 0.227}))
    assert r["roi_state"] == "NO_SAVINGS"
    assert "projected_break_even_replays" not in r


def test_replays_move_state_but_only_threshold_closes():
    r = roi.roi_for(_cap(validated_replays=2))
    assert r["roi_state"] == "amortizing"
    assert r["replays_remaining_to_break_even"] == 2
    assert abs(r["retired_value_usd"] - 2 * 0.187) < 1e-9
    r = roi.roi_for(_cap(validated_replays=4))
    assert r["roi_state"] == "amortized"
    assert r["replays_remaining_to_break_even"] == 0


def test_zero_replays_never_amortized_regardless_of_projection():
    # even a capture that would break even in 1 replay stays needs_replay at 0
    r = roi.roi_for(_cap(capture_cost_usd=0.01))
    assert r["projected_break_even_replays"] == 1
    assert r["roi_state"] == "needs_replay"


def test_committed_ledger_loads_and_reports():
    caps = roi.load_captures()
    assert caps, "expected the task02 worked example"
    reports = [roi.roi_for(c) for c in caps]
    by_id = {r["capture_id"]: r for r in reports}
    r = by_id["task02_escape_class_boundary"]
    assert r["projected_break_even_replays"] == 4
    # Two validated replays landed 2026-07-10 — the crossing event and replay03
    # (validate_patterns), each a distinct hash-bound replay-receipt@1. The row is
    # amortizing, 2 of 4, and stays NON-CLOSED until 2 more distinct replays.
    assert r["roi_state"] == "amortizing"
    assert r["validated_replays"] == 2
    assert r["replays_remaining_to_break_even"] == 2


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
