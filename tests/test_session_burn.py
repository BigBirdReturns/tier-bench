#!/usr/bin/env python3
"""Tests for experiments/breadth/session_burn.py — the quota estimator must be
honest: reject malformed rows, never invent a ceiling, never mix units, and label
single-source vs corroborated.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "experiments" / "breadth"))

import session_burn as sb  # noqa: E402


def _row(**over):
    row = {"session_id": "S", "model": "claude-fable-5", "started": "2026-07-11T00:00:00Z",
           "end_reason": "quota_exhausted", "budget_metric": "subagent_trials",
           "budget_consumed": 30, "evidence_class": "measured"}
    row.update(over)
    return row


def test_valid_row_passes():
    assert sb.validate_row(_row()) == []


def test_bad_end_reason_rejected():
    assert any("end_reason" in e for e in sb.validate_row(_row(end_reason="ran_out")))


def test_bad_metric_rejected():
    assert any("budget_metric" in e for e in sb.validate_row(_row(budget_metric="vibes")))


def test_negative_consumed_rejected():
    assert any("budget_consumed" in e for e in sb.validate_row(_row(budget_consumed=-1)))


def test_missing_field_rejected():
    r = _row()
    del r["evidence_class"]
    assert any("evidence_class" in e for e in sb.validate_row(r))


def test_log_rejects_invalid(tmp_path):
    try:
        sb.log_session(tmp_path / "b.jsonl", session_id="S", model="m")
    except ValueError:
        return
    raise AssertionError("expected ValueError on invalid row")


def test_conservative_quota_is_min_of_exhausted():
    rows = [_row(session_id="S1", budget_consumed=40),
            _row(session_id="S2", budget_consumed=25),
            _row(session_id="S3", budget_consumed=33)]
    q = sb.functional_quota(rows, "subagent_trials")
    assert q["state"] == "measured"
    assert q["conservative_functional_quota"] == 25   # you can reliably reach the MIN
    assert q["median_exhaustion"] == 33
    assert q["corroboration"] == "corroborated"


def test_single_source_labeled():
    q = sb.functional_quota([_row()], "subagent_trials")
    assert q["corroboration"] == "single-source"


def test_no_exhausted_is_unmeasured_not_guessed():
    # only completed sessions -> the ceiling is UNMEASURED, only bounded below
    rows = [_row(end_reason="completed", budget_consumed=50)]
    q = sb.functional_quota(rows, "subagent_trials")
    assert q["state"] == "UNMEASURED"
    assert q["lower_bound_from_completed"] == 50


def test_metric_isolation_no_unit_mixing():
    # a usd row must not contaminate a subagent_trials report
    rows = [_row(budget_consumed=30),
            _row(session_id="S2", budget_metric="usd", budget_consumed=9.99)]
    q = sb.functional_quota(rows, "subagent_trials")
    assert q["exhaustion_observations"] == 1  # the usd row is excluded
    assert q["conservative_functional_quota"] == 30


def test_invalid_metric_fails_closed():
    assert sb.functional_quota([_row()], "dollars")["state"] == "INVALID_METRIC"


def _run_standalone() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            if fn.__code__.co_argcount:
                import tempfile
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
