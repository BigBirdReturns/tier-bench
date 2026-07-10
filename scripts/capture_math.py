#!/usr/bin/env python3
"""The ONE capture ROI calculation, shared by capture_roi.py and
validate_capture_ledger.py.

P1 remediation (2026-07-10): projected break-even was previously computed only
in capture_roi.py while the validator accepted the row's own declared numbers —
two authorities that could drift, and closure could ride the softer one. This
module is now the single arithmetic authority. The ledger's
`break_even_reuse_count` is never an input to any decision; it is validated
AGAINST this computation.

Pure functions, stdlib only, no I/O.
"""
from __future__ import annotations

import math

__all__ = ["savings_per_replay", "projected_break_even"]


def savings_per_replay(old_cost_per_trial, new_cost_per_trial):
    """USD saved each time the floor+artifact path replaces the retired call.

    new_path = the frontier call being retired; old_path = the floor the replay
    runs on (docs/frontier-capture.md). Returns None when either cost is
    missing — absence of data is an answer, never a guess.
    """
    if old_cost_per_trial is None or new_cost_per_trial is None:
        return None
    return new_cost_per_trial - old_cost_per_trial


def projected_break_even(capture_cost_usd, old_cost_per_trial, new_cost_per_trial):
    """ceil(capture_cost / savings_per_replay), or None when unmeasurable.

    None means either a cost is missing (UNMEASURED) or the floor path is not
    cheaper than the retired call (NO_SAVINGS) — in both cases no break-even
    threshold exists and no closure may cite one.
    """
    savings = savings_per_replay(old_cost_per_trial, new_cost_per_trial)
    if savings is None or savings <= 0 or capture_cost_usd is None:
        return None
    return math.ceil(capture_cost_usd / savings)
