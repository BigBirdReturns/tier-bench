#!/usr/bin/env python3
"""Tests for experiments/breadth/quota.py — the self-calibrating quota gauge.

Runs under pytest or standalone, stdlib only.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from experiments.breadth import quota  # noqa: E402


def _events():
    # two completed windows (300 then 500 tokens before a wall), then an open one
    return [
        {"type": "spend", "calls": 1, "tokens": 100},
        {"type": "spend", "calls": 1, "tokens": 200},
        {"type": "limit_hit"},
        {"type": "spend", "calls": 1, "tokens": 200},
        {"type": "spend", "calls": 1, "tokens": 300},
        {"type": "limit_hit"},
        {"type": "spend", "calls": 1, "tokens": 150},
    ]


def test_windows_split_and_open_window():
    w = quota.windows_from_events(_events())
    assert [x["tokens"] for x in w["completed"]] == [300.0, 500.0]
    assert w["current"]["tokens"] == 150.0 and w["current"]["spends"] == 1


def test_safe_is_smallest_likely_is_median():
    g = quota.gauge_from_events(_events())
    assert g["tokens"]["known"] is True
    assert g["tokens"]["safe"] == 300.0          # count on the smallest observed window
    assert g["tokens"]["likely"] == 400.0        # median of [300, 500]
    assert g["tokens"]["checkpoint_at"] == 240.0  # 0.8 * safe
    assert g["calls"]["safe"] == 2.0


def test_open_window_tracks_approach():
    g = quota.gauge_from_events(_events())
    t = g["tokens"]
    assert t["current_burned"] == 150.0
    assert t["remaining_to_safe"] == 150.0
    assert t["approaching"] is False              # 150 < checkpoint 240


def test_no_completed_window_is_unmeasured_not_infinite():
    g = quota.gauge_from_events([{"type": "spend", "tokens": 999999}])
    assert g["tokens"]["known"] is False
    assert "UNMEASURED" in g["tokens"]["note"]


def test_double_limit_hit_emits_no_empty_window():
    ev = [{"type": "spend", "tokens": 100}, {"type": "limit_hit"}, {"type": "limit_hit"}]
    w = quota.windows_from_events(ev)
    assert len(w["completed"]) == 1


def test_fit_refuses_unmeasured_quota():
    plan = quota.fit_run(9, per_trial_tokens=1000, quota_tokens=None)
    assert plan["sizable"] is False
    assert "UNMEASURED" in plan["reason"]


def test_fit_sizes_quarters_within_warn_band():
    # quota 4000 tok, warn 0.8 -> usable 3200; per-trial 400 -> 8 trials/window
    plan = quota.fit_run(6, per_trial_tokens=400, quota_tokens=4000, quarters=4)
    assert plan["sizable"] and plan["fits_one_window"] is True
    assert plan["metrics"]["tokens"]["trials_per_window"] == 8
    # a run that fits in one window quarters the RUN (6), not the window headroom (8)
    assert sum(c["trials"] for c in plan["quarter_plan"]) == 6
    assert plan["quarter_plan"][-1]["cumulative"] == 6


def test_fit_reports_multiple_windows_when_run_exceeds_quota():
    # 20 trials * 1000 tok = 20000; usable per window 0.8*4000 = 3200 -> 3/window -> 7 windows
    plan = quota.fit_run(20, per_trial_tokens=1000, quota_tokens=4000)
    assert plan["fits_one_window"] is False
    assert plan["metrics"]["tokens"]["windows_needed"] == 7


def test_binding_metric_is_the_tighter_wall():
    # tokens allow many, calls allow few -> calls binds
    plan = quota.fit_run(10, per_trial_tokens=10, quota_tokens=100000,
                         per_trial_calls=1, quota_calls=8)
    assert plan["binding_metric"] == "calls"


def test_per_trial_from_ledger_excludes_cache_reads():
    rows = [{"input_tokens": 20, "output_tokens": 100, "cache_write_tokens": 80,
             "cache_read_tokens": 40000}]
    assert quota.per_trial_from_ledger(rows, "tokens") == 200.0
    assert quota.per_trial_from_ledger(rows, "calls") == 1.0
    assert quota.per_trial_from_ledger([], "tokens") is None


def test_filter_by_account_separates_meters():
    # a Plus wall and a Max20x wall are different meters — must not pool
    events = [
        {"type": "spend", "tokens": 100, "account": "plus"},
        {"type": "limit_hit"},
        {"type": "spend", "tokens": 900, "account": "max20x"},
        {"type": "spend", "tokens": 800},  # untagged legacy row (unknown lineage)
    ]
    # None → unfiltered, everything kept (back-compat / original behavior)
    assert len(quota.filter_by_account(events, None)) == 4
    # a specific account keeps only its explicitly-tagged rows + wall markers;
    # the untagged legacy row is excluded, never silently attributed
    max_ev = quota.filter_by_account(events, "max20x")
    assert max_ev == [{"type": "limit_hit"}, {"type": "spend", "tokens": 900, "account": "max20x"}]
    plus_ev = quota.filter_by_account(events, "plus")
    assert plus_ev == [{"type": "spend", "tokens": 100, "account": "plus"}, {"type": "limit_hit"}]
    # gauging the filtered stream: max20x has no CLOSED window → UNMEASURED,
    # not inflated by the Plus window
    assert quota.gauge_from_events(max_ev)["tokens"]["known"] is False


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
